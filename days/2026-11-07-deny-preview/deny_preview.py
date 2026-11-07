#!/usr/bin/env python3
"""deny-preview — `permissions.denyInsteadOfPrompting`을 켜기 전에 "무엇이 조용히 거절될지" 미리 본다.

settings.json의 permissions 규칙(allow/ask/deny, defaultMode)과 도구 호출 목록을 넣으면
호출마다 ALLOW / DENY / ASK→DENY / PROMPT→DENY 로 나눠 보여 준다.
도구 호출 목록은 한 줄에 `Bash(npm test)` 같은 텍스트이거나, 세션 기록(JSONL, ~/.claude/projects/...).
표준 라이브러리만 쓴다. 모델·네트워크 호출 없음.

주의: Claude Code의 실제 판정(자동 모드 분류기, 관리 설정 우선순위, 규칙 문법 전체)을 그대로 따라 하지 않는
근사다. 규칙을 켜기 전에 어디를 봐야 하는지 알려 주는 용도다.
"""
import argparse
import json
import os
import re
import shlex
import sys
from collections import OrderedDict

READ_ONLY = {"Read", "Glob", "Grep", "LS", "NotebookRead", "TodoWrite", "Task", "Agent", "ToolSearch"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
PATH_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "Glob", "Grep", "LS"}
SPLIT_RE = re.compile(r"\s*(?:&&|\|\||;|\||\n)\s*")


# ── 설정 읽기 ───────────────────────────────────────────────────────────
def load_settings(paths):
    """여러 settings 파일을 합친다. 폴더면 .claude/settings(.local).json을 찾는다."""
    files = []
    for p in paths:
        if os.path.isdir(p):
            for rel in (".claude/settings.json", ".claude/settings.local.json", "settings.json", "settings.local.json"):
                f = os.path.join(p, rel)
                if os.path.isfile(f) and f not in files:
                    files.append(f)
        else:
            files.append(p)
    merged = {"allow": [], "ask": [], "deny": [], "defaultMode": None, "deny_instead": None, "files": []}
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as e:
            raise SystemExit("설정을 읽지 못했다: %s (%s)" % (f, e))
        perm = data.get("permissions") or {}
        for k in ("allow", "ask", "deny"):
            for r in perm.get(k) or []:
                if isinstance(r, str) and r not in merged[k]:
                    merged[k].append(r)
        if perm.get("defaultMode"):
            merged["defaultMode"] = perm["defaultMode"]
        if "denyInsteadOfPrompting" in perm:
            merged["deny_instead"] = bool(perm["denyInsteadOfPrompting"])
        merged["files"].append(f)
    return merged


# ── 규칙 파싱·매칭 ──────────────────────────────────────────────────────
def parse_rule(rule):
    m = re.fullmatch(r"([A-Za-z0-9_\-\.\*]+)(?:\((.*)\))?", rule.strip(), re.S)
    if not m:
        return rule.strip(), None
    return m.group(1), m.group(2)


def tool_matches(rule_tool, tool):
    if rule_tool == tool:
        return True
    if "*" in rule_tool:
        return re.fullmatch(re.escape(rule_tool).replace(r"\*", ".*"), tool) is not None
    # 맨몸 MCP 서버 규칙 mcp__a 는 서버 a의 도구만 (2.1.299 이후 의미)
    if tool.startswith("mcp__") and rule_tool.startswith("mcp__") and rule_tool.count("__") == 1:
        return tool.startswith(rule_tool + "__")
    return False


def glob_re(spec, path_like):
    out, i = "", 0
    while i < len(spec):
        c = spec[i]
        if c == "*":
            if spec[i:i + 2] == "**":
                out += ".*"
                i += 2
                if spec[i:i + 1] == "/":
                    i += 1
                    out = out[:-2] + "(?:.*/)?"
                continue
            out += "[^/]*" if path_like else ".*"
        else:
            out += re.escape(c)
        i += 1
    return re.compile(out, re.S)


def normalize_command(cmd):
    """따옴표 낀 단어를 벗겨 규칙과 같은 모양으로 맞춘다 (`rm "-rf" x` → `rm -rf x`)."""
    try:
        return " ".join(shlex.split(cmd, posix=True))
    except ValueError:
        return cmd.strip()


def spec_matches(tool, spec, arg):
    if spec is None or spec == "*":
        return True
    if arg is None:
        return False
    if tool == "Bash":
        cand = {arg.strip(), normalize_command(arg)}
        if spec.endswith(":*"):  # 옛 접두 문법 Bash(npm run:*)
            pre = spec[:-2]
            return any(c == pre or c.startswith(pre + " ") for c in cand)
        rx = glob_re(spec, False)
        return any(rx.fullmatch(c) for c in cand)
    if tool == "WebFetch":
        if spec.startswith("domain:"):
            host = re.sub(r"^[a-z]+://", "", arg).split("/")[0].split(":")[0]
            want = spec[7:]
            return host == want or host.endswith("." + want)
        return glob_re(spec, False).fullmatch(arg) is not None
    if tool in PATH_TOOLS:
        a = arg.lstrip("./") if arg.startswith("./") else arg
        s = spec.lstrip("./") if spec.startswith("./") else spec
        return glob_re(s, True).fullmatch(a) is not None
    return glob_re(spec, False).fullmatch(arg) is not None


def rule_hits(rules, tool, arg):
    """규칙 목록에서 이 호출에 걸리는 첫 규칙. Bash 복합 명령은 부분 명령 하나라도 걸리면 걸린 것."""
    parts = [arg]
    if tool == "Bash" and arg:
        parts = [p for p in SPLIT_RE.split(arg) if p.strip()] or [arg]
    for r in rules:
        rt, spec = parse_rule(r)
        if not tool_matches(rt, tool):
            continue
        if spec is None or any(spec_matches(tool, spec, p) for p in parts) or spec_matches(tool, spec, arg):
            return r
    return None


def allow_covers(rules, tool, arg):
    """allow는 모든 부분 명령이 허용 규칙에 걸려야 허용."""
    if tool == "Bash" and arg:
        parts = [p for p in SPLIT_RE.split(arg) if p.strip()] or [arg]
        if len(parts) > 1:
            hits = [rule_hits(rules, tool, p) for p in parts]
            return hits[0] if all(hits) else None
    return rule_hits(rules, tool, arg)


def decide(cfg, tool, arg):
    """(결과, 근거). 결과: ALLOW | DENY | ASK→DENY | PROMPT→DENY"""
    r = rule_hits(cfg["deny"], tool, arg)
    if r:
        return "DENY", "deny 규칙 %s" % r
    r = rule_hits(cfg["ask"], tool, arg)
    if r:
        return "ASK→DENY", "ask 규칙 %s (확인창이 뜰 자리)" % r
    r = allow_covers(cfg["allow"], tool, arg)
    if r:
        return "ALLOW", "allow 규칙 %s" % r
    mode = cfg["defaultMode"] or "default"
    if mode == "bypassPermissions":
        return "ALLOW", "defaultMode bypassPermissions"
    if tool in READ_ONLY:
        return "ALLOW", "읽기 전용 도구"
    if mode == "acceptEdits" and tool in EDIT_TOOLS:
        return "ALLOW", "defaultMode acceptEdits"
    return "PROMPT→DENY", "맞는 규칙이 없어 확인창이 뜰 자리"


# ── 호출 목록 읽기 ──────────────────────────────────────────────────────
CALL_RE = re.compile(r"([A-Za-z0-9_\-\.]+)(?:\((.*)\))?")


def arg_of(tool, inp):
    if not isinstance(inp, dict):
        return None
    if tool == "Bash":
        return inp.get("command")
    if tool == "WebFetch":
        return inp.get("url")
    if tool in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit"):
        return inp.get("file_path") or inp.get("notebook_path")
    if tool in ("Glob", "Grep"):
        return inp.get("path") or inp.get("pattern")
    return None


def read_calls(path):
    text = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    calls = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("{"):
            try:
                obj = json.loads(s)
            except ValueError:
                continue
            content = (obj.get("message") or {}).get("content")
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        calls.append((b.get("name", "?"), arg_of(b.get("name"), b.get("input"))))
            continue
        m = CALL_RE.fullmatch(s)
        if m:
            calls.append((m.group(1), m.group(2)))
    return calls


def suggest(cfg, tool, arg):
    """거절을 피할 allow 후보 한 줄. Bash 복합 명령은 아직 허용 안 된 첫 부분 명령 기준."""
    if tool == "Bash" and arg:
        for part in [p for p in SPLIT_RE.split(arg) if p.strip()]:
            if rule_hits(cfg["allow"], tool, part):
                continue
            words = normalize_command(part).split()
            if words:
                return "Bash(%s:*)" % (" ".join(words[:2]) if len(words) > 1 and not words[1].startswith("-") else words[0])
    if tool == "WebFetch" and arg:
        return "WebFetch(domain:%s)" % re.sub(r"^[a-z]+://", "", arg).split("/")[0]
    if tool in PATH_TOOLS and arg:
        return "%s(%s)" % (tool, arg)
    return tool


def main(argv=None):
    ap = argparse.ArgumentParser(prog="deny_preview", description=__doc__.split("\n")[0])
    ap.add_argument("calls", nargs="+", help="도구 호출 목록 파일(텍스트 또는 JSONL). `-`는 표준입력")
    ap.add_argument("-s", "--settings", action="append", default=[], help="settings.json 또는 프로젝트 폴더 (여러 번 가능)")
    ap.add_argument("--json", action="store_true", help="JSON으로 출력")
    ap.add_argument("--strict", action="store_true", help="거절될 호출이 하나라도 있으면 exit 1")
    ap.add_argument("-v", "--verbose", action="store_true", help="허용된 호출도 나열")
    a = ap.parse_args(argv)

    cfg = load_settings(a.settings) if a.settings else {"allow": [], "ask": [], "deny": [], "defaultMode": None, "deny_instead": None, "files": []}
    calls = []
    for p in a.calls:
        try:
            calls += read_calls(p)
        except OSError as e:
            print("호출 목록을 읽지 못했다: %s (%s)" % (p, e), file=sys.stderr)
            return 2
    if not calls:
        print("도구 호출이 하나도 없다 (형식: `Bash(npm test)` 한 줄씩, 또는 세션 JSONL)", file=sys.stderr)
        return 2

    agg = OrderedDict()
    for tool, arg in calls:
        key = (tool, arg)
        res, why = decide(cfg, tool, arg)
        if key in agg:
            agg[key]["n"] += 1
        else:
            agg[key] = {"tool": tool, "arg": arg, "result": res, "why": why, "n": 1}
    rows = list(agg.values())
    totals = {}
    for r in rows:
        totals[r["result"]] = totals.get(r["result"], 0) + r["n"]
    denied = [r for r in rows if r["result"] != "ALLOW"]
    sug = OrderedDict()
    for r in rows:
        if r["result"] == "PROMPT→DENY":
            k = suggest(cfg, r["tool"], r["arg"])
            sug[k] = sug.get(k, 0) + r["n"]

    if a.json:
        print(json.dumps({"denyInsteadOfPrompting": cfg["deny_instead"], "totals": totals, "calls": rows,
                          "suggest_allow": list(sug)}, ensure_ascii=False, indent=2))
    else:
        flag = {True: "켜짐", False: "꺼짐(false)", None: "설정 없음"}[cfg["deny_instead"]]
        print("설정: %s | defaultMode=%s | denyInsteadOfPrompting %s" % (", ".join(cfg["files"]) or "(없음)", cfg["defaultMode"] or "default", flag))
        print("규칙: allow %d · ask %d · deny %d" % (len(cfg["allow"]), len(cfg["ask"]), len(cfg["deny"])))
        print("호출 %d건 (서로 다른 호출 %d종)" % (len(calls), len(rows)))
        print()
        for r in rows:
            if r["result"] == "ALLOW" and not a.verbose:
                continue
            label = r["tool"] + ("(%s)" % r["arg"] if r["arg"] is not None else "")
            print("%-12s ×%-3d %s\n             └ %s" % (r["result"], r["n"], label[:110], r["why"]))
        print()
        print("요약: " + " · ".join("%s %d" % (k, totals[k]) for k in ("ALLOW", "DENY", "ASK→DENY", "PROMPT→DENY") if k in totals))
        if cfg["deny_instead"] is not True:
            stuck = totals.get("ASK→DENY", 0) + totals.get("PROMPT→DENY", 0)
            if stuck:
                print("지금(설정 꺼짐): 위 %d건은 사람이 답할 때까지 확인창에서 멈춘다. 무인 실행이면 거기서 끝난다." % stuck)
        else:
            print("설정 켜짐: ASK/PROMPT 표시 호출은 멈추지 않고 거절되고, 거절 뒤 턴은 이어진다.")
        if sug:
            print("거절을 피하려면 allow 후보 (규칙이 없어 거절될 호출만. ask·deny 규칙은 의도라 건드리지 않음):")
            for k, n in sug.items():
                print("  \"%s\"   (%d건)" % (k, n))
    return 1 if (a.strict and denied) else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""mcp-rule-audit — Claude Code 2.1.299에서 의미가 바뀐 MCP 권한 규칙을 찾는다.

MCP 도구 이름은 `mcp__<서버>__<도구>` 한 줄이고 서버·도구 이름에도 `__`가 들어갈 수 있어
문자열이 모호하다. 2.1.299 이전에는 맨몸 허용 규칙 `mcp__a`가 서버 `a__b`·`a_x`까지 덮었고,
`mcp__a__b` 같은 deny·ask 규칙은 "서버 a의 도구 b"로 읽혔다. 2.1.299부터 `mcp__a`는 서버 a만 덮는다.
이 도구는 설정 JSON·.mcp.json·서브에이전트 정의·워크플로의 --allowedTools에서 그런 규칙을 찾아
서버 전체 이름에 `__*`를 붙인 형태로 고쳐 쓰라고 제안한다. 표준 라이브러리만 쓰고 네트워크·모델을 쓰지 않는다.

종료 코드: 0=error 없음, 1=error(--strict면 warn도), 2=읽을 파일 없음/경로 오류.
"""
import argparse
import json
import os
import re
import sys

NORM = re.compile(r"[^A-Za-z0-9_-]")
TOKEN = re.compile(r"mcp__[A-Za-z0-9_\-*]+")
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv"}
WF_HINT = re.compile(r"allowedTools|disallowedTools|allowed_tools|disallowed_tools|claude_args|--tools", re.I)

CODES = {
    "MR001": "맨몸 규칙이 이름이 겹치는 다른 서버까지 덮던 규칙",
    "MR002": "맨몸 서버 규칙(참고)",
    "MR003": "`__`가 든 서버 이름 전체를 도구 규칙처럼 쓴 규칙",
    "MR004": "서버/도구 경계가 둘 이상으로 읽히는 규칙",
    "MR005": "서버 이름에 `__` 포함",
}


def norm(name):
    return NORM.sub("_", name)


def find_line(lines, needle, start=0):
    for i in range(start, len(lines)):
        if needle in lines[i]:
            return i + 1
    for i in range(0, start):
        if needle in lines[i]:
            return i + 1
    return 1


# ---------- 수집 ----------

def walk_json(node, out_rules, out_servers):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "permissions" and isinstance(v, dict):
                for kind in ("allow", "deny", "ask"):
                    for r in v.get(kind) or []:
                        if isinstance(r, str):
                            out_rules.append((kind, r))
            elif k == "allowedTools" and isinstance(v, list):
                out_rules.extend(("allow", r) for r in v if isinstance(r, str))
            elif k == "mcpServers" and isinstance(v, dict):
                out_servers.extend(v.keys())
            if k != "permissions":
                walk_json(v, out_rules, out_servers)
    elif isinstance(node, list):
        for v in node:
            walk_json(v, out_rules, out_servers)


def scan_json(path, text):
    try:
        data = json.loads(text)
    except ValueError as e:
        return [], [], [dict(file=path, line=1, level="error", code="MR000", rule="", msg=f"JSON 파싱 실패: {e}", fix="")]
    rules, servers = [], []
    walk_json(data, rules, servers)
    lines = text.splitlines()
    cursor = {}
    found = []
    for kind, r in rules:
        start = cursor.get(r, 0)
        ln = find_line(lines, json.dumps(r), start)
        cursor[r] = ln
        found.append((path, ln, kind, r))
    srv = [(path, find_line(lines, json.dumps(s)), s) for s in servers]
    return found, srv, []


def split_list(val):
    items, depth, cur = [], 0, ""
    for ch in val:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            items.append(cur)
            cur = ""
        else:
            cur += ch
    items.append(cur)
    return [i.strip().strip("'\"") for i in items if i.strip().strip("'\"")]


def scan_agent_md(path, text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return [], []
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return [], []
    out, i = [], 1
    while i < end:
        m = re.match(r"^(tools|disallowedTools)\s*:\s*(.*)$", lines[i])
        if m:
            kind = "allow" if m.group(1) == "tools" else "deny"
            vals = split_list(m.group(2)) if m.group(2).strip() else []
            j = i + 1
            while j < end and re.match(r"^\s*-\s+", lines[j]):
                vals.append(re.sub(r"^\s*-\s+", "", lines[j]).strip().strip("'\""))
                j += 1
            out.extend((path, i + 1, kind, v) for v in vals)
            i = j
            continue
        i += 1
    return out, []


def scan_workflow(path, text):
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if not WF_HINT.search(line):
            continue
        kind = "deny" if re.search(r"disallowed", line, re.I) else "allow"
        out.extend((path, n, kind, t) for t in TOKEN.findall(line))
    return out, []


def classify(path, explicit=False):
    p = path.replace(os.sep, "/")
    base = os.path.basename(p)
    if explicit:  # 직접 지정한 파일은 확장자만 보고 고른다
        if base.endswith(".json"):
            return "json"
        if base.endswith(".md"):
            return "agent"
        if base.endswith((".yml", ".yaml", ".sh")):
            return "workflow"
        return None
    if base.endswith(".json") and (base.startswith("settings") or base in (".mcp.json", ".claude.json", "claude.json") or "/.claude/" in "/" + p):
        return "json"
    if base.endswith(".md") and "/agents/" in "/" + p:
        return "agent"
    if base.endswith((".yml", ".yaml", ".sh")):
        return "workflow"
    return None


def collect(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, names in os.walk(p):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
                for n in sorted(names):
                    fp = os.path.join(root, n)
                    if classify(fp):
                        files.append(fp)
        elif os.path.isfile(p):
            if classify(p, explicit=True):
                files.append(p)
        else:
            raise FileNotFoundError(p)
    return files


# ---------- 분석 ----------

def analyze(rules, servers, verbose=False):
    """rules: [(file, line, kind, rule)], servers: {정규화된 이름: [(file, line)]}"""
    out = []

    def add(f, ln, level, code, rule, msg, fix):
        out.append(dict(file=f, line=ln, level=level, code=code, rule=rule, msg=msg, fix=fix))

    for (f, ln, kind, rule) in rules:
        if not rule.startswith("mcp__"):
            continue
        body = rule[5:]
        if not body or body == "*":
            continue
        if body.endswith("__*"):
            continue
        if "__" not in body:
            clash = sorted(n for n in servers if n != body and n.startswith(body + "_"))
            if clash:
                level = "error" if kind == "allow" else "warn"
                effect = "허용" if kind == "allow" else ("차단" if kind == "deny" else "확인 요구")
                add(f, ln, level, "MR001", rule,
                    f"{kind} 규칙 `{rule}`는 2.1.299 이전 버전에서 서버 {', '.join(clash)}까지 {effect} 대상으로 삼았다 (2.1.299부터는 `{body}` 서버만)",
                    f"mcp__{body}__*")
            elif verbose:
                add(f, ln, "info", "MR002", rule,
                    f"맨몸 서버 규칙. 2.1.299부터 `{body}` 서버만 덮는다", f"mcp__{body}__*")
            continue
        splits = {body[:i] for i in range(len(body) - 1) if body[i:i + 2] == "__" and i > 0}
        cands = sorted(s for s in splits if s in servers)
        whole = body in servers
        if whole:
            cands = sorted(set(cands) | {body})
        if len(cands) >= 2:
            add(f, ln, "warn", "MR004", rule,
                f"`{rule}`는 서버 {' 또는 '.join(cands)}로 읽힐 수 있다",
                " / ".join(f"mcp__{s}__*" for s in cands))
        elif whole:
            first = body.split("__", 1)
            add(f, ln, "warn", "MR003", rule,
                f"`{rule}`는 이제 서버 `{first[0]}`의 도구 `{first[1]}`로 읽힌다. 서버 `{body}` 전체를 뜻했다면 어긋난다",
                f"mcp__{body}__*")

    for name, srcs in sorted(servers.items()):
        if "__" in name:
            f, ln = srcs[0]
            add(f, ln, "warn", "MR005", name,
                f"서버 이름 `{name}`에 `__`가 있어 `mcp__<서버>__<도구>` 경계가 모호하다",
                f"이름을 `{name.replace('__', '-')}`처럼 하이픈으로")
    order = {"error": 0, "warn": 1, "info": 2}
    out.sort(key=lambda x: (order[x["level"]], x["file"], x["line"], x["code"]))
    return out


def audit(paths, extra_servers=(), verbose=False):
    files = collect(paths)
    explicit = {p for p in paths if os.path.isfile(p)}
    rules, servers, problems = [], {}, []
    for fp in files:
        kind = classify(fp, explicit=fp in explicit)
        try:
            with open(fp, encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as e:
            problems.append(dict(file=fp, line=1, level="error", code="MR000", rule="", msg=f"읽기 실패: {e}", fix=""))
            continue
        if kind == "json":
            r, s, pr = scan_json(fp, text)
            problems += pr
            for (pf, pl, name) in s:
                servers.setdefault(norm(name), []).append((pf, pl))
        elif kind == "agent":
            r, _ = scan_agent_md(fp, text)
        elif kind == "workflow":
            r, _ = scan_workflow(fp, text)
        else:
            continue
        rules += r
    for s in extra_servers:
        servers.setdefault(norm(s), []).append(("--server", 1))
    findings = problems + analyze(rules, servers, verbose)
    return files, rules, servers, findings


def main(argv=None):
    ap = argparse.ArgumentParser(description="2.1.299에서 의미가 바뀐 MCP 권한 규칙 점검")
    ap.add_argument("paths", nargs="*", default=["."], help="파일 또는 폴더 (기본: 현재 폴더)")
    ap.add_argument("--server", action="append", default=[], help="스캔 대상 밖에 있는 서버 이름 추가 (반복 가능)")
    ap.add_argument("--strict", action="store_true", help="warn도 exit 1")
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    ap.add_argument("-v", "--verbose", action="store_true", help="info(MR002)도 표시")
    a = ap.parse_args(argv)
    try:
        files, rules, servers, findings = audit(a.paths, a.server, a.verbose)
    except FileNotFoundError as e:
        print(f"경로가 없다: {e}", file=sys.stderr)
        return 2
    if not files:
        print("점검할 설정·에이전트·워크플로 파일이 없다", file=sys.stderr)
        return 2
    n = {lv: sum(f["level"] == lv for f in findings) for lv in ("error", "warn", "info")}
    if a.json:
        print(json.dumps(dict(files=len(files), rules=sum(r[3].startswith("mcp__") for r in rules),
                              servers=sorted(servers), counts=n, findings=findings), ensure_ascii=False, indent=2))
    else:
        for f in findings:
            print(f"{f['file']}:{f['line']}: {f['level']} {f['code']} {f['msg']}")
            if f["fix"]:
                print(f"    → {f['fix']}")
        mcp_rules = sum(r[3].startswith("mcp__") for r in rules)
        print(f"파일 {len(files)}개 · MCP 규칙 {mcp_rules}개 · 서버 {len(servers)}개 — error {n['error']} · warn {n['warn']}")
    bad = n["error"] + (n["warn"] if a.strict else 0)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""verify-gate — `git commit` 직전에 "이 세션에서 검증했다"는 증거를 보는 PreToolUse 훅.

claude.dev 11-16 글(Claude Code 팀의 검증 방식)의 커밋 게이트를 작게 옮긴 것:
  - 모드 off / observe / enforce (처음엔 observe: 막을 뻔한 것만 기록)
  - 증거 = 세션 기록의 `/verify`·`/code-review` 슬래시 명령 또는 Skill 호출
    (설정으로 `bash test.sh` 같은 Bash 명령도 증거로 인정)
  - 증거가 마지막 파일 수정보다 앞이면 "stale" — 오래된 커밋에 대한 통과는 의미 없다
  - 커밋 메시지에 `Unverified: 이유`가 있으면 면제
  - 한 세션에서 두 번 막히면 세 번째는 통과(에이전트가 갇히지 않게)

표준 라이브러리만 쓴다. 모델·키·네트워크 불필요.

  verify_gate.py hook                 # PreToolUse 훅 (stdin: 도구 호출 JSON)
  verify_gate.py check -t 기록.jsonl  # 이 기록이 검증됐는지 (종료 코드 0/1)
  verify_gate.py report [-d 폴더]     # 로그 요약
  verify_gate.py print-settings       # settings.json에 넣을 훅 등록 조각
"""
import argparse
import collections
import datetime
import json
import os
import re
import shlex
import sys

MODES = ("off", "observe", "enforce")
DEFAULTS = {
    "mode": "observe",
    "slash": ["verify", "code-review"],
    "skills": ["verify", "code-review"],
    "bash": [],          # 증거로 인정할 Bash 명령 정규식 (예: "bash test\\.sh")
    "max_blocks": 2,     # 세션당 이만큼 막으면 다음 커밋은 통과
    "bash_edits": True,  # 셸로 파일을 쓴 흔적(> , tee, sed -i, mv …)도 "수정"으로 센다
}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
WAIVER = re.compile(r"(?:\bUnverified:[ \t]*([^\s\"'`].*)|\[skip-verify:[ \t]*([^\]\s][^\]]*)\])")
GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}


# ---------- 명령 해석 ----------

def split_segments(cmd):
    """따옴표 밖의 ; & | 줄바꿈 ( ) 에서 명령을 나눈다."""
    segs, cur, q, esc = [], [], None, False
    for ch in cmd:
        if esc:
            cur.append(ch); esc = False; continue
        if ch == "\\" and q != "'":
            cur.append(ch); esc = True; continue
        if q:
            cur.append(ch)
            if ch == q:
                q = None
            continue
        if ch in "'\"":
            q = ch; cur.append(ch); continue
        if ch in ";&|\n()":
            segs.append("".join(cur)); cur = []; continue
        cur.append(ch)
    segs.append("".join(cur))
    return [s.strip() for s in segs if s.strip()]


def is_commit_segment(seg, depth=0):
    try:
        toks = shlex.split(seg)
    except ValueError:
        return bool(re.search(r"\bgit\b.*\bcommit\b", seg))
    while toks and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]):
        toks.pop(0)                      # FOO=bar git commit
    if not toks:
        return False
    if toks[0] in ("bash", "sh", "zsh") and "-c" in toks and depth < 3:
        i = toks.index("-c")
        if i + 1 < len(toks):
            return is_commit_command(toks[i + 1], depth + 1)
        return False
    if toks[0] == "git":
        i = 1
        while i < len(toks) and toks[i].startswith("-"):
            i += 2 if toks[i] in GIT_VALUE_OPTS else 1
        return i < len(toks) and toks[i] == "commit"
    return False


def is_commit_command(cmd, depth=0):
    return any(is_commit_segment(s, depth) for s in split_segments(cmd))


HEREDOC = re.compile(r"(<<-?[ \t]*(['\"]?)(\w+)\2[^\n]*\n).*?\n[ \t]*\3[ \t]*(?=\n|$)", re.S)
QUOTED = re.compile(r"'[^']*'|\"(?:\\.|[^\"\\])*\"")
BASH_WRITE = re.compile(
    r"(?<![0-9&<>])>>?(?!&)[ \t]*(?!/dev/null)\S"          # 파일로 리다이렉트 (2>&1, >/dev/null 제외)
    r"|\btee\b|\bsed\s+(?:-\w*i|--in-place)|\b(?:mv|cp|rm|touch|patch|truncate)\b|\bgit\s+apply\b")


def command_segments(cmd):
    """heredoc 본문을 뺀 뒤 명령 단위로 나눈다 — 본문에 적힌 글자에 반응하지 않기 위해."""
    return split_segments(HEREDOC.sub(r"\1", cmd))


def bash_writes_files(cmd):
    for seg in command_segments(cmd):
        if BASH_WRITE.search(QUOTED.sub("''", seg)):
            return True
    return False


def bash_runs(cmd, regexes):
    """설정한 정규식이 어떤 명령의 맨 앞(환경변수 뒤)에 맞을 때만, 맞은 명령 조각을 돌려준다."""
    for seg in command_segments(cmd):
        seg = re.sub(r"^(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)+", "", seg)
        if any(r.match(seg) for r in regexes):
            return seg
    return None


def waiver_reason(cmd):
    m = WAIVER.search(cmd or "")
    if not m:
        return None
    return (m.group(1) or m.group(2) or "").strip().rstrip("\"')` ")[:100]


# ---------- 세션 기록 읽기 ----------

def _name_matches(name, wanted):
    name = (name or "").lstrip("/")
    return name in wanted or name.split(":")[-1] in wanted


def read_transcript(path):
    """줄 번호가 있는 (kind, 줄) 이벤트 목록을 만든다."""
    events = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                events.append((n, json.loads(line)))
            except ValueError:
                continue
    return events


def evaluate(path, cfg):
    """-> dict(verdict, evidence, last_edit). verdict: verified|stale|none"""
    events = read_transcript(path)
    slash = set(cfg["slash"]); skills = set(cfg["skills"])
    bash_res = [re.compile(r) for r in cfg["bash"]]
    last_edit = -1
    evidence = []          # (줄, 설명)
    pending_bash = {}      # tool_use_id -> (줄, 설명)
    for n, o in events:
        msg = o.get("message") or {}
        content = msg.get("content")
        role = msg.get("role") or o.get("type")
        if role == "user":
            texts = []
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        texts.append(b.get("text", ""))
                    elif b.get("type") == "tool_result":
                        hit = pending_bash.pop(b.get("tool_use_id"), None)
                        if hit and not b.get("is_error"):
                            evidence.append(hit)
            for t in texts:
                for m in re.finditer(r"<command-name>\s*/?([^<\s]+)\s*</command-name>", t):
                    if _name_matches(m.group(1), slash):
                        evidence.append((n, "슬래시 /" + m.group(1)))
        elif role == "assistant" and isinstance(content, list):
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_use":
                    continue
                name, inp = b.get("name"), b.get("input") or {}
                if name in EDIT_TOOLS:
                    last_edit = n
                elif name == "Skill":
                    sk = inp.get("skill") or inp.get("name") or ""
                    if _name_matches(sk, skills):
                        evidence.append((n, "Skill " + sk))
                elif name == "Bash":
                    c = inp.get("command", "")
                    if cfg.get("bash_edits", True) and bash_writes_files(c):
                        last_edit = n
                    hit = bash_runs(c, bash_res) if bash_res else None
                    if hit:
                        pending_bash[b.get("id")] = (n, "Bash " + hit.splitlines()[0][:40])
    if not evidence:
        return {"verdict": "none", "evidence": None, "last_edit": last_edit}
    ev_line, ev_desc = max(evidence)
    verdict = "verified" if ev_line > last_edit else "stale"
    return {"verdict": verdict, "evidence": ev_desc, "last_edit": last_edit}


# ---------- 설정·상태 ----------

def project_dir(data):
    return os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()


def load_config(proj):
    cfg = json.loads(json.dumps(DEFAULTS))
    p = os.path.join(proj, ".claude", "verify-gate.json")
    if os.path.isfile(p):
        try:
            user = json.load(open(p, encoding="utf-8"))
            for k in DEFAULTS:
                if k in user:
                    cfg[k] = user[k]
        except (OSError, ValueError) as e:
            cfg["_warn"] = "설정 파일을 읽지 못해 기본값을 쓴다: %s" % e
    env = os.environ.get("VERIFY_GATE_MODE")
    if env:
        cfg["mode"] = env.strip().lower()
    if cfg["mode"] not in MODES:
        cfg["_warn"] = "알 수 없는 mode %r — observe로 대체" % cfg["mode"]
        cfg["mode"] = "observe"
    return cfg


def state_dir(proj):
    return os.environ.get("VERIFY_GATE_DIR") or os.path.join(proj, ".claude", "verify-gate")


def _safe(s):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s or "nosession")[:80]


def bump_blocks(sdir, session):
    d = os.path.join(sdir, "blocks"); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, _safe(session))
    try:
        n = int(open(p).read().strip() or 0)
    except (OSError, ValueError):
        n = 0
    return p, n


def log(sdir, rec):
    os.makedirs(sdir, exist_ok=True)
    rec = dict(rec, ts=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    with open(os.path.join(sdir, "log.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------- 훅 ----------

def block_message(res, cfg, left):
    why = {"none": "이 세션에 /verify나 /code-review를 돌린 흔적이 없다.",
           "stale": "마지막 검증(%s) 뒤에 파일이 또 바뀌었다." % res["evidence"]}[res["verdict"]]
    return ("verify-gate: 커밋을 막았다 — %s\n"
            "  1) /verify 또는 /code-review를 돌린 뒤 다시 커밋하거나\n"
            "  2) 검증하지 않는 이유가 있으면 커밋 메시지에 `Unverified: <이유>`를 적어라.\n"
            "  (이 세션에서 %d번 더 막히면 다음 커밋은 통과한다.)\n" % (why, left))


def run_hook(stdin, stderr):
    try:
        data = json.loads(stdin.read() or "{}")
    except ValueError:
        return 0                                   # 입력을 못 읽으면 열어 둔다(훅이 커밋을 못 쓰게 만들지 않는다)
    if data.get("tool_name") != "Bash":
        return 0
    cmd = (data.get("tool_input") or {}).get("command", "")
    if not is_commit_command(cmd):
        return 0
    proj = project_dir(data)
    cfg = load_config(proj)
    if cfg["mode"] == "off":
        return 0
    sdir = state_dir(proj)
    session = data.get("session_id") or "nosession"
    base = {"session": session, "mode": cfg["mode"]}
    if cfg.get("_warn"):
        stderr.write("verify-gate: %s\n" % cfg["_warn"])

    reason = waiver_reason(cmd)
    if reason:
        log(sdir, dict(base, verdict="waived", action="allowed", reason=reason))
        return 0
    tpath = data.get("transcript_path")
    if not tpath or not os.path.isfile(tpath):
        log(sdir, dict(base, verdict="unknown", action="allowed", reason="세션 기록 없음"))
        return 0
    try:
        res = evaluate(tpath, cfg)
    except OSError as e:
        log(sdir, dict(base, verdict="unknown", action="allowed", reason="기록 읽기 실패: %s" % e))
        return 0
    if res["verdict"] == "verified":
        log(sdir, dict(base, verdict="verified", action="allowed", evidence=res["evidence"]))
        return 0
    # none / stale
    if cfg["mode"] == "observe":
        log(sdir, dict(base, verdict=res["verdict"], action="would-block", evidence=res["evidence"]))
        return 0
    bpath, n = bump_blocks(sdir, session)
    if n >= int(cfg["max_blocks"]):
        log(sdir, dict(base, verdict=res["verdict"], action="released",
                       reason="이 세션에서 이미 %d번 막음" % n))
        return 0
    with open(bpath, "w") as f:
        f.write(str(n + 1))
    log(sdir, dict(base, verdict=res["verdict"], action="blocked", evidence=res["evidence"]))
    stderr.write(block_message(res, cfg, int(cfg["max_blocks"]) - n - 1))
    return 2


# ---------- check / report / print-settings ----------

def cmd_check(a):
    proj = a.project or os.getcwd()
    cfg = load_config(proj)
    try:
        res = evaluate(a.transcript, cfg)
    except OSError as e:
        print("읽기 실패:", e, file=sys.stderr)
        return 2
    print("%s  증거=%s  마지막 수정 줄=%s" % (res["verdict"], res["evidence"] or "-", res["last_edit"]))
    return 0 if res["verdict"] == "verified" else 1


def cmd_report(a):
    sdir = a.dir or state_dir(a.project or os.getcwd())
    p = os.path.join(sdir, "log.jsonl")
    if not os.path.isfile(p):
        print("로그 없음: %s (게이트가 한 번도 커밋을 보지 못했다)" % p)
        return 0
    recs, bad = [], 0
    for line in open(p, encoding="utf-8"):
        try:
            recs.append(json.loads(line))
        except ValueError:
            bad += 1
    by_v = collections.Counter(r.get("verdict") for r in recs)
    by_a = collections.Counter(r.get("action") for r in recs)
    total = len(recs)
    unver = by_v["none"] + by_v["stale"]
    out = {"total": total, "by_verdict": dict(by_v), "by_action": dict(by_a),
           "unverified_rate": round(unver / total, 3) if total else 0, "unreadable_lines": bad}
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    print("커밋 %d건 (읽지 못한 줄 %d)" % (total, bad))
    for v in ("verified", "stale", "none", "waived", "unknown"):
        if by_v[v]:
            print("  %-9s %3d" % (v, by_v[v]))
    print("처리: " + ", ".join("%s %d" % kv for kv in sorted(by_a.items())))
    print("검증 안 된 비율(stale+none): %.0f%%" % (100 * out["unverified_rate"]))
    miss = [r for r in recs if r.get("verdict") in ("none", "stale")][-5:]
    if miss:
        print("최근 검증 안 된 커밋:")
        for r in miss:
            print("  %s  %-7s → %s" % (r.get("ts"), r.get("verdict"), r.get("action")))
    return 0


def cmd_print_settings(a):
    here = os.path.abspath(__file__)
    print(json.dumps({"hooks": {"PreToolUse": [{
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": "python3 %s hook" % shlex.quote(here)}]}]}},
        indent=2))
    print("\n# mode는 .claude/verify-gate.json 의 {\"mode\": \"observe\"} 또는 환경변수 VERIFY_GATE_MODE", file=sys.stderr)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("hook")
    c = sub.add_parser("check"); c.add_argument("-t", "--transcript", required=True); c.add_argument("-p", "--project")
    r = sub.add_parser("report"); r.add_argument("-d", "--dir"); r.add_argument("-p", "--project"); r.add_argument("--json", action="store_true")
    sub.add_parser("print-settings")
    a = ap.parse_args(argv)
    if a.cmd == "hook":
        return run_hook(sys.stdin, sys.stderr)
    return {"check": cmd_check, "report": cmd_report, "print-settings": cmd_print_settings}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())

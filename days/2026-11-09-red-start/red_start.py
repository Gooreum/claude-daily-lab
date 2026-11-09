#!/usr/bin/env python3
"""red-start: SessionStart 훅. 빠른 점검 명령을 돌려 실패한 줄만 첫 컨텍스트로 넘긴다.

원칙(dev.to 11-09 글 + hook-manners 규칙):
- 항상 exit 0. 어떤 예외도 세션을 막지 않는다.
- 자체 데드라인. 시간 안에 못 끝나면 "상태 모름"이라는 사실만 적고 자식 프로세스까지 정리한다.
- 출력은 사실 문장만. "고쳐라" 같은 명령형은 쓰지 않는다.
- 출력 상한(기본 8000자). Claude Code는 1만 자를 넘으면 파일로 빼고 미리보기만 보여 준다.
표준 라이브러리만 쓴다.
"""
import json
import os
import re
import signal
import subprocess
import sys
import time

DEFAULT_BUDGET = 45        # 초. 설정 timeout(예: 60)보다 작게
DEFAULT_MAX_FAILS = 15
DEFAULT_MAX_LINE = 200
DEFAULT_MAX_CHARS = 8000
DEFAULT_SOURCES = ("startup", "resume")

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
# 러너마다 다른 실패 표기: pytest, TAP, go test, jest, test.sh 관례
FAIL_LINE = re.compile(
    r"^\s*(FAILED\b|ERROR\b|not ok\b|--- FAIL\b|FAIL\b|FAIL:|✗|✖|✘|\[FAIL\])"
)


def strip_ansi(s):
    return ANSI.sub("", s)


def load_config(project_dir):
    path = os.path.join(project_dir, ".claude", "red-start.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def autodetect(project_dir):
    """설정이 없을 때만. 가장 흔한 세 가지."""
    if os.path.isfile(os.path.join(project_dir, "test.sh")):
        return "bash test.sh"
    pkg = os.path.join(project_dir, "package.json")
    if os.path.isfile(pkg):
        try:
            with open(pkg, encoding="utf-8") as f:
                scripts = (json.load(f) or {}).get("scripts") or {}
            if "test" in scripts:
                return "npm test --silent"
        except (OSError, ValueError, AttributeError):
            pass
    for marker in ("pytest.ini", "tox.ini", "conftest.py"):
        if os.path.isfile(os.path.join(project_dir, marker)):
            return "python3 -m pytest -q --tb=no -rfE"
    return ""


def resolve(argv_cmd, project_dir):
    """우선순위: --cmd > RED_START_CMD > .claude/red-start.json > 자동 감지. (cmd, 출처) 반환"""
    cfg = load_config(project_dir)
    if argv_cmd:
        return argv_cmd, "--cmd", cfg
    if os.environ.get("RED_START_CMD"):
        return os.environ["RED_START_CMD"], "RED_START_CMD", cfg
    if isinstance(cfg.get("cmd"), str) and cfg["cmd"].strip():
        return cfg["cmd"].strip(), ".claude/red-start.json", cfg
    cmd = autodetect(project_dir)
    return cmd, ("자동 감지" if cmd else "없음"), cfg


def as_int(value, default, lo=1, hi=10_000_000):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def run_with_deadline(cmd, cwd, budget):
    """(returncode, output, seconds, timed_out). 시간 초과면 프로세스 그룹째 죽인다."""
    start = time.monotonic()
    proc = subprocess.Popen(
        ["sh", "-c", cmd], cwd=cwd, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace", start_new_session=True,
    )
    try:
        out, _ = proc.communicate(timeout=budget)
        return proc.returncode, out or "", time.monotonic() - start, False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        try:
            out, _ = proc.communicate(timeout=2)
        except Exception:
            out = ""
        return None, out or "", time.monotonic() - start, True


def clip(line, n):
    line = line.rstrip()
    return line if len(line) <= n else line[: n - 1] + "…"


def build_message(cmd, rc, out, secs, timed_out, budget, max_fails, max_line, max_chars):
    label = f"`{clip(cmd, 80)}`"
    if timed_out:
        return (f"Session start check {label} did not finish within {budget}s "
                "and was stopped. Its status is unknown.")
    if rc == 0:
        return f"Session start check {label} passed (exit 0, {secs:.1f}s)."
    lines = [strip_ansi(l) for l in out.splitlines()]
    fails = [l for l in lines if FAIL_LINE.search(l)]
    head = f"Session start check {label} exited {rc} after {secs:.1f}s."
    if fails:
        shown = fails[:max_fails]
        body = [head, f"Lines that look like failures ({len(shown)} of {len(fails)}), as printed:"]
        body += ["    " + clip(l, max_line) for l in shown]
        if len(fails) > len(shown):
            body.append(f"    ... {len(fails) - len(shown)} more not shown")
    else:
        tail = [l for l in lines if l.strip()][-5:]
        body = [head, "No line matched a known failure pattern. Last output lines:"]
        body += ["    " + clip(l, max_line) for l in tail] or ["    (no output)"]
    text = "\n".join(body)
    if len(text) > max_chars:
        text = text[: max_chars - 40].rstrip() + "\n    ... output truncated"
    return text


SETTINGS_SNIPPET = {
    "hooks": {
        "SessionStart": [{
            "matcher": "startup|resume",
            "hooks": [{
                "type": "command",
                "command": "python3 \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/red_start.py",
                "timeout": 60,
            }],
        }]
    }
}


def parse_args(argv):
    opts = {"cmd": "", "json": False, "dry": False, "snippet": False}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--cmd" and i + 1 < len(argv):
            opts["cmd"] = argv[i + 1]
            i += 1
        elif a == "--json":
            opts["json"] = True
        elif a == "--dry-run":
            opts["dry"] = True
        elif a == "--print-settings":
            opts["snippet"] = True
        i += 1
    return opts


def read_hook_input():
    """stdin이 비었거나 깨졌어도 {}로 간다."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        data = json.loads(sys.stdin.read() or "{}")
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def main(argv):
    opts = parse_args(argv)
    if opts["snippet"]:
        print(json.dumps(SETTINGS_SNIPPET, ensure_ascii=False, indent=2))
        return 0

    hook = {} if opts["dry"] else read_hook_input()
    project_dir = (os.environ.get("CLAUDE_PROJECT_DIR")
                   or (hook.get("cwd") if isinstance(hook.get("cwd"), str) else "")
                   or os.getcwd())
    cmd, origin, cfg = resolve(opts["cmd"], project_dir)

    budget = as_int(os.environ.get("RED_START_BUDGET", cfg.get("budget")), DEFAULT_BUDGET, 1, 3600)
    max_fails = as_int(cfg.get("max_fails"), DEFAULT_MAX_FAILS, 1, 200)
    max_line = as_int(cfg.get("max_line"), DEFAULT_MAX_LINE, 40, 2000)
    max_chars = as_int(cfg.get("max_chars"), DEFAULT_MAX_CHARS, 200, 9500)  # 1만 자 아래로 고정
    sources = cfg.get("sources") if isinstance(cfg.get("sources"), list) else list(DEFAULT_SOURCES)

    if opts["dry"]:
        print(f"프로젝트 폴더: {project_dir}")
        print(f"명령: {cmd or '(없음 — 훅은 아무것도 출력하지 않는다)'}  [출처: {origin}]")
        print(f"제한 시간: {budget}s · 실패 줄 최대 {max_fails} · 줄당 {max_line}자 · 전체 {max_chars}자")
        print(f"실행하는 시작 방식(source): {', '.join(map(str, sources))}")
        print("실제로는 실행하지 않았다(--dry-run).")
        return 0

    source = hook.get("source")
    if isinstance(source, str) and source not in sources:
        return 0
    if not cmd:
        return 0

    rc, out, secs, timed_out = run_with_deadline(cmd, project_dir, budget)
    text = build_message(cmd, rc, out, secs, timed_out, budget, max_fails, max_line, max_chars)
    if opts["json"]:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart", "additionalContext": text}}, ensure_ascii=False))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except BaseException:  # 훅은 무슨 일이 있어도 세션을 막지 않는다
        sys.exit(0)

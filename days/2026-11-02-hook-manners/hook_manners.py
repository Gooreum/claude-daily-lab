#!/usr/bin/env python3
"""hook-manners — 관찰용·Stop 훅이 Claude를 방해하지 않는지 실제로 돌려 점검한다.

settings.json의 command 훅을 깨진 입력·정상 입력·(Stop 계열은) stop_hook_active 참/거짓으로 실행해
종료 코드, stdout, 소요 시간, 루프 위험을 본다. 표준 라이브러리만 쓴다.
점검 대상 훅은 실제로 실행된다. 모르는 훅은 --no-run부터.
"""
import argparse, json, os, re, shlex, signal, subprocess, sys, time

GUARD_EVENTS = {"PreToolUse", "PermissionRequest"}      # 막는 것이 일이다 -> hook-exit-audit 영역
CONTEXT_EVENTS = {"SessionStart", "UserPromptSubmit"}   # stdout이 컨텍스트로 들어가는 게 정상일 수 있다
STOP_EVENTS = {"Stop", "SubagentStop"}
SEV = {"error": 0, "warn": 1, "info": 2}

SAMPLE = {
    "session_id": "probe-session", "transcript_path": "/nonexistent/probe.jsonl",
    "cwd": "", "hook_event_name": "",
}
BROKEN = [("빈 입력", ""), ("깨진 JSON", "not json{"), ("JSON null", "null"), ("배열", "[1,2,3]")]


def load_hooks(path):
    """settings 파일에서 (event, matcher, command, timeout) 목록."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for event, groups in (data.get("hooks") or {}).items():
        for g in groups if isinstance(groups, list) else []:
            for h in g.get("hooks", []) if isinstance(g, dict) else []:
                if isinstance(h, dict) and h.get("type", "command") == "command" and h.get("command"):
                    out.append({"event": event, "matcher": g.get("matcher", ""), "command": h["command"],
                                "timeout": h.get("timeout"), "source": path})
    return out


def run(cmd, stdin_text, cwd, timeout):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=cwd)
    t0 = time.monotonic()
    p = subprocess.Popen(["sh", "-c", cmd], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, cwd=cwd, env=env, start_new_session=True)
    try:
        out, err = p.communicate(stdin_text.encode(), timeout=timeout)
        return {"rc": p.returncode, "out": out.decode(errors="replace"), "err": err.decode(errors="replace"),
                "sec": time.monotonic() - t0, "timeout": False}
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        p.communicate()
        return {"rc": None, "out": "", "err": "", "sec": time.monotonic() - t0, "timeout": True}


def blocks(r):
    """이 실행이 Claude를 붙잡는가 (Stop 계열): exit 2 또는 stdout JSON의 decision == block."""
    if r["rc"] == 2:
        return True
    try:
        j = json.loads(r["out"])
        return isinstance(j, dict) and j.get("decision") == "block"
    except ValueError:
        return False


def _tokens(cmd):
    try:
        return shlex.split(cmd)
    except ValueError:
        return cmd.split()


def _expand(tok, h):
    return tok.replace("$CLAUDE_PROJECT_DIR", h.get("cwd") or os.getcwd()).replace("${CLAUDE_PROJECT_DIR}", h.get("cwd") or os.getcwd())


def script_text(cmd):
    """명령에 나온 로컬 파일들의 내용을 이어 붙인다(정적 점검용)."""
    text = []
    try:
        toks = shlex.split(cmd)
    except ValueError:
        toks = cmd.split()
    for t in toks:
        t = t.replace("$CLAUDE_PROJECT_DIR", os.environ.get("CLAUDE_PROJECT_DIR", "."))
        if os.path.isfile(t) and os.path.getsize(t) < 1_000_000:
            try:
                text.append(open(t, encoding="utf-8", errors="replace").read())
            except OSError:
                pass
    return "\n".join(text)


def check_hook(h, args):
    f = []   # (sev, code, msg)
    ev, cmd = h["event"], h["command"]
    t = h["timeout"]
    # --- 설정 점검 (실행 안 해도 됨)
    if t is None:
        f.append(("warn", "HM01", "설정에 timeout이 없다 — 기본 대기 시간에 기댄다. 짧게(예: 5) 적어 둘 것"))
    elif ev not in GUARD_EVENTS and isinstance(t, (int, float)) and t > args.max_timeout:
        f.append(("warn", "HM01", f"timeout {t}초 — {ev}는 서두르는 이벤트다(기준 {args.max_timeout}초). 기다리는 훅은 PermissionRequest뿐"))
    src = script_text(cmd)
    for tok in _tokens(cmd):
        if re.search(r"\.(py|sh|js|mjs|ts|rb)$", tok) and not os.path.isfile(_expand(tok, h)):
            why = "셸이 exit 127로 끝나 훅 오류가 된다" if tok == _tokens(cmd)[0] else "python3·node는 exit 2로 끝나 모든 호출을 막는다"
            f.append(("warn", "HM08", f"스크립트 파일이 없다: {tok} — {why}"))
    if ev in STOP_EVENTS and re.search(r"\bblock\b", src) and "stop_hook_active" not in src:
        f.append(("warn", "HM07", "스크립트가 block을 내면서 stop_hook_active를 읽지 않는다 — 루프 위험"))
    if args.no_run:
        return f, "건너뜀"
    cwd = h.get("cwd") or args.cwd
    tmo = args.timeout
    notes = []
    base = dict(SAMPLE, cwd=cwd, hook_event_name=ev)
    # --- 깨진 입력 (가드 훅은 일부러 막는 게 맞으니 제외)
    if ev not in GUARD_EVENTS:
        bad_rc, noisy, hung = [], [], []
        for label, text in BROKEN:
            r = run(cmd, text, cwd, tmo)
            if r["timeout"]:
                hung.append(label)
            elif r["rc"] != 0:
                bad_rc.append(f"{label}→exit {r['rc']}")
            elif r["out"].strip() and ev not in CONTEXT_EVENTS:
                noisy.append(label)
        if bad_rc:
            f.append(("error", "HM02", "깨진 입력에서 exit 0이 아니다: " + ", ".join(bad_rc)
                      + " — exit 2는 동작을 막고, 그 밖의 비-0은 훅 오류로 보인다"))
        if hung:
            f.append(("error", "HM05", f"깨진 입력에서 {tmo}초 안에 안 끝난다: " + ", ".join(hung) + " — 스크립트 안에 자체 데드라인이 없다"))
        if noisy:
            f.append(("warn", "HM03", "깨진 입력에서 stdout에 뭔가 찍는다: " + ", ".join(noisy) + " — stdout은 의도할 때만"))
        # --- 정상 입력
        r = run(cmd, json.dumps(base), cwd, tmo)
        if r["timeout"]:
            f.append(("error", "HM05", f"정상 입력에서 {tmo}초 안에 안 끝난다"))
        else:
            notes.append(f"{r['sec']:.2f}s")
            if r["sec"] > args.slow:
                f.append(("warn", "HM05", f"정상 입력 처리에 {r['sec']:.2f}초 (기준 {args.slow}초) — 이벤트마다 치르는 비용"))
            if r["rc"] not in (0, None) and not bad_rc:
                f.append(("warn", "HM02", f"정상 입력에서 exit {r['rc']}"))
            out = r["out"].strip()
            if out and ev not in CONTEXT_EVENTS:
                try:
                    json.loads(out)
                except ValueError:
                    f.append(("warn", "HM04", f"stdout이 JSON이 아닌 글자다({out[:30]!r}…) — 디버그 출력이 남았나"))
    # --- Stop 계열: 루프
    if ev in STOP_EVENTS:
        loops, inactive_block = [], False
        for label, extra in [("기본", {}), ("transcript 없음", {"transcript_path": ""}), ("메시지 있음", {"last_assistant_message": "done"})]:
            inp = dict(base, **extra)
            ra = run(cmd, json.dumps(dict(inp, stop_hook_active=True)), cwd, tmo)
            ri = run(cmd, json.dumps(dict(inp, stop_hook_active=False)), cwd, tmo)
            if ra["timeout"] or ri["timeout"]:
                f.append(("error", "HM05", f"{label}: {tmo}초 안에 안 끝난다"))
                continue
            if blocks(ra):
                loops.append(label)
            inactive_block = inactive_block or blocks(ri)
        if loops:
            f.append(("error", "HM06", "stop_hook_active=true인데 또 막는다(" + ", ".join(loops)
                      + ") — Claude가 끝낼 때마다 되돌려 보내지는 루프"))
        notes.append("비활성 때 막음" if inactive_block else "비활성 때도 안 막음")
    return f, " · ".join(notes) or "-"


def main(argv=None):
    ap = argparse.ArgumentParser(description="관찰용·Stop 훅이 Claude를 방해하지 않는지 점검한다.")
    ap.add_argument("settings", nargs="*", help="settings.json 경로 (없으면 .claude/settings*.json, ~/.claude/settings.json)")
    ap.add_argument("--hook", help="설정 파일 없이 명령 하나만")
    ap.add_argument("--event", default="Stop", help="--hook의 이벤트 이름 (기본 Stop)")
    ap.add_argument("--timeout", type=float, default=5, help="실행당 제한 시간 초 (기본 5)")
    ap.add_argument("--slow", type=float, default=1.5, help="느리다고 볼 기준 초 (기본 1.5)")
    ap.add_argument("--max-timeout", type=float, default=30, help="설정 timeout 상한(가드·PermissionRequest 제외, 기본 30)")
    ap.add_argument("--cwd", default=None, help="훅 실행 위치 (기본 현재 폴더 — 훅은 프로젝트 폴더에서 돈다)")
    ap.add_argument("--no-run", action="store_true", help="실행하지 않고 설정·정적 점검만")
    ap.add_argument("--fail-on", choices=["error", "warn"], default="error")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    hooks = []
    if args.hook:
        hooks.append({"event": args.event, "matcher": "", "command": args.hook, "timeout": None, "source": "--hook"})
    else:
        paths = args.settings or [p for p in (".claude/settings.json", ".claude/settings.local.json",
                                              os.path.expanduser("~/.claude/settings.json")) if os.path.isfile(p)]
        if not paths:
            print("점검할 settings.json이 없다", file=sys.stderr)
            return 2
        for p in paths:
            try:
                hooks += load_hooks(p)
            except (OSError, ValueError) as e:
                print(f"읽기 실패 {p}: {e}", file=sys.stderr)
                return 2
    if not hooks:
        print("command 훅이 없다 — 점검할 것이 없음")
        return 0

    args.cwd = os.path.abspath(args.cwd or os.getcwd())
    results = []
    for h in hooks:
        findings, note = check_hook(h, args)
        results.append((h, sorted(findings, key=lambda x: (SEV[x[0]], x[1])), note))

    n = {"error": 0, "warn": 0, "info": 0}
    for _, fs, _ in results:
        for s, _, _ in fs:
            n[s] += 1
    if args.json:
        print(json.dumps([{**h, "note": note, "findings": [{"severity": s, "code": c, "message": m} for s, c, m in fs]}
                          for h, fs, note in results], ensure_ascii=False, indent=2))
    else:
        for h, fs, note in results:
            tag = "가드(점검 제외)" if h["event"] in GUARD_EVENTS else "관찰"
            print(f"[{h['event']}{':' + h['matcher'] if h['matcher'] else ''}] {h['command'][:70]}  ({tag}; {note})")
            if not fs:
                print("  ok")
            for s, c, m in fs:
                print(f"  {s:<5} {c}: {m}")
        print(f"\n훅 {len(results)}개 · error {n['error']} · warn {n['warn']}")
    bad = n["error"] + (n["warn"] if args.fail_on == "warn" else 0)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

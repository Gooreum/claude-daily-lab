#!/usr/bin/env python3
"""hook-merge — 같은 도구 호출에 걸린 PreToolUse 훅 여럿의 결정이 어떻게 합쳐지는지 미리 본다.

배경: dev.to 11-20 "On Claude Code 2.1.319, one hook's defer erased another hook's ask…".
훅은 병렬로 돌고, 결정이 서로 다르면 문서 우선순위 deny > defer > ask > allow 로 합쳐진다.
  - exit 2 = deny(stderr가 사유). exit 0 + JSON hookSpecificOutput.permissionDecision = allow|deny|ask|defer.
  - defer는 `claude -p`에서 도구 호출이 하나일 때만 지켜진다. 대화형·병렬 호출에서는 경고만 남기고 무시된다.
  - 2.1.321 미만: defer가 먼저 끝나 "지킬 수 없으면" 다른 훅의 ask가 사라질 수 있었다.
이 도구는 설정 파일에서 호출에 걸리는 command 훅을 골라 병렬로 실행하고 결과를 합쳐 보여 준다.
표준 라이브러리만 쓴다. 모델·키·네트워크 불필요. 훅 명령을 실제로 실행하므로(`run`) 믿는 설정에만 쓴다. `plan`은 실행하지 않는다.
"""
import argparse, fnmatch, json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

ORDER = ["deny", "defer", "ask", "allow"]          # 문서 우선순위 (앞이 강함)
FIXED_IN = (2, 1, 321)                              # defer가 ask를 지우던 문제가 고쳐진 버전
EXACT_RE = re.compile(r"^[A-Za-z0-9_\- ,|]*$")


def parse_ver(s):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", s or "")
    return tuple(int(x) for x in m.groups()) if m else None


def matcher_hits(matcher, tool):
    """matcher가 도구 이름에 맞는가. (문서 규칙: 정확 일치 목록 또는 앵커 없는 정규식)"""
    if matcher in (None, "", "*"):
        return True
    if not isinstance(matcher, str):
        return False
    if EXACT_RE.match(matcher):
        return tool in [a.strip() for a in re.split(r"[|,]", matcher)]
    try:
        return re.search(re.sub(r"\(\?<([A-Za-z_]\w*)>", r"(?P<\1>", matcher), tool) is not None
    except re.error:
        return False


def if_hits(cond, tool, tin):
    """핸들러 `if`(권한 규칙 문법)가 이 호출에 맞는가. 근사 판정: True/False/None(판단 못 함)."""
    if not cond:
        return True
    m = re.match(r"^\s*([A-Za-z_][\w]*)(?:\((.*)\))?\s*$", cond)
    if not m:
        return None
    name, spec = m.group(1), m.group(2)
    if name != tool:
        return False
    if spec is None or spec == "*":
        return True
    if tool == "Bash":
        cmd = (tin or {}).get("command", "")
        if spec.endswith(":*"):                       # 옛 문법: 접두사 일치
            return cmd == spec[:-2] or cmd.startswith(spec[:-2] + " ")
        return fnmatch.fnmatchcase(cmd, spec)
    return None


def load_hooks(paths):
    """설정 JSON들에서 PreToolUse 그룹을 모은다. 플러그인 hooks.json의 {"hooks": {...}}도 같은 모양."""
    out = []
    for p in paths:
        try:
            data = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError) as e:
            out.append({"error": f"{p}: 읽을 수 없다({e})"})
            continue
        groups = ((data.get("hooks") or {}).get("PreToolUse")) or []
        for gi, g in enumerate(groups):
            for hi, h in enumerate(g.get("hooks") or []):
                out.append({"file": os.path.basename(p), "group": gi, "idx": hi,
                            "matcher": g.get("matcher"), "type": h.get("type", "command"),
                            "command": h.get("command") or h.get("url") or h.get("prompt"), "if": h.get("if"),
                            "timeout": h.get("timeout"), "onFailure": h.get("onFailure")})
    return out


def select(hooks, tool, tin):
    chosen, skipped = [], []
    for h in hooks:
        if "error" in h:
            continue
        if not matcher_hits(h["matcher"], tool):
            continue
        c = if_hits(h["if"], tool, tin)
        if c is False:
            skipped.append((h, "if 조건이 이 호출과 안 맞음"))
            continue
        h = dict(h, if_unknown=(c is None))
        if h["type"] != "command":
            skipped.append((h, f"type={h['type']} 훅은 실행하지 않는다(결정만 합쳐 보려면 command 훅이어야 한다)"))
            continue
        chosen.append(h)
    return chosen, skipped


def parse_decision(rc, out, err):
    """훅 종료 코드·stdout → (decision|None, reason, note)."""
    if rc == 2:
        return "deny", (err or "").strip().splitlines()[-1] if (err or "").strip() else "", "exit 2"
    if rc != 0:
        return None, "", f"exit {rc}: 막지 않는 오류(결정 없음, 호출은 계속된다)"
    s = (out or "").strip()
    if not s:
        return None, "", "무응답"
    try:
        j = json.loads(s)
    except ValueError:
        return None, "", "exit 0이지만 stdout이 JSON이 아니다(결정 없음)"
    if not isinstance(j, dict):
        return None, "", "JSON이 객체가 아니다(결정 없음)"
    hso = j.get("hookSpecificOutput") or {}
    d = hso.get("permissionDecision")
    if d in ORDER:
        return d, hso.get("permissionDecisionReason", ""), "permissionDecision"
    old = j.get("decision")                          # 옛 최상위 필드
    if old in ("approve", "block"):
        return ("allow" if old == "approve" else "deny"), j.get("reason", ""), f"옛 필드 decision={old}(deprecated)"
    return None, "", "결정 필드 없음"


def run_one(h, payload, project_dir, max_wait):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=project_dir)
    limit = min(h.get("timeout") or max_wait, max_wait)
    t0 = time.time()
    try:
        r = subprocess.run(h["command"], shell=True, input=payload, capture_output=True, text=True,
                           timeout=limit, env=env, cwd=project_dir)
        rc, out, err = r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        rc, out, err = -1, "", ""
        d = (None, "", f"{limit:g}초 안에 안 끝남(결정 없음)")
        return dict(h, rc=rc, dec=d[0], reason=d[1], note=d[2], t=time.time() - t0, end=time.time())
    d, reason, note = parse_decision(rc, out, err)
    return dict(h, rc=rc, dec=d, reason=reason, note=note, t=time.time() - t0, end=time.time())


def merge(results, mode, parallel_calls=False):
    """우선순위로 합친다. mode: interactive | print. defer는 대화형·병렬 호출에서 무시된다."""
    decs = [r["dec"] for r in results if r["dec"]]
    ignored_defer = False
    if "defer" in decs and (mode == "interactive" or parallel_calls):
        ignored_defer = True
        decs = [d for d in decs if d != "defer"]
    for d in ORDER:
        if d in decs:
            return d, ignored_defer
    return None, ignored_defer


def findings(results, version, parallel_calls):
    out = []
    decs = {}
    for r in results:
        if r["dec"]:
            decs.setdefault(r["dec"], []).append(r)
    if len(decs) >= 2:
        winner = next(d for d in ORDER if d in decs)
        out.append(("HM01", "warn", "훅들의 결정이 갈린다(" + ", ".join(f"{d}×{len(v)}" for d, v in decs.items()) +
                    f") — 우선순위 deny>defer>ask>allow 로 {winner} 하나로 합쳐진다. 진 결정은 결과에 반영되지 않는다"))
    if "defer" in decs and "ask" in decs:
        d, a = decs["defer"][0], decs["ask"][0]
        order = "defer가 먼저 끝남" if d["end"] < a["end"] else "ask가 먼저 끝남"
        if version is None:
            out.append(("HM02", "warn", f"defer+ask 쌍({order}). Claude Code 2.1.321 미만이면 defer가 먼저 끝날 때 ask가 사라져 "
                        "허용 규칙에 걸린 명령이 확인 없이 실행될 수 있다 — --claude-version 으로 버전을 알려 주면 판정한다"))
        elif version < FIXED_IN:
            out.append(("HM02", "error", f"defer+ask 쌍({order}) + Claude Code {'.'.join(map(str, version))} < 2.1.321: "
                        "defer가 먼저 끝나면 ask가 사라져 확인 창 없이 명령이 실행될 수 있다 — 올리거나 defer를 빼라"))
    if "defer" in decs:
        out.append(("HM03", "warn", "defer는 `claude -p`에서 도구 호출이 하나일 때만 지켜진다. 대화형 세션과 한 턴에 도구 호출이 여럿인 경우"
                    "에는 경고만 남기고 무시돼 보통 권한 흐름으로 간다" + (" (이번 실행은 병렬 호출로 가정)" if parallel_calls else "")))
    if len(decs.get("ask", [])) >= 2:
        out.append(("HM04", "warn", "ask가 둘 이상이다 — 확인 창에 어느 훅의 사유가 보일지는 훅이 끝나는 순서에 달릴 수 있다(2.1.321이 이 문제를 고쳤다). 사유를 한 훅으로 모으거나 한쪽을 줄인다"))
    for r in results:
        if r["dec"] is None and r["rc"] not in (0, 2):
            out.append(("HM05", "warn", f"{r['file']}: `{cmd_label(r['command'])}` 가 결정 없이 끝났다({r['note']}) — 가드라면 fail-open이다. exit 2 또는 onFailure:block 을 쓴다"))
        elif r["dec"] is None and r["rc"] == 0 and r["note"].startswith("exit 0이지만"):
            out.append(("HM06", "warn", f"{r['file']}: `{cmd_label(r['command'])}` 가 JSON이 아닌 stdout을 냈다 — 결정으로 읽히지 않는다"))
    return out


def short(s, n=48):
    s = re.sub(r"\s+", " ", s or "")
    return s if len(s) <= n else s[: n - 1] + "…"


def cmd_label(c, n=50):
    """긴 훅 명령을 줄인다: 따옴표와 $CLAUDE_PROJECT_DIR/ 를 걷고, 길면 꼬리(스크립트 이름 쪽)를 남긴다."""
    c = re.sub(r"\s+", " ", c or "").replace('"', "").replace("$CLAUDE_PROJECT_DIR/", "./")
    c = re.sub(r"^(bash|sh|python3?|node) ", "", c)
    return c if len(c) <= n else "…" + c[-(n - 1):]


def build_payload(args):
    tool = args.tool
    if args.input:
        raw = open(args.input[1:], encoding="utf-8").read() if args.input.startswith("@") else args.input
        tin = json.loads(raw)
    elif args.command is not None:
        tin = {"command": args.command}
    else:
        tin = {}
    payload = json.dumps({"session_id": "hook-merge", "cwd": os.path.abspath(args.project_dir), "hook_event_name": "PreToolUse",
                          "tool_name": tool, "tool_input": tin, "tool_use_id": "toolu_hookmerge"})
    return tool, tin, payload


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hook_merge", description=__doc__.split("\n")[0])
    ap.add_argument("mode", choices=["plan", "run"], help="plan: 걸리는 훅만 나열(실행 안 함) · run: 훅을 병렬 실행해 결정을 합친다")
    ap.add_argument("settings", nargs="+", help="settings.json / settings.local.json / 플러그인 hooks.json")
    ap.add_argument("--tool", default="Bash")
    ap.add_argument("--command", help="Bash 호출의 명령(tool_input.command)")
    ap.add_argument("--input", help="tool_input JSON 문자열 또는 @파일")
    ap.add_argument("--project-dir", default=os.getcwd(), help="CLAUDE_PROJECT_DIR 로 넘기고 훅의 작업 폴더로 쓴다")
    ap.add_argument("--claude-version", help="쓰는 Claude Code 버전(예: 2.1.319). HM02 판정에 쓴다")
    ap.add_argument("--parallel-calls", action="store_true", help="한 턴에 도구 호출이 여럿인 경우로 가정(defer 무시)")
    ap.add_argument("--max-wait", type=float, default=30, help="훅 하나를 기다릴 최대 초(기본 30)")
    ap.add_argument("--strict", action="store_true", help="warn도 exit 1")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    version = parse_ver(args.claude_version)
    tool, tin, payload = build_payload(args)
    hooks = load_hooks(args.settings)
    errs = [h["error"] for h in hooks if "error" in h]
    chosen, skipped = select(hooks, tool, tin)

    results = []
    if args.mode == "run" and chosen:
        with ThreadPoolExecutor(max_workers=len(chosen)) as ex:
            results = list(ex.map(lambda h: run_one(h, payload, args.project_dir, args.max_wait), chosen))
    fnd = findings(results, version, args.parallel_calls) if results else []
    mi, ig_i = merge(results, "interactive", args.parallel_calls)
    mp, ig_p = merge(results, "print", args.parallel_calls)

    if args.json:
        print(json.dumps({"tool": tool, "matched": [{k: h[k] for k in ("file", "matcher", "if", "command")} for h in chosen],
                          "results": [{"file": r["file"], "command": r["command"], "decision": r["dec"], "reason": r["reason"],
                                       "rc": r["rc"], "seconds": round(r["t"], 2), "note": r["note"]} for r in results],
                          "merged": {"interactive": mi, "print": mp}, "findings": [list(f) for f in fnd], "errors": errs},
                         ensure_ascii=False, indent=2))
    else:
        print(f"hook-merge {args.mode} — {tool}" + (f" `{short(tin.get('command'), 60)}`" if tin.get("command") else "")
              + f" · 설정 {len(args.settings)}개 · PreToolUse 훅 {len([h for h in hooks if 'error' not in h])}개 중 {len(chosen)}개가 걸린다")
        for e in errs:
            print(f"  ! {e}")
        order = sorted(results, key=lambda r: r["end"]) if results else []
        rank = {id(r): i + 1 for i, r in enumerate(order)}
        if results:
            print(f"  {'끝난 순':<6} {'결정':<6} {'초':>5}  훅")
            for r in results:
                dec = r["dec"] or "—"
                extra = f"  사유: {short(r['reason'], 60)}" if r["reason"] else ""
                print(f"  {rank[id(r)]:<6} {dec:<6} {r['t']:>5.2f}  {r['file']}[{r['matcher'] or '*'}] {cmd_label(r['command'])}{extra}"
                      + (f"  ({r['note']})" if not r["dec"] else ""))
        else:
            for h in chosen:
                tag = " (`if` 판단 못 함 — 맞을 수 있음)" if h["if_unknown"] else ""
                print(f"  걸림  {h['file']}[{h['matcher'] or '*'}] {cmd_label(h['command'])}{' if=' + h['if'] if h['if'] else ''}{tag}")
        for h, why in skipped:
            print(f"  제외  {h['file']}[{h['matcher'] or '*'}] {cmd_label(h['command'])} — {why}")
        if results:
            print(f"  합친 결과: 대화형 → {mi or '결정 없음(보통 권한 흐름)'}{' (defer 무시)' if ig_i else ''}"
                  f" · claude -p → {mp or '결정 없음(보통 권한 흐름)'}{' (defer 무시)' if ig_p else ''}")
        for fid, sev, msg in fnd:
            print(f"  {sev:<5} {fid}  {msg}")
        if args.mode == "run":
            print(f"  요약: error {sum(1 for f in fnd if f[1]=='error')} · warn {sum(1 for f in fnd if f[1]=='warn')}")
    bad = any(f[1] == "error" for f in fnd) or (args.strict and fnd) or bool(errs)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

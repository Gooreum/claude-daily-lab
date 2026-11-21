#!/usr/bin/env python3
"""settings-live — Claude Code 설정 파일이 "읽히는가", 안 읽히면 무엇이 꺼지는가.

Agent SDK 0.3.330은 설정 파일이 검증에 실패해 적용되지 않으면 `settings_not_in_effect`
경고를 보낸다. 파일 하나가 깨지면 그 안의 deny 규칙·훅이 통째로 사라지므로, 세션을
열기 전에 같은 종류의 고장을 미리 찾는다. 표준 라이브러리만 쓴다. 키·모델 불필요.

  python3 settings_live.py                 # ~/.claude/settings.json + ./.claude/settings*.json
  python3 settings_live.py FILE...         # 지정한 파일
  python3 settings_live.py --root DIR --home DIR
  python3 settings_live.py --string '{"permissions":{}}'   # SDK query()의 settings 문자열
  python3 settings_live.py --json | --strict

종료 코드: 0 문제 없음 · 1 error(또는 --strict에서 warn) · 2 사용법 오류
"""
import argparse
import difflib
import json
import os
import re
import sys

KNOWN_TOP = """$schema agent allowedHttpHookUrls allowedMcpServers alwaysThinkingEnabled apiKeyHelper
attribution autoMode autoUpdatesChannel awsAuthRefresh awsCredentialExport channelsEnabled
cleanupPeriodDays companyAnnouncements deniedMcpServers disableAllHooks disableBypassPermissionsMode
disabledMcpjsonServers effortLevel enableAllProjectMcpServers enabledMcpjsonServers enabledPlugins env
extraKnownMarketplaces fastMode feedbackSurveyRate forceLoginMethod forceLoginOrgUUID
forceRemoteSettingsRefresh hooks includeCoAuthoredBy includeGitInstructions language mcpServers model
modelOverrides otelHeadersHelper outputStyle permissions plansDirectory preferredNotifChannel
prefersReducedMotion respectGitignore sandbox showThinkingSummaries skipDangerousModePermissionPrompt
spinnerTipsEnabled spinnerVerbs statusLine strictKnownMarketplaces subagentPromptCacheTtl
subagentStatusLine terminalProgressBarEnabled theme useAutoModeDuringPlan verbose worktree""".split()
KNOWN_PERM = """allow deny ask defaultMode additionalDirectories disableBypassPermissionsMode
denyInsteadOfPrompting workingDirectoriesExclude""".split()
PERM_MODES = ["default", "acceptEdits", "plan", "auto", "bypassPermissions", "dontAsk"]
HOOK_EVENTS = """PreToolUse PostToolUse PostToolUseFailure PermissionRequest PermissionDenied Notification
UserPromptSubmit UserPromptExpansion SessionStart SessionEnd Stop StopFailure SubagentStart SubagentStop
PreCompact PostCompact Setup TeammateIdle TaskCreated TaskCompleted Elicitation ElicitationResult
ConfigChange InstructionsLoaded CwdChanged FileChanged WorktreeCreate WorktreeRemove""".split()
HANDLER_TYPES = ["command", "prompt", "agent", "http", "mcp_tool"]
INTERPRETERS = {"bash", "sh", "zsh", "python", "python3", "node", "deno", "bun", "ruby", "perl", "uv"}


class Dup(Exception):
    pass


def pairs_hook_factory(dups):
    def hook(pairs):
        seen = {}
        for k, v in pairs:
            if k in seen:
                dups.append((k, seen[k]))
            seen[k] = v
        return seen
    return hook


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def hint_for(text, err):
    """JSON 오류 위치 주변을 보고 흔한 원인을 짚는다."""
    pos = err.pos
    before = text[:pos].rstrip()
    ctx = text[max(0, pos - 40):pos + 20]
    if text[pos:pos + 2] in ("//", "/*") or re.search(r"(^|\s)//", text[max(0, pos - 80):pos + 2]):
        return "주석(// 또는 /* */)이 있다 — JSON은 주석을 허용하지 않는다"
    if before.endswith(",") and text[pos:pos + 1] in ("}", "]") or re.search(r",\s*[}\]]", ctx):
        return "마지막 항목 뒤에 쉼표(,)가 남았다"
    if "'" in ctx and '"' not in text[pos:pos + 1]:
        return "작은따옴표 문자열이 있다 — JSON은 큰따옴표만 쓴다"
    if err.msg.startswith("Expecting property name"):
        return "키가 따옴표 없이 쓰였거나 쉼표가 겹쳤다"
    if err.msg.startswith("Expecting ',' delimiter"):
        return "항목 사이에 쉼표(,)가 빠졌다"
    return ""


def lenient(text):
    """주석·후행 쉼표를 걷어 낸 사본으로 다시 파싱한다(문자열 안은 건드리지 않는다)."""
    out, i, n, in_s = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_s:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 1
            elif c == '"':
                in_s = False
        elif c == '"':
            in_s = True; out.append(c)
        elif c == "/" and text[i:i + 2] == "//":
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif c == "/" and text[i:i + 2] == "/*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        else:
            out.append(c)
        i += 1
    s = re.sub(r",(\s*[}\]])", r"\1", "".join(out))
    try:
        return json.loads(s)
    except ValueError:
        return None


def close(name, known, cutoff=0.8):
    m = difflib.get_close_matches(name, known, n=1, cutoff=cutoff)
    if m:
        return m[0]
    low = {k.lower(): k for k in known}
    return low.get(name.lower())


class Report:
    def __init__(self, label):
        self.label = label
        self.items = []  # (level, rule, where, msg)
        self.stake = None

    def add(self, level, rule, where, msg):
        self.items.append((level, rule, where, msg))


def check_rules(rep, where, rules, kind):
    if not isinstance(rules, list):
        rep.add("error", "SL03", where, f"{kind}는 문자열 배열이어야 한다(지금 {type(rules).__name__})")
        return
    for i, r in enumerate(rules):
        if not isinstance(r, str) or not r.strip():
            rep.add("error", "SL03", f"{where}[{i}]", f"규칙은 비어 있지 않은 문자열이어야 한다(지금 {r!r})")
        elif r.count("(") != r.count(")"):
            rep.add("warn", "SL10", f"{where}[{i}]", f"괄호가 짝이 안 맞는다: {r!r} — 규칙이 의도대로 매칭되지 않을 수 있다")


def script_path(cmd, root):
    toks = cmd.strip().split()
    if not toks:
        return None
    t = toks[0]
    if os.path.basename(t) in INTERPRETERS or t in INTERPRETERS:
        rest = [x for x in toks[1:] if not x.startswith("-")]
        if not rest:
            return None
        t = rest[0]
    t = t.replace("${CLAUDE_PROJECT_DIR}", root).replace("$CLAUDE_PROJECT_DIR", root)
    t = t.replace("${HOME}", os.path.expanduser("~")).replace("$HOME", os.path.expanduser("~"))
    t = t.replace('"', "").replace("'", "")
    if t.startswith("~/"):
        t = os.path.expanduser(t)
    if t.startswith("./"):
        t = os.path.join(root, t[2:])
    if not os.path.isabs(t) or "$" in t or "`" in t:
        return None
    return t


def check_hooks(rep, hooks, root):
    if not isinstance(hooks, dict):
        rep.add("error", "SL03", "hooks", f"hooks는 {{이벤트: [그룹…]}} 객체여야 한다(지금 {type(hooks).__name__})")
        return
    for ev, groups in hooks.items():
        w = f"hooks.{ev}"
        if ev not in HOOK_EVENTS:
            near = close(ev, HOOK_EVENTS, 0.7)
            if near:
                rep.add("warn", "SL05", w, f"\"{ev}\"는 훅 이벤트 이름이 아니다 — \"{near}\"? 이름은 대소문자를 구분하므로 이 훅은 한 번도 안 돈다")
            else:
                rep.add("info", "SL05", w, f"\"{ev}\"는 이 도구가 아는 훅 이벤트 목록에 없다(목록은 스냅샷이라 새 이벤트면 무시)")
        if not isinstance(groups, list):
            rep.add("error", "SL03", w, f"이벤트 값은 그룹 배열이어야 한다(지금 {type(groups).__name__})")
            continue
        for gi, g in enumerate(groups):
            gw = f"{w}[{gi}]"
            if not isinstance(g, dict):
                rep.add("error", "SL03", gw, "그룹은 객체여야 한다")
                continue
            hs = g.get("hooks")
            if not isinstance(hs, list):
                rep.add("error", "SL03", gw, "그룹에 \"hooks\" 배열이 없다 — 이 그룹의 훅은 전부 무시된다")
                continue
            for hi, h in enumerate(hs):
                hw = f"{gw}.hooks[{hi}]"
                if not isinstance(h, dict):
                    rep.add("error", "SL03", hw, "훅 핸들러는 객체여야 한다")
                    continue
                t = h.get("type")
                if t not in HANDLER_TYPES:
                    rep.add("warn", "SL03", hw, f"type {t!r}는 알려진 핸들러 종류({', '.join(HANDLER_TYPES)})가 아니다")
                    continue
                need = {"command": "command", "prompt": "prompt", "agent": "prompt", "http": "url"}.get(t)
                if need and not isinstance(h.get(need), str):
                    rep.add("error", "SL03", hw, f"type \"{t}\" 핸들러에는 문자열 \"{need}\"가 필요하다")
                if "timeout" in h and (isinstance(h["timeout"], bool) or not isinstance(h["timeout"], (int, float))):
                    rep.add("warn", "SL03", hw, f"timeout은 숫자여야 한다(지금 {h['timeout']!r})")
                if t == "command" and isinstance(h.get("command"), str):
                    p = script_path(h["command"], root)
                    if p and not os.path.exists(p):
                        rep.add("warn", "SL06", hw, f"스크립트 {p} 가 없다 — 훅이 exit 127로 끝나고, 127은 호출을 막지 못한다(막는 코드는 2)")


def stake_counts(cfg):
    perms = cfg.get("permissions") if isinstance(cfg.get("permissions"), dict) else {}
    def n(k):
        v = perms.get(k)
        return len(v) if isinstance(v, list) else 0
    hooks = cfg.get("hooks") if isinstance(cfg.get("hooks"), dict) else {}
    by_ev = {}
    for ev, groups in hooks.items():
        if isinstance(groups, list):
            c = sum(len(g.get("hooks", [])) for g in groups
                    if isinstance(g, dict) and isinstance(g.get("hooks"), list))
            if c:
                by_ev[ev] = c
    env = cfg.get("env") if isinstance(cfg.get("env"), dict) else {}
    return {"deny": n("deny"), "ask": n("ask"), "allow": n("allow"),
            "hooks": sum(by_ev.values()), "hooks_by_event": by_ev, "env": len(env),
            "sandbox": isinstance(cfg.get("sandbox"), dict) and bool(cfg["sandbox"].get("enabled"))}


def analyze_text(text, label, root, raw_bytes=None):
    rep = Report(label)
    if raw_bytes is not None and raw_bytes.startswith(b"\xef\xbb\xbf"):
        rep.add("warn", "SL07", "파일 앞", "UTF-8 BOM이 있다 — 엄격한 JSON 파서는 거부한다(편집기에서 BOM 없이 저장)")
    if not text.strip():
        rep.add("error", "SL01", "1행", "빈 파일이다 — JSON이 아니므로 설정으로 읽히지 않을 수 있다. 쓸 게 없으면 {} 를 넣는다")
        rep.stake = stake_counts({})
        return rep
    dups = []
    cfg = None
    try:
        cfg = json.loads(text, object_pairs_hook=pairs_hook_factory(dups))
    except json.JSONDecodeError as e:
        h = hint_for(text, e)
        rep.add("error", "SL01", f"{e.lineno}행 {e.colno}열", f"JSON 파싱 실패: {e.msg}" + (f" — {h}" if h else ""))
        alt = lenient(text)
        if isinstance(alt, dict):
            rep.stake = stake_counts(alt)
            rep.stake["recovered"] = True
        else:
            rep.stake = stake_counts({})
            rep.stake["unknown"] = True
        return rep
    for k, old in dups:
        lost = ""
        if k in ("permissions", "hooks", "env"):
            st = stake_counts({k: old})
            lost = f" 사라지는 쪽에 든 것: deny {st['deny']} · ask {st['ask']} · allow {st['allow']} · 훅 {st['hooks']} · env {st['env']}."
        rep.add("warn", "SL09", f"키 \"{k}\"", f"같은 키가 한 객체에 또 나온다 — 마지막 것만 남고 앞의 내용은 조용히 사라진다.{lost}")
    if not isinstance(cfg, dict):
        rep.add("error", "SL02", "최상위", f"최상위 값은 객체여야 한다(지금 {type(cfg).__name__})")
        rep.stake = stake_counts({})
        return rep
    for k in cfg:
        if k not in KNOWN_TOP:
            near = close(k, KNOWN_TOP)
            if near:
                rep.add("warn", "SL04", k, f"\"{k}\"는 설정 키가 아니다 — \"{near}\"? 오타면 이 값은 적용되지 않는다")
            else:
                rep.add("info", "SL04", k, f"\"{k}\"는 이 도구가 아는 키 목록에 없다(목록은 스냅샷이라 새 키면 무시)")
    perms = cfg.get("permissions")
    if perms is not None:
        if not isinstance(perms, dict):
            rep.add("error", "SL03", "permissions", f"permissions는 객체여야 한다(지금 {type(perms).__name__})")
        else:
            for k in perms:
                if k not in KNOWN_PERM:
                    near = close(k, KNOWN_PERM)
                    if near:
                        rep.add("warn", "SL04", f"permissions.{k}", f"\"{k}\"는 permissions 키가 아니다 — \"{near}\"? 오타면 규칙이 적용되지 않는다")
            for k in ("allow", "deny", "ask"):
                if k in perms:
                    check_rules(rep, f"permissions.{k}", perms[k], f"permissions.{k}")
            dm = perms.get("defaultMode")
            if dm is not None and dm not in PERM_MODES:
                rep.add("warn", "SL03", "permissions.defaultMode", f"{dm!r}는 알려진 모드({', '.join(PERM_MODES)})가 아니다")
    if "hooks" in cfg:
        check_hooks(rep, cfg["hooks"], root)
    env = cfg.get("env")
    if env is not None:
        if not isinstance(env, dict):
            rep.add("error", "SL03", "env", f"env는 {{이름: 문자열}} 객체여야 한다(지금 {type(env).__name__})")
        else:
            for k, v in env.items():
                if not isinstance(v, str):
                    rep.add("warn", "SL03", f"env.{k}", f"값은 문자열이어야 한다(지금 {v!r}) — 따옴표로 감싼다")
    ep = cfg.get("enabledPlugins")
    if ep is not None and not isinstance(ep, dict):
        rep.add("error", "SL03", "enabledPlugins", f"enabledPlugins는 {{플러그인: true|false}} 객체여야 한다(지금 {type(ep).__name__})")
    if "model" in cfg and not isinstance(cfg["model"], str):
        rep.add("error", "SL03", "model", f"model은 문자열이어야 한다(지금 {type(cfg['model']).__name__})")
    rep.stake = stake_counts(cfg)
    return rep


def analyze_file(path, root):
    try:
        raw = open(path, "rb").read()
    except OSError as e:
        r = Report(path); r.add("error", "SL01", "열기", f"읽을 수 없다: {e.strerror}"); r.stake = stake_counts({}); return r
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        r = Report(path); r.add("error", "SL01", "인코딩", "UTF-8이 아니다"); r.stake = stake_counts({}); return r
    return analyze_text(text, path, root, raw)


def discover(root, home):
    cands = [os.path.join(home, ".claude", "settings.json"),
             os.path.join(root, ".claude", "settings.json"),
             os.path.join(root, ".claude", "settings.local.json")]
    return [c for c in cands if os.path.exists(c)]


def stake_line(s):
    if s.get("unknown"):
        return "고칠 수 없는 모양이라 안에 뭐가 있었는지 셀 수 없다"
    parts = [f"deny {s['deny']}", f"ask {s['ask']}", f"allow {s['allow']}", f"훅 {s['hooks']}", f"env {s['env']}"]
    if s["hooks_by_event"]:
        parts.append("(" + ", ".join(f"{k} {v}" for k, v in s["hooks_by_event"].items()) + ")")
    if s["sandbox"]:
        parts.append("sandbox 켜짐")
    return " · ".join(parts)


def render(reps, strict, string_mode=False):
    lines = []
    errs = warns = infos = 0
    for r in reps:
        lines.append(f"== {r.label}")
        for lv, rule, where, msg in r.items:
            lines.append(f"  {lv:<5} {rule} {where} — {msg}")
            errs += lv == "error"; warns += lv == "warn"; infos += lv == "info"
        s = r.stake
        has_err = any(i[0] == "error" for i in r.items)
        if s:
            if has_err:
                tag = "고치면 살아날 것" if s.get("recovered") else "이 파일이 안 읽히면 꺼지는 것"
                lines.append(f"  stake {tag}: {stake_line(s)}")
                if (s["deny"] or s["hooks"]) and not s.get("unknown") and not string_mode:
                    lines.append(f"  stake → deny {s['deny']}개·훅 {s['hooks']}개가 적용되지 않은 채 세션이 시작된다(SDK는 settings_not_in_effect 경고만 보낸다)")
            else:
                lines.append(f"  stake 이 파일이 담당하는 것: {stake_line(s)}")
        if not r.items:
            lines.append("  ok    지적 없음")
    lines.append(f"파일 {len(reps)}개 · error {errs} · warn {warns} · info {infos}")
    bad = errs or (strict and warns)
    return "\n".join(lines), 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Claude Code 설정 파일이 읽히는지·안 읽히면 무엇이 꺼지는지 점검")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--root", default=os.getcwd())
    ap.add_argument("--home", default=os.path.expanduser("~"))
    ap.add_argument("--string", help="SDK query()의 settings에 넘길 JSON 문자열을 직접 점검")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="warn도 실패로 친다")
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root)
    if a.string is not None:
        reps = [analyze_text(a.string, "--string", root)]
        for r in reps:
            r.items = [(lv, ru, w, m + (" (SDK 0.3.330부터 query()가 오류로 끝난다)" if ru == "SL01" else "")) for lv, ru, w, m in r.items]
    else:
        files = a.files or discover(root, os.path.abspath(a.home))
        if not files:
            print("점검할 설정 파일이 없다(~/.claude/settings.json, .claude/settings.json, .claude/settings.local.json). 경로를 직접 주거나 --root를 쓴다")
            return 0
        reps = [analyze_file(f, root) for f in files]
    if a.json:
        print(json.dumps([{"file": r.label, "findings": [dict(level=l, rule=ru, where=w, msg=m) for l, ru, w, m in r.items],
                           "stake": r.stake} for r in reps], ensure_ascii=False, indent=2))
        bad = any(l == "error" or (a.strict and l == "warn") for r in reps for l, *_ in r.items)
        return 1 if bad else 0
    out, rc = render(reps, a.strict, a.string is not None)
    print(out)
    return rc


if __name__ == "__main__":
    sys.exit(main())

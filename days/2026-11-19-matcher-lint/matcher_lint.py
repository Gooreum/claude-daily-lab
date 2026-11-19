#!/usr/bin/env python3
"""matcher-lint — 훅 설정의 `matcher`가 "절대 안 맞는" 경우를 문서 규칙대로 찾는다.

Claude Code v2.1.327의 `/status`가 알려 주는 "never match 훅 matcher"를 저장소·CI에서 미리 잡는다.
settings.json / settings.local.json / 플러그인 hooks.json을 읽기만 한다(훅은 실행하지 않는다).
표준 라이브러리만 쓴다. 모델·키·네트워크 불필요.

matcher 평가 규칙(https://code.claude.com/docs/en/hooks, "Matcher patterns")
  - "*" · "" · 생략             -> 모든 발생에 맞음
  - 글자·숫자·_·-·공백·,·| 만     -> 정확한 문자열(또는 |·, 로 나눈 목록). 대소문자 구분
  - 그 밖의 문자가 하나라도 있으면 -> JavaScript 정규식, 앵커 없음(어디서든 맞으면 통과)
  - FileChanged·StopFailure는 정확 일치 문자 집합이 더 좁다(글자·숫자·_·| 만)
  - matcher를 지원하지 않는 이벤트에 쓰면 조용히 무시된다
"""
import argparse, json, os, re, sys

# 도구 이름 (https://code.claude.com/docs/en/tools-reference, 2026-11-19 확인)
TOOLS = {
    "Agent", "Artifact", "AskUserQuestion", "Bash", "CronCreate", "CronDelete", "CronList", "Edit",
    "EndConversation", "EnterPlanMode", "EnterWorktree", "ExitPlanMode", "ExitWorktree", "Glob", "Grep",
    "ListAgents", "ListMcpResourcesTool", "LSP", "Monitor", "NotebookEdit", "PowerShell", "PushNotification",
    "Read", "ReadMcpResourceTool", "RemoteTrigger", "ReportFindings", "ScheduleWakeup", "SendFeedback",
    "SendMessage", "SendUserFile", "ShareOnboardingGuide", "Skill", "SubagentHandback", "TaskCreate",
    "TaskGet", "TaskList", "TaskOutput", "TaskStop", "TaskUpdate", "TodoWrite", "ToolSearch",
    "WaitForMcpServers", "WebFetch", "WebSearch", "Workflow", "Write",
}
# 옛 버전에 있던 이름. 지금 도구 목록에는 없어 새 버전에서는 안 맞지만, 옛 버전 설정일 수 있어 warn만 한다.
LEGACY = {"Task": "Agent", "MultiEdit": "Edit"}
TOOL_EVENTS = {"PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest", "PermissionDenied"}
NO_MATCHER_EVENTS = {"UserPromptSubmit", "PostToolBatch", "Stop", "TeammateIdle", "TaskCreated",
                     "TaskCompleted", "WorktreeCreate", "WorktreeRemove", "MessageDisplay", "CwdChanged"}
# 값 목록이 닫혀 있는 이벤트. 새 버전이 값을 늘릴 수 있어 어긋나면 error가 아니라 warn으로 둔다.
ENUMS = {
    "SessionStart": {"startup", "resume", "clear", "compact", "fork"},
    "Setup": {"init", "maintenance"},
    "SessionEnd": {"clear", "resume", "logout", "prompt_input_exit", "other"},
    "Notification": {"permission_prompt", "idle_prompt", "auth_success", "auth_storage_failure",
                     "elicitation_dialog", "elicitation_url_dialog", "elicitation_complete",
                     "elicitation_response", "agent_needs_input", "agent_completed",
                     "quota_auto_resume_fired", "quota_auto_resume_stale", "quota_auto_resume_disabled",
                     "plugin_notification"},
    "PreCompact": {"manual", "auto"}, "PostCompact": {"manual", "auto"},
    "ConfigChange": {"user_settings", "project_settings", "local_settings", "policy_settings", "skills"},
    "DirectoryAdded": {"slash_command", "register_repo_root"},
    "StopFailure": {"rate_limit", "authentication_failed", "oauth_org_not_allowed", "account_on_hold",
                    "billing_error", "invalid_request", "model_not_found", "server_error",
                    "max_output_tokens", "cloud_credential_error", "unknown"},
    "InstructionsLoaded": {"session_start", "nested_traversal", "path_glob_match", "include", "compact"},
}
# 값 목록이 열려 있어 이름을 검증할 수 없는 이벤트(정규식 문법만 본다)
OPEN_EVENTS = {"SubagentStart", "SubagentStop", "UserPromptExpansion", "Elicitation", "ElicitationResult",
               "FileChanged", "PreModelSwitch", "PostModelSwitch"}
NARROW_EVENTS = {"FileChanged", "StopFailure"}
EXACT_RE = re.compile(r"^[A-Za-z0-9_\- ,|]*$")
NARROW_RE = re.compile(r"^[A-Za-z0-9_|]*$")
SEV = {"error": 0, "warn": 1}
BASH_FAMILY = {"Bash", "Monitor"}  # Bash 규칙·matcher는 Monitor 명령에도 걸린다 (tools-reference, hooks 문서)


def js_to_py(rx):
    """JS 정규식에서 파이썬 re로 옮길 때 다른 점만 보정한다 (이름 붙은 그룹)."""
    return re.sub(r"\(\?<([A-Za-z_]\w*)>", r"(?P<\1>", rx)


def alternatives(m):
    return [a.strip() for a in re.split(r"[|,]", m)]


def near_tool(name):
    low = name.lower()
    for t in sorted(TOOLS):
        if t.lower() == low:
            return t
    return None


class Finding(dict):
    pass


def lint_group(event, matcher, handlers, extra_tools):
    """한 matcher 그룹의 지적 목록. [(id, severity, message)]"""
    out = []
    tools = TOOLS | set(extra_tools)
    if matcher is None or matcher == "" or matcher == "*":
        pass_matcher = True
    else:
        pass_matcher = False
    if matcher is not None and not isinstance(matcher, str):
        return [("ML00", "error", f"matcher는 문자열이어야 한다(지금 {type(matcher).__name__}). 이 그룹은 무시되거나 설정 오류가 된다")]

    if pass_matcher:
        matched = None  # 전부
    elif event in NO_MATCHER_EVENTS:
        out.append(("ML03", "warn", f"{event}는 matcher를 지원하지 않아 \"{matcher}\"는 조용히 무시된다 — 매번 실행된다. matcher를 지우거나 훅 안에서 거른다"))
        matched = None
    else:
        exact_re = NARROW_RE if event in NARROW_EVENTS else EXACT_RE
        matched = None
        if exact_re.match(matcher):
            alts = alternatives(matcher)
            if event in TOOL_EVENTS:
                ok = set()
                for a in alts:
                    if a in tools:
                        ok.add(a)
                    elif a.startswith("mcp__"):
                        parts = a.split("__")
                        if len(parts) >= 3 and all(parts[1:3]):
                            ok.add(a)  # mcp__서버__도구 정확한 이름
                        else:
                            out.append(("ML01", "error", f"\"{a}\"는 정확 일치로만 비교돼 어떤 MCP 도구와도 안 맞는다 — 서버의 모든 도구는 \"{a}__.*\"로 쓴다"))
                    elif a == "":
                        continue
                    elif a in LEGACY:
                        out.append(("ML01", "warn", f"\"{a}\"는 지금 도구 목록에 없다 — 현재 이름은 \"{LEGACY[a]}\"다(옛 버전용이면 무시)"))
                        ok.add(a)
                    else:
                        hint = near_tool(a)
                        out.append(("ML01", "error", f"\"{a}\"는 도구 이름과 정확히 일치하지 않는다" + (f" — 대소문자를 구분한다. \"{hint}\"를 뜻했다면 그렇게 쓴다" if hint else " — 오타이거나 없는 도구다")))
                matched = ok
            elif event in ENUMS:
                bad = [a for a in alts if a and a not in ENUMS[event]]
                for a in bad:
                    near = [v for v in sorted(ENUMS[event]) if v.lower() == a.lower()]
                    out.append(("ML05", "warn", f"{event}의 matcher 값 목록에 \"{a}\"가 없다" + (f" — 대소문자를 구분한다. \"{near[0]}\"?" if near else f" (문서 값: {', '.join(sorted(ENUMS[event]))}) — 새 버전이 값을 늘렸다면 무시")))
        else:
            # 정규식 경로
            try:
                rx = re.compile(js_to_py(matcher))
            except re.error as e:
                out.append(("ML02", "error", f"정규식으로 해석되지 않는다({e}) — 글로브(`*.ts`, `Edit*`)가 아니라 정규식을 쓴다: `.*`, `^Edit$`"))
                rx = None
            if rx is not None and event in TOOL_EVENTS:
                m = re.match(r"^\s*([A-Za-z_][\w]*)\((.*)\)\s*$", matcher)
                hits = {t: rx.search(t) for t in tools}
                hits = {t: h for t, h in hits.items() if h}
                if m and (m.group(1) in tools):
                    out.append(("ML04", "error", f"matcher는 도구 이름만 거른다. 인자 조건은 핸들러의 if에 쓴다 — matcher \"{m.group(1)}\", if \"{matcher}\""))
                elif not hits and "mcp__" not in matcher:
                    out.append(("ML02", "error", "이 정규식은 알려진 어떤 도구 이름에도 맞지 않는다 — 아무것도 안 맞는다 (MCP 도구 전용이면 `mcp__서버__.*` 꼴로)"))
                elif hits and not matcher.lstrip("(").startswith("^"):
                    extra = sorted(t for t, h in hits.items() if h.start() > 0)
                    if extra:
                        out.append(("ML06", "warn", f"앵커가 없어 {', '.join(extra)}도 맞는다 — 한 도구만 뜻했다면 ^…$ 로 감싼다"))
                matched = set(hits) if hits else (None if "mcp__" in matcher else set())
            elif rx is not None and event in ENUMS:
                vals = ENUMS[event]
                if not any(rx.search(v) for v in vals):
                    out.append(("ML05", "warn", f"이 정규식은 {event}의 문서 값({', '.join(sorted(vals))}) 어디에도 맞지 않는다"))

    # if 필드와 matcher가 겹치는가 (도구 이벤트만)
    if event in TOOL_EVENTS:
        for h in handlers:
            cond = h.get("if") if isinstance(h, dict) else None
            if not isinstance(cond, str):
                continue
            m = re.match(r"^\s*([A-Za-z_][\w]*)", cond)
            if not m:
                continue
            tname = m.group(1)
            if tname.startswith("mcp__") or matched is None:
                continue
            fam = BASH_FAMILY if tname in BASH_FAMILY else {tname}
            mfam = set(matched)
            if mfam & BASH_FAMILY:
                mfam |= BASH_FAMILY
            if tname in tools and not (fam & mfam):
                out.append(("ML07", "error", f"if \"{cond}\"는 {tname} 호출에만 맞는데 matcher \"{matcher}\"는 {tname} 호출을 통과시키지 않는다 — 이 훅은 한 번도 실행되지 않는다"))
            elif tname not in tools:
                near = near_tool(tname)
                out.append(("ML07", "error", f"if \"{cond}\"의 도구 이름 \"{tname}\"이 목록에 없다" + (f" — \"{near}\"?" if near else "")))
    return out


def collect(path):
    """설정 파일 하나에서 [(event, matcher_or_None, handlers, location)]."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    hooks = data.get("hooks") if isinstance(data, dict) else None
    groups = []
    if not isinstance(hooks, dict):
        return groups
    for event, glist in hooks.items():
        if not isinstance(glist, list):
            continue
        for i, g in enumerate(glist):
            if not isinstance(g, dict):
                continue
            hs = g.get("hooks") if isinstance(g.get("hooks"), list) else []
            groups.append((event, g.get("matcher") if "matcher" in g else None, hs, f"{event}[{i}]"))
    return groups


def find_files(paths, user):
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, names in os.walk(p):
                dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "__pycache__", "fixtures"}]
                for n in names:
                    full = os.path.join(root, n)
                    if n in ("settings.json", "settings.local.json") and os.path.basename(root) == ".claude":
                        files.append(full)
                    elif n == "hooks.json" and os.path.basename(root) == "hooks":
                        files.append(full)
        else:
            files.append(p)
    if user:
        for n in ("settings.json", "settings.local.json"):
            f = os.path.join(os.path.expanduser("~"), ".claude", n)
            if os.path.exists(f):
                files.append(f)
    return files


def main():
    ap = argparse.ArgumentParser(description="훅 matcher가 절대 안 맞는 경우를 찾는다")
    ap.add_argument("paths", nargs="*", help="설정 파일 또는 폴더(.claude/settings*.json, hooks/hooks.json을 찾는다)")
    ap.add_argument("--user", action="store_true", help="~/.claude/settings*.json도 본다")
    ap.add_argument("--extra-tool", action="append", default=[], help="도구 이름 목록에 더할 이름(반복 가능)")
    ap.add_argument("--strict", action="store_true", help="warn도 실패(exit 1)로 센다")
    ap.add_argument("--json", action="store_true", help="결과를 JSON으로 출력")
    a = ap.parse_args()
    files = find_files(a.paths or ["."], a.user)
    if not files:
        print("점검할 훅 설정 파일이 없다", file=sys.stderr)
        return 0
    results, groups_n, bad_files = [], 0, 0
    for f in files:
        try:
            groups = collect(f)
        except (OSError, ValueError) as e:
            bad_files += 1
            results.append({"file": f, "where": "-", "id": "ML90", "severity": "error", "message": f"읽거나 JSON으로 해석하지 못했다: {e}"})
            continue
        for event, matcher, hs, where in groups:
            groups_n += 1
            for fid, sev, msg in lint_group(event, matcher, hs, a.extra_tool):
                results.append({"file": f, "where": f"{where} matcher={matcher!r}", "id": fid, "severity": sev, "message": msg})
    results.sort(key=lambda r: (SEV[r["severity"]], r["file"], r["where"]))
    errs = sum(r["severity"] == "error" for r in results)
    warns = sum(r["severity"] == "warn" for r in results)
    if a.json:
        print(json.dumps({"files": len(files), "groups": groups_n, "errors": errs, "warnings": warns, "findings": results}, ensure_ascii=False, indent=2))
    else:
        for r in results:
            print(f"{r['severity']:5} {r['id']}: {r['file']} {r['where']}\n      {r['message']}")
        print(f"파일 {len(files)}개 · matcher 그룹 {groups_n}개 · error {errs} · warn {warns}")
    return 1 if errs or (a.strict and warns) else 0


if __name__ == "__main__":
    sys.exit(main())

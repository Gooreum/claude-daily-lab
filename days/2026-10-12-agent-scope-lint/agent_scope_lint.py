#!/usr/bin/env python3
"""agent-scope-lint: Claude Code 서브에이전트 정의와 권한 규칙의 "생각과 다르게 동작하는" 설정을 잡는다.

검사 (dev.to 10-12 실측 글 기준):
  AS001 error  disallowedTools에 괄호 지정자(Bash(git push *)) → 그 도구 전체가 사라진다
  AS002 warn   셸을 막은 서브에이전트가 Agent 도구는 갖고 있다 → 손자 에이전트가 제한 없이 Bash를 쓴다
  AS003 warn   permissions.deny의 `Bash(git <sub> …)` → `git -C <경로> <sub>`·`git -c k=v <sub>`로 우회된다
  AS004 warn   tools 허용 목록에 괄호 지정자 → 허용 목록은 도구 이름 단위라 지정자가 뜻대로 안 먹을 수 있다

표준 라이브러리만 쓴다. exit 0 = 문제 없음(또는 경고만), 1 = error 있음(--strict면 warn도), 2 = 사용법/파일 오류.
"""
import argparse
import json
import os
import re
import sys

SHELL_TOOLS = {"Bash", "PowerShell"}
AGENT_TOOLS = {"Agent", "Task"}  # Task는 Agent의 예전 이름
SPEC_RE = re.compile(r"^\s*([A-Za-z_][\w-]*)\s*\((.*)\)\s*$", re.S)
# git 전역 옵션: 하위 명령 앞에 끼어 deny 규칙의 문자열 매칭을 피해 간다
GIT_GLOBAL_BYPASS = ["git -C <경로> {sub}", "git -c <키>=<값> {sub}", "git --git-dir=<경로> {sub}"]


def split_top(s):
    """괄호 바깥의 쉼표로만 나눈다. 'Read, Bash(a, b)' → ['Read', 'Bash(a, b)']"""
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [x.strip().strip("'\"") for x in out if x.strip().strip("'\"")]


def parse_frontmatter(text):
    """서브에이전트 .md의 YAML 프론트매터에서 필요한 키만 읽는 작은 파서.
    지원: `key: a, b` / `key: [a, b]` / 블록 리스트(`- a`). 반환: {key: (값, 줄번호)}"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fm, key = {}, None
    for i, raw in enumerate(lines[1:], start=2):
        if raw.strip() == "---":
            return fm
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", raw)
        if m and not raw.startswith((" ", "\t")):
            key, val = m.group(1), m.group(2).strip()
            if val.startswith("[") and val.endswith("]"):
                val = val[1:-1]
            fm[key] = (split_top(val) if val else [], i, val)
            continue
        item = re.match(r"^\s+-\s+(.*)$", raw)
        if item and key:
            vals, line, scalar = fm[key]
            vals.append(item.group(1).strip().strip("'\""))
            fm[key] = (vals, line, scalar)
    return None  # 닫는 --- 없음


def finding(code, level, path, line, msg, fix):
    return {"code": code, "level": level, "file": path, "line": line, "message": msg, "fix": fix}


def lint_agent(path, text, explicit=True):
    fm = parse_frontmatter(text)
    if fm is None:
        if not explicit:  # 폴더를 훑다 만난 프론트매터 없는 .md는 에이전트가 아닌 문서로 본다
            return []
        return [finding("AS000", "warn", path, 1, "프론트매터(--- … ---)를 찾지 못했다", "파일 맨 위에 프론트매터를 둔다")]
    out = []
    tools = fm.get("tools")
    dis = fm.get("disallowedTools")
    dis_names = set()

    if dis:
        for entry in dis[0]:
            m = SPEC_RE.match(entry)
            if m:
                name = m.group(1)
                dis_names.add(name)
                out.append(finding(
                    "AS001", "error", path, dis[1],
                    f"disallowedTools의 `{entry}`는 `{name}(…)`만이 아니라 {name} 도구 전체를 없앤다",
                    f"셸이 필요 없으면 `disallowedTools: {name}`로 의도를 드러내고, "
                    f"셸은 두고 일부 명령만 막으려면 settings의 permissions.deny + PreToolUse 훅을 쓴다"))
            else:
                dis_names.add(entry)

    if tools and tools[0]:
        for entry in tools[0]:
            if SPEC_RE.match(entry):
                out.append(finding(
                    "AS004", "warn", path, tools[1],
                    f"tools 허용 목록의 `{entry}`: 서브에이전트 도구 목록은 이름 단위다. 지정자 동작은 실측되지 않았다",
                    "도구 이름만 적고, 명령 단위 제한은 permissions 규칙이나 훅으로 옮긴다"))
        allowed = {SPEC_RE.match(e).group(1) if SPEC_RE.match(e) else e for e in tools[0]}
        has_shell = bool(allowed & SHELL_TOOLS) and not (dis_names & SHELL_TOOLS)
        has_agent = bool(allowed & AGENT_TOOLS) and not (dis_names & AGENT_TOOLS)
        anchor = tools[1]
    else:  # tools 생략 = 부모의 도구를 전부 물려받는다
        has_shell = not (dis_names & SHELL_TOOLS)
        has_agent = not (dis_names & AGENT_TOOLS)
        anchor = dis[1] if dis else 1

    if not has_shell and has_agent:
        out.append(finding(
            "AS002", "warn", path, anchor,
            "셸이 막힌 서브에이전트가 Agent 도구를 갖고 있다. 이 에이전트가 띄우는 서브에이전트는 제한을 물려받지 않아 Bash를 쓴다",
            "disallowedTools에 Agent를 추가하거나, tools 허용 목록에서 Agent/Task를 뺀다"))
    return out


def lint_settings(path, text):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return [finding("AS000", "warn", path, e.lineno, f"JSON 파싱 실패: {e.msg}", "JSON 문법을 고친다")]
    deny = (data.get("permissions") or {}).get("deny") or []
    out = []
    lines = text.splitlines()
    for rule in deny:
        if not isinstance(rule, str):
            continue
        m = SPEC_RE.match(rule)
        if not m or m.group(1) not in SHELL_TOOLS:
            continue
        cmd = m.group(2).strip()
        g = re.match(r"^git\s+([a-z][\w-]*)", cmd)
        if not g:
            continue
        sub = g.group(1)
        line = next((i for i, ln in enumerate(lines, 1) if rule in ln), 1)
        forms = ", ".join("`" + f.format(sub=sub) + "`" for f in GIT_GLOBAL_BYPASS)
        out.append(finding(
            "AS003", "warn", path, line,
            f"deny `{rule}`는 명령 문자열만 비교한다. {forms}는 걸리지 않는다",
            f"git 전역 옵션을 걷어낸 뒤 하위 명령 `{sub}`를 보는 PreToolUse 훅을 짝으로 두고, "
            f"꼭 막아야 하면 원격(보호 브랜치·pre-receive)에서 막는다"))
    return out


def collect(targets):
    files = []  # (경로, 직접 지정 여부)
    for t in targets:
        if os.path.isdir(t):
            agents = os.path.join(t, ".claude", "agents")
            base = agents if os.path.isdir(agents) else t
            for root, _, names in os.walk(base):
                files += [(os.path.join(root, n), False) for n in sorted(names) if n.endswith(".md")]
            for n in ("settings.json", "settings.local.json"):
                p = os.path.join(t, ".claude", n)
                if os.path.isfile(p):
                    files.append((p, True))
        elif os.path.isfile(t):
            files.append((t, True))
        else:
            raise FileNotFoundError(t)
    return files


def lint_file(path, explicit=True):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if path.endswith(".json"):
        return lint_settings(path, text)
    return lint_agent(path, text, explicit)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Claude Code 서브에이전트·권한 규칙 함정 린터")
    ap.add_argument("targets", nargs="*", default=["."],
                    help="프로젝트 폴더(.claude/agents·settings*.json을 찾음), 에이전트 .md, settings .json")
    ap.add_argument("--json", action="store_true", help="JSON으로 출력")
    ap.add_argument("--strict", action="store_true", help="warn도 실패(exit 1)로 친다")
    a = ap.parse_args(argv)

    try:
        files = collect(a.targets)
    except FileNotFoundError as e:
        print(f"agent-scope-lint: 경로 없음: {e}", file=sys.stderr)
        return 2
    results = []
    for p, explicit in files:
        results += lint_file(p, explicit)

    errors = sum(r["level"] == "error" for r in results)
    warns = sum(r["level"] == "warn" for r in results)
    if a.json:
        print(json.dumps({"files": len(files), "errors": errors, "warnings": warns, "findings": results},
                         ensure_ascii=False, indent=2))
    else:
        for r in results:
            print(f"{r['file']}:{r['line']}: {r['level']} {r['code']} {r['message']}")
            print(f"    → {r['fix']}")
        print(f"파일 {len(files)}개 · error {errors} · warn {warns}")
    return 1 if errors or (a.strict and warns) else 0


if __name__ == "__main__":
    sys.exit(main())

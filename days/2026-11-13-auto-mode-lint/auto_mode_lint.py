#!/usr/bin/env python3
"""auto-mode-lint: Claude Code settings.json 의 autoMode 블록을 점검한다.

근거: https://code.claude.com/docs/en/auto-mode-config (2026-11-13 확인)
  - environment/allow/soft_deny/hard_deny 는 산문 규칙 배열이다.
  - 배열에 "$defaults" 가 없으면 그 섹션의 내장 규칙 전체를 대체한다.
  - 분류기는 프로젝트의 .claude/settings.json, settings.local.json 의 autoMode 를 읽지 않는다.

모델·키·네트워크 없이 돈다. 표준 라이브러리만 쓴다.
종료 코드: 0 문제 없음(또는 경고만) / 1 오류 있음(--strict면 경고도) / 2 사용법·읽기 실패
"""
import argparse
import json
import os
import re
import sys

SECTIONS = ("environment", "allow", "soft_deny", "hard_deny")
KNOWN_KEYS = set(SECTIONS) | {"classifyAllShell"}
LOSS = {
    "soft_deny": ("error", "내장 차단 규칙 전부(force push, curl | bash, 운영 배포, auto mode 우회)가 사라진다"),
    "hard_deny": ("error", "내장 데이터 유출 차단 규칙이 사라진다"),
    "allow": ("warn", "내장 예외 규칙이 사라져 허용 프롬프트가 늘어난다"),
    "environment": ("info", "내장 환경 항목이 사라진다(/auto-mode-setup 초안은 일부러 이렇게 쓰므로 정보로만 표시)"),
}
PLACEHOLDER = re.compile(
    r"(_HERE\b|\bYOUR[_-][A-Z]|<[^>\n]{1,40}>|\bTODO\b|\bFIXME\b|\bCHANGE_?ME\b|\bXXX+\b"
    r"|\bexample\.(?:com|org)\b|\bacme-corp\b|\bplaceholder\b|\bREPLACE[_ -]?ME\b)",
    re.I,
)
# 대소문자 구분: 자리표시자 대문자 토큰(GITHUB_ACCOUNT_HERE)을 잡기 위한 보조 패턴
UPPER_HERE = re.compile(r"\b[A-Z][A-Z0-9_]*_HERE\b")
NEAR_DEFAULTS = re.compile(r"^\$?\s*defaults?$", re.I)
PATTERNY = re.compile(r"^(?:Bash|Read|Edit|Write|WebFetch|mcp__\w+)\(.*\)$|^[A-Za-z_]+\(.*\*.*\)$")


def finding(sev, code, where, msg):
    return {"severity": sev, "code": code, "where": where, "message": msg}


def lint_block(block, label, scope):
    """autoMode 객체 하나를 검사한다. scope: 'user' | 'managed' | 'project' | 'unknown'."""
    out = []
    if scope == "project":
        out.append(finding("error", "AM003", f"{label}:autoMode",
                           "프로젝트 설정의 autoMode 는 분류기가 읽지 않는다(체크인된 저장소가 규칙을 주입하지 못하게). ~/.claude/settings.json 으로 옮긴다"))
    if not isinstance(block, dict):
        out.append(finding("error", "AM004", f"{label}:autoMode", f"autoMode 는 객체여야 한다(지금: {type(block).__name__})"))
        return out
    for key in block:
        if key not in KNOWN_KEYS:
            out.append(finding("warn", "AM004", f"{label}:autoMode.{key}",
                               f"알 수 없는 키 '{key}'. 쓸 수 있는 키: {', '.join(sorted(KNOWN_KEYS))}"))
    if "classifyAllShell" in block and not isinstance(block["classifyAllShell"], bool):
        out.append(finding("error", "AM004", f"{label}:autoMode.classifyAllShell",
                           "classifyAllShell 은 true/false 여야 한다"))
    for sec in SECTIONS:
        if sec not in block:
            continue
        arr = block[sec]
        where = f"{label}:autoMode.{sec}"
        if not isinstance(arr, list):
            out.append(finding("error", "AM004", where, f"배열이어야 한다(지금: {type(arr).__name__})"))
            continue
        if not arr:
            sev, why = LOSS[sec]
            out.append(finding("warn" if sev != "info" else "info", "AM005", where,
                               f"빈 배열이다. 기본값을 유지하려면 키를 지우거나 [\"$defaults\"]로 쓴다. 빈 배열은 내장 규칙을 대체한다: {why}"))
            continue
        strs = [x for x in arr if isinstance(x, str)]
        for i, x in enumerate(arr):
            if not isinstance(x, str):
                out.append(finding("error", "AM004", f"{where}[{i}]", f"항목은 문자열(산문 규칙)이어야 한다(지금: {type(x).__name__})"))
        n_def = sum(1 for x in strs if x == "$defaults")
        if n_def > 1:
            out.append(finding("warn", "AM006", where, f"\"$defaults\"가 {n_def}번 있다. 한 번이면 된다"))
        for i, x in enumerate(strs):
            if x != "$defaults" and NEAR_DEFAULTS.match(x.strip()):
                out.append(finding("error", "AM006", f"{where}[{i}]",
                                   f"\"{x}\"는 \"$defaults\"의 오타로 보인다. 정확히 \"$defaults\"여야 내장 규칙이 들어온다"))
        if n_def == 0:
            sev, why = LOSS[sec]
            out.append(finding(sev, "AM001", where,
                               f"\"$defaults\"가 없다 → 이 섹션의 내장 규칙을 전부 대체한다: {why}. 의도한 게 아니면 첫 항목에 \"$defaults\"를 둔다"))
        for i, x in enumerate(strs):
            if x == "$defaults":
                continue
            if PLACEHOLDER.search(x) or UPPER_HERE.search(x):
                out.append(finding("error", "AM002", f"{where}[{i}]", f"자리표시자로 보인다: {x[:80]!r}"))
            elif PATTERNY.match(x.strip()):
                out.append(finding("warn", "AM007", f"{where}[{i}]",
                                   f"권한 규칙 문법처럼 보인다: {x[:60]!r}. autoMode 항목은 산문이다. 도구 패턴은 permissions.allow/deny 에 쓴다"))
    return out


def scope_of(path, force=None):
    if force:
        return force
    p = path.replace("\\", "/")
    base = os.path.basename(p)
    if p.endswith("/.claude/settings.local.json") or (base == "settings.local.json"):
        return "project"
    if p.endswith("/.claude/settings.json") or p == ".claude/settings.json":
        home = os.path.expanduser("~").replace("\\", "/")
        return "user" if os.path.abspath(p).replace("\\", "/") == f"{home}/.claude/settings.json" else "project"
    if "managed" in base:
        return "managed"
    return "unknown"


def lint_file(path, scope=None):
    label = path
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None, [finding("error", "AM000", label, "파일이 없다")]
    except (OSError, json.JSONDecodeError) as e:
        return None, [finding("error", "AM000", label, f"읽거나 파싱하지 못했다: {e}")]
    if not isinstance(data, dict):
        return None, [finding("error", "AM000", label, "최상위가 객체가 아니다")]
    if "autoMode" not in data:
        return False, []
    return True, lint_block(data["autoMode"], label, scope_of(path, scope))


def default_targets(cwd, home):
    return [
        (os.path.join(home, ".claude", "settings.json"), "user"),
        (os.path.join(cwd, ".claude", "settings.json"), "project"),
        (os.path.join(cwd, ".claude", "settings.local.json"), "project"),
    ]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Claude Code autoMode 설정 린터")
    ap.add_argument("files", nargs="*", help="점검할 settings JSON. 없으면 ~/.claude/settings.json 과 현재 폴더의 .claude/ 설정")
    ap.add_argument("--scope", choices=["user", "managed", "project"], help="파일의 범위를 지정(기본: 경로로 추정)")
    ap.add_argument("--home", default=os.path.expanduser("~"), help="홈 폴더(테스트용)")
    ap.add_argument("--json", action="store_true", help="JSON으로 출력")
    ap.add_argument("--strict", action="store_true", help="경고도 실패로 센다")
    a = ap.parse_args(argv)

    targets = [(f, a.scope) for f in a.files] if a.files else default_targets(os.getcwd(), a.home)
    results, checked = [], []
    for path, scope in targets:
        if not a.files and not os.path.exists(path):
            continue  # 기본 탐색에서는 없는 파일을 건너뛴다
        has, fs = lint_file(path, scope)
        checked.append({"file": path, "has_autoMode": has})
        results.extend(fs)
    n_err = sum(1 for f in results if f["severity"] == "error")
    n_warn = sum(1 for f in results if f["severity"] == "warn")
    if any(f["code"] == "AM000" for f in results):
        rc = 2  # 파일을 읽지 못함: 점검 자체가 안 됐다
    else:
        rc = 1 if n_err or (a.strict and n_warn) else 0

    if a.json:
        print(json.dumps({"checked": checked, "findings": results, "errors": n_err, "warnings": n_warn, "exit": rc},
                         ensure_ascii=False, indent=2))
    else:
        if not checked:
            print("점검할 설정 파일이 없다(~/.claude/settings.json, .claude/settings*.json). 파일 경로를 인자로 주면 그 파일을 본다.")
        for c in checked:
            if c["has_autoMode"] is False:
                print(f"- {c['file']}: autoMode 블록 없음(기본값 그대로)")
        for f in results:
            tag = {"error": "오류", "warn": "경고", "info": "참고"}[f["severity"]]
            print(f"[{tag}] {f['code']} {f['where']}\n       {f['message']}")
        print(f"\n파일 {len(checked)}개 · 오류 {n_err} · 경고 {n_warn} → exit {rc}")
        if checked and any(c["has_autoMode"] for c in checked):
            print("실제 적용 결과는 `claude auto-mode config`로 확인한다(이 도구는 설정 파일만 본다).")
    return rc


if __name__ == "__main__":
    sys.exit(main())

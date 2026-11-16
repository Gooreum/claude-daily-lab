#!/usr/bin/env python3
"""rule-leak — Claude Code 설정 파일에 저장된 허용 규칙·env 안의 비밀값을 찾는다.

"항상 허용"을 누르면 명령 문자열이 그대로 .claude/settings.local.json 의 permissions.allow 규칙으로
저장된다. 명령에 비밀번호·토큰이 적혀 있었다면 그 값도 같이 저장된다.
이 도구는 설정 파일을 읽어 (1) 규칙·env 문자열 속 비밀값, (2) 파일이 git에 추적되는지·무시되는지를 점검한다.
비밀값은 앞 두 글자만 남기고 마스킹해서 출력한다(전체를 출력·저장하지 않는다).

    python3 rule_leak.py [경로...] [--home] [--json] [--quiet]

경로는 폴더(아래의 .claude/settings.json, .claude/settings.local.json 을 찾는다)나 설정 파일이다.
종료 코드: 0 = 문제 없음, 1 = LEAK(비밀값) 또는 TRACKED(로컬 파일이 추적됨) 또는 읽기 실패 있음, 2 = 사용 오류.
표준 라이브러리만 쓴다. 키·네트워크·모델 불필요.
출처: https://dev.to/roidayan/before-you-click-dont-ask-again-what-your-coding-agent-saves-and-how-to-keep-secrets-out-of-it-j2m
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "vendor"}
NAMES = ("settings.json", "settings.local.json")
SECRET_NAME = r"[A-Za-z0-9_]*?(?:PASSWORD|PASSWD|PASS|PWD|SECRET|TOKEN|API_?KEY|ACCESS_?KEY|PRIVATE_?KEY|CREDENTIALS?)"

# (종류, 정규식, 비밀로 볼 그룹 번호). 소스에 비밀 패턴 문자열이 그대로 보이지 않게 일부러 나눠 적었다.
PATTERNS = [
    ("api-key", re.compile(r"(sk-" r"ant-[A-Za-z0-9_\-]{16,})"), 1),
    ("api-key", re.compile(r"\b(AK" r"IA[0-9A-Z]{16})\b"), 1),
    ("api-key", re.compile(r"\b((?:gh" r"[pousr]_|github_" r"pat_)[A-Za-z0-9_]{20,})"), 1),
    ("api-key", re.compile(r"\b(xox[abpr]-[A-Za-z0-9-]{10,})"), 1),
    ("api-key", re.compile(r"\b(AIza[0-9A-Za-z_\-]{30,})"), 1),
    ("private-key", re.compile(r"(-----BEGIN [A-Z ]*PRIV" r"ATE KEY)"), 1),
    ("bearer", re.compile(r"(?i)\b(?:bearer|basic|token)\s+([A-Za-z0-9._~+/=\-]{8,})"), 1),
    ("url-cred", re.compile(r"://[^\s/:@'\"]+:([^\s/@'\"]{3,})@"), 1),
    ("cli-flag", re.compile(r"(?i)--(?:password|passwd|token|secret|api-?key|access-?key)(?:=|\s+)(['\"]?)([^\s'\"*$<]{3,})\1"), 2),
    ("curl-user", re.compile(r"\bcurl\b[^|;]*?\s-u\s+['\"]?[^\s:'\"]+:([^\s'\"*$<]{3,})"), 1),
    ("inline-env", re.compile(r"(?<![\w-])" + SECRET_NAME + r"=(['\"]?)([^\s'\"*$<]{1,})\1"), 2),
]
ENV_NAME = re.compile(r"(?:^|_)(?:PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY|PRIVATE_?KEY|CREDENTIALS?)$", re.I)
PLACEHOLDER = re.compile(r"^(\$|<|\{\{|your[_-]|xxx|changeme|example|none$|null$|true$|false$|\d{1,3}$)", re.I)


def mask(v: str) -> str:
    return (v[:2] if len(v) > 4 else v[:1]) + "***(" + str(len(v)) + "자)"


def scan_string(s: str):
    """문자열 하나에서 (종류, 마스킹한 문자열) 목록. 같은 구간은 한 번만 센다."""
    hits, taken = [], []
    for kind, rx, grp in PATTERNS:
        for m in rx.finditer(s):
            a, b = m.span(grp)
            if any(a < y and x < b for x, y in taken):
                continue
            if PLACEHOLDER.match(m.group(grp)):
                continue
            taken.append((a, b))
            hits.append((kind, a, b))
    hits.sort(key=lambda h: h[1])
    out, shown = [], s
    for kind, a, b in reversed(hits):
        shown = shown[:a] + mask(s[a:b]) + shown[b:]
    for kind, _, _ in hits:
        out.append(kind)
    return out, shown


def scan_settings(data):
    findings = []
    perms = data.get("permissions") if isinstance(data, dict) else None
    if isinstance(perms, dict):
        for lst in ("allow", "ask", "deny"):
            for i, rule in enumerate(perms.get(lst) or []):
                if not isinstance(rule, str):
                    continue
                kinds, shown = scan_string(rule)
                for k in kinds:
                    findings.append({"where": f"permissions.{lst}[{i}]", "kind": k, "text": shown[:110]})
    env = data.get("env") if isinstance(data, dict) else None
    if isinstance(env, dict):
        for k, v in env.items():
            if not isinstance(v, str) or not v:
                continue
            kinds, shown = scan_string(v)
            if kinds:
                for kind in kinds:
                    findings.append({"where": f"env.{k}", "kind": kind, "text": shown[:110]})
            elif ENV_NAME.search(k) and len(v) >= 8 and not PLACEHOLDER.match(v):
                findings.append({"where": f"env.{k}", "kind": "env-literal", "text": mask(v)})
    return findings


def git_state(path):
    d, name = os.path.dirname(os.path.abspath(path)), os.path.basename(path)

    def run(*a):
        try:
            return subprocess.run(["git", "-C", d, *a], capture_output=True, text=True, timeout=20).returncode
        except (OSError, subprocess.SubprocessError):
            return None
    if run("rev-parse", "--is-inside-work-tree") != 0:
        return "no-git"
    if run("ls-files", "--error-unmatch", "--", name) == 0:
        return "tracked"
    return "ignored" if run("check-ignore", "-q", "--", name) == 0 else "untracked"


def find_files(paths, home):
    files = []
    for p in paths:
        if os.path.isfile(p):
            files.append(p)
            continue
        for root, dirs, names in os.walk(p):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS or x == ".claude"]
            if os.path.basename(root) == ".claude":
                files += [os.path.join(root, n) for n in NAMES if n in names]
    if home:
        for n in NAMES:
            f = os.path.join(os.path.expanduser("~"), ".claude", n)
            if os.path.isfile(f):
                files.append(f)
    return sorted(dict.fromkeys(files))


def check(path):
    r = {"file": path, "git": git_state(path), "findings": [], "error": None}
    try:
        with open(path, encoding="utf-8") as f:
            r["findings"] = scan_settings(json.load(f))
    except (OSError, ValueError) as e:
        r["error"] = f"{type(e).__name__}: {str(e)[:80]}"
    local = os.path.basename(path) == "settings.local.json"
    if r["error"]:
        r["verdict"] = "ERROR"
    elif r["findings"]:
        r["verdict"] = "LEAK"
    elif local and r["git"] == "tracked":
        r["verdict"] = "TRACKED"
    elif local and r["git"] == "untracked":
        r["verdict"] = "UNIGNORED"
    else:
        r["verdict"] = "OK"
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(description="설정 파일의 허용 규칙·env 속 비밀값 점검")
    ap.add_argument("paths", nargs="*", default=["."])
    ap.add_argument("--home", action="store_true", help="~/.claude/settings*.json 도 본다")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="OK 줄은 숨긴다")
    a = ap.parse_args(argv)
    for p in a.paths:
        if not os.path.exists(p):
            print(f"오류: 경로가 없다: {p}", file=sys.stderr)
            return 2
    results = [check(f) for f in find_files(a.paths, a.home)]
    counts = {v: sum(1 for r in results if r["verdict"] == v) for v in ("LEAK", "TRACKED", "UNIGNORED", "ERROR", "OK")}
    if a.json:
        print(json.dumps({"counts": counts, "results": results}, ensure_ascii=False, indent=2))
    else:
        for r in results:
            if a.quiet and r["verdict"] == "OK":
                continue
            print(f"{r['verdict']:<9} {r['file']}  [git: {r['git']}]")
            if r["error"]:
                print(f"          읽기 실패 — {r['error']}")
            for f in r["findings"]:
                print(f"          {f['where']}  {f['kind']}  {f['text']}")
            if r["verdict"] == "TRACKED":
                print("          로컬 전용 파일이 git에 추적된다 — git rm --cached 후 .gitignore 에 추가")
            if r["verdict"] == "UNIGNORED":
                print("          .gitignore 에 없다 — 이 컴퓨터의 전역 제외에만 기대는 중일 수 있다")
            if r["verdict"] == "LEAK":
                tip = " (이미 추적 중이면 git 기록에 남아 있다)" if r["git"] == "tracked" else ""
                print(f"          순서: 1) 값을 폐기·재발급 2) 규칙에서 값을 빼고 세션 허용으로 대체{tip}")
        print("합계: " + " ".join(f"{k}={v}" for k, v in counts.items()) + f" (파일 {len(results)}개)")
    bad = counts["LEAK"] + counts["TRACKED"] + counts["ERROR"]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""cc-advisory: 설치된 Claude Code 버전을 보안 공지의 수정 버전과 대조한다.

사용:
  python3 cc_advisory.py                       # claude --version을 읽어 점검 (미달이면 exit 1)
  python3 cc_advisory.py --version 2.1.200     # 버전을 직접 지정
  python3 cc_advisory.py --json                # 기계가 읽는 결과
  python3 cc_advisory.py --list                # 공지 표만 출력
  python3 cc_advisory.py --table my.json       # 공지 표를 내 파일로 교체/추가
  python3 cc_advisory.py --hook                # SessionStart 훅: 미달일 때만 사실 문장을 낸다(항상 exit 0)
  python3 cc_advisory.py --print-settings      # settings.json에 넣을 훅 조각

종료 코드(CLI): 0 모두 수정 버전 이상 / 1 미달 공지 있음 / 2 버전을 알 수 없음.
표준 라이브러리만 쓴다. 네트워크·키·모델 호출 없음.
"""
import argparse
import json
import re
import subprocess
import sys

# 공지 표. 2026-11-12에 GitHub 공지 페이지에서 수정 버전·영향 범위·게시일을 직접 확인했다.
# 새 공지는 이 목록에 한 줄을 더하거나 --table 파일로 넘긴다.
BUILTIN = [
    {
        "id": "GHSA-5j29-h97v-84ch",
        "cve": "CVE-2026-103435",
        "severity": "High",
        "fixed": "2.1.129",
        "published": "2026-10-05",
        "title": "Write-time symlink following (TOCTOU) lets an edit land outside the project",
        "url": "https://github.com/anthropics/claude-code/security/advisories/GHSA-5j29-h97v-84ch",
    },
    {
        "id": "GHSA-5xjx-9qx6-jcrv",
        "cve": "CVE-2026-88968",
        "severity": "High",
        "fixed": "2.1.251",
        "published": "2026-10-26",
        "title": "TOCTOU race in the Edit tool allows file writes outside the workspace",
        "url": "https://github.com/anthropics/claude-code/security/advisories/GHSA-5xjx-9qx6-jcrv",
    },
]

VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def parse_version(text):
    """'2.1.322 (Claude Code)' 같은 문자열에서 첫 X.Y.Z를 (X, Y, Z)로. 없으면 None."""
    if not isinstance(text, str):
        return None
    m = VERSION_RE.search(text)
    if not m:
        return None
    return tuple(int(x) for x in m.groups())


def fmt(v):
    return ".".join(str(x) for x in v)


def load_table(path):
    if not path:
        return list(BUILTIN)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        extra = data.get("advisories", [])
        base = list(BUILTIN) if data.get("extend", True) else []
        data = base + extra
    if not isinstance(data, list):
        raise ValueError("공지 표는 목록이거나 {advisories: [...]} 여야 한다")
    for a in data:
        if parse_version(a.get("fixed")) is None:
            raise ValueError("fixed 버전을 읽을 수 없는 공지: %r" % (a.get("id"),))
    return data


def installed_version(cmd="claude"):
    """claude --version 출력에서 버전을 읽는다. 실패하면 None."""
    try:
        out = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_version(out.stdout) or parse_version(out.stderr)


def check(version, table):
    """version 미만에서 고쳐진 공지만 골라 수정 버전이 높은 순으로 돌려준다."""
    hit = [a for a in table if version < parse_version(a["fixed"])]
    hit.sort(key=lambda a: parse_version(a["fixed"]), reverse=True)
    return hit


def facts(version, hit):
    """사실 문장만(명령조 없음). SessionStart 컨텍스트로도 쓴다."""
    top = hit[0]
    lines = [
        "Installed Claude Code is %s. Security advisories with a fixed version above it: %d. Highest fixed version: %s."
        % (fmt(version), len(hit), top["fixed"])
    ]
    for a in hit:
        lines.append("- %s (%s, %s) fixed in %s: %s" % (a["id"], a.get("cve", "no CVE"), a.get("severity", "?"), a["fixed"], a["title"]))
    return "\n".join(lines)


def settings_snippet():
    return {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/cc_advisory.py --hook",
                            "timeout": 15,
                        }
                    ],
                }
            ]
        }
    }


def run_hook(args):
    """훅은 어떤 경우에도 exit 0. 미달일 때만 출력, 그 외(버전 모름 포함)는 조용히."""
    try:
        try:
            sys.stdin.read()
        except Exception:
            pass
        table = load_table(args.table)
        v = parse_version(args.version) if args.version else installed_version()
        if v is None:
            return 0
        hit = check(v, table)
        if not hit:
            return 0
        text = facts(v, hit)
        if args.plain:
            print(text)
        else:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}, ensure_ascii=False))
    except BaseException:
        pass
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Claude Code 버전을 보안 공지의 수정 버전과 대조")
    ap.add_argument("--version", help="점검할 버전 (기본: claude --version)")
    ap.add_argument("--table", help="공지 표 JSON 파일 (목록 또는 {extend, advisories})")
    ap.add_argument("--json", action="store_true", help="결과를 JSON으로")
    ap.add_argument("--list", action="store_true", help="공지 표만 출력")
    ap.add_argument("--hook", action="store_true", help="SessionStart 훅 모드(항상 exit 0)")
    ap.add_argument("--plain", action="store_true", help="--hook에서 JSON 대신 일반 텍스트")
    ap.add_argument("--print-settings", action="store_true", help="settings.json 훅 조각 출력")
    args = ap.parse_args(argv)

    if args.hook:
        return run_hook(args)
    if args.print_settings:
        print(json.dumps(settings_snippet(), indent=2))
        return 0
    try:
        table = load_table(args.table)
    except (OSError, ValueError) as e:
        print("공지 표를 읽지 못했다: %s" % e, file=sys.stderr)
        return 2
    if args.list:
        for a in sorted(table, key=lambda a: a.get("published", "")):
            print("%-22s %-16s %-8s fixed %-8s %s  %s" % (a["id"], a.get("cve", "-"), a.get("severity", "?"), a["fixed"], a.get("published", ""), a["title"]))
        return 0

    v = parse_version(args.version) if args.version else installed_version()
    if v is None:
        print("버전을 알 수 없다: %s" % ("입력 '%s'에서 X.Y.Z를 못 찾음" % args.version if args.version else "`claude --version` 실행·파싱 실패"), file=sys.stderr)
        return 2
    hit = check(v, table)
    if args.json:
        print(json.dumps({"version": fmt(v), "vulnerable": bool(hit), "advisories": hit, "checked": len(table)}, ensure_ascii=False, indent=2))
    elif hit:
        print(facts(v, hit))
        print("확인한 공지 %d개 중 %d개가 이 버전에 해당한다." % (len(table), len(hit)))
    else:
        print("Claude Code %s: 표의 공지 %d개 모두 수정 버전 이상이다." % (fmt(v), len(table)))
    return 1 if hit else 0


if __name__ == "__main__":
    sys.exit(main())

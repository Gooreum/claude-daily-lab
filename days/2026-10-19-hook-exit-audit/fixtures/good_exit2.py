#!/usr/bin/env python3
import json, re, sys


def main():
    data = json.load(sys.stdin)
    cmd = data["tool_input"]["command"]
    if re.search(r"rm -rf|git (-\w+ \S+ )*push .*(--force|-f\b|\+|--mirror)|git reset --hard|DROP TABLE|\| *sh\b", cmd):
        print("차단: 위험한 명령입니다. 사용자에게 먼저 물어보세요.", file=sys.stderr)
        return 2
    return 0


try:
    sys.exit(main())
except Exception as e:  # 크래시도 막는 쪽으로 (fail closed)
    print(f"차단: 훅 오류 {e}", file=sys.stderr)
    sys.exit(2)

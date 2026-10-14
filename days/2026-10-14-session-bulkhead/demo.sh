#!/usr/bin/env bash
# demo.sh — Claude Code 없이 훅 프로토콜(stdin JSON → exit code + stderr)만으로 세션 둘의 충돌을 재현한다.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
HOOK="$PWD/hooks/session_bulkhead.py"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/repo/.git"
export SESSION_BULKHEAD_STATE="$T/state" SESSION_BULKHEAD_MEM_MB=8000 SESSION_BULKHEAD_CONFIG="$T/none.json"
call() { # $1=세션 $2=명령
  printf '\n$ [%s] %s\n' "$1" "$2"
  printf '{"session_id":"%s","cwd":"%s","tool_name":"Bash","tool_input":{"command":%s}}' \
    "$1" "$T/repo" "$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$2")" | python3 "$HOOK" hook
  echo "  -> exit $?"
}
call sessionA-1111 "npm run dev -- --port 3000"
call sessionB-2222 "npm run dev -- --port 3000"
call sessionB-2222 "pkill node"
call sessionB-2222 "git checkout -b feature-x"
call sessionB-2222 "kill 4242"
call sessionB-2222 "npm run dev -- --port 3001"
echo; python3 "$HOOK" status

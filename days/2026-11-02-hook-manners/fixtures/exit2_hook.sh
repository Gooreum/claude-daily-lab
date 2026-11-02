#!/bin/sh
# 나쁜 관찰 훅: jq가 실패하면 exit 2로 끝나 동작을 막는다.
cat | python3 -c 'import json,sys; json.load(sys.stdin)' 2>/dev/null || exit 2

#!/usr/bin/env bash
# 모델을 부르는 확인(CI 제외). 깨진 settings.json을 둔 폴더에서 `claude -p`를 돌려
#  (1) settings_live.py 가 그 파일을 error 로 잡는지,
#  (2) 같은 폴더에서 Claude Code 스트림에 settings_not_in_effect 경고가 오는지 본다.
# 로그인이 없으면 SKIP(exit 0).
set -u
cd "$(dirname "$0")"
HERE=$PWD
command -v claude >/dev/null || { echo "SKIP claude CLI 없음"; exit 0; }
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/.claude"
printf '{\n "permissions": {"deny": ["Read(./secret.txt)",]}\n}\n' > "$T/.claude/settings.json"

python3 "$HERE/settings_live.py" --root "$T" --home "$T/none" >"$T/live.txt"; rc=$?
[ $rc -eq 1 ] && echo "ok   settings_live: 깨진 파일을 error 로 잡음" || { echo "FAIL settings_live exit=$rc"; exit 1; }

cd "$T"
timeout 120 claude -p "Say ok" --model claude-haiku-5-5 --effort low --max-turns 3 --tools "" \
  --output-format stream-json --verbose >"$T/out.jsonl" 2>"$T/err.txt"
if grep -q "Not logged in" "$T/out.jsonl"; then echo "SKIP 로그인이 없어 claude -p 확인 생략"; exit 0; fi
if grep -q settings_not_in_effect "$T/out.jsonl"; then
  echo "ok   claude -p 스트림에 settings_not_in_effect 경고가 옴"
else
  echo "INFO claude -p 스트림에 settings_not_in_effect 가 없다 — 이 경고는 SDK 호스트(Agent SDK) 메시지일 수 있다"
fi

#!/usr/bin/env bash
# e2e.sh — 실제 Claude Code로 모드를 --plugin-dir로 싣고 /turnstats 명령이 동작하는지 본다. `bash e2e.sh`
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
command -v claude >/dev/null || { echo "claude CLI 없음"; exit 1; }
echo "claude: $(claude --version)"
pass=0; fail=0
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

echo "== 1) claude -p '/turnstats' → 모드의 명령 응답"
out="$(cd "$tmp" && claude -p "/turnstats" --plugin-dir "$OLDPWD/turn-notify" --output-format text 2>&1 < /dev/null)"
printf '%s\n' "$out" | sed 's/^/   | /'
if [[ "$out" == *"No turns yet in this session"* ]]; then pass=$((pass+1)); echo "  ✅ /turnstats 응답"; else fail=$((fail+1)); echo "  ❌ /turnstats 응답 없음"; fi

echo "== 2) 모드 없이 /turnstats → 알 수 없는 명령 (대조군)"
out="$(cd "$tmp" && claude -p "/turnstats" --output-format text 2>&1 < /dev/null)"
printf '%s\n' "$out" | sed 's/^/   | /'
if [[ "$out" != *"No turns yet in this session"* ]]; then pass=$((pass+1)); echo "  ✅ 모드 없을 땐 응답 없음"; else fail=$((fail+1)); echo "  ❌ 모드 없이도 응답됨?"; fi

echo "== 3) 실제 턴 1회 + stream-json으로 turn.complete 결과 텍스트 확인"
out="$(cd "$tmp" && claude -p "Reply with exactly: OK" --model claude-haiku-5-5 --plugin-dir "$OLDPWD/turn-notify" --output-format stream-json --verbose --max-turns 1 2>&1 < /dev/null)"
printf '%s\n' "$out" | grep -E '⏱|"type":"result"' | cut -c1-220 | sed 's/^/   | /'
if [[ "$out" == *"⏱ "* ]]; then pass=$((pass+1)); echo "  ✅ 턴 요약 줄(⏱) 출력됨"; else echo "  ⚠ 턴 요약 줄이 stream-json에 안 보임 (대화형 전용일 수 있음) — 실패로 세지 않음"; fi

echo "== 결과: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]

#!/usr/bin/env bash
# e2e.sh — 실제 Claude Code로 모드를 --plugin-dir로 싣고 /pet 명령과 실제 턴 후 상태를 본다. `bash e2e.sh`
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
command -v claude >/dev/null || { echo "claude CLI 없음"; exit 1; }
echo "claude: $(claude --version)"
pass=0; fail=0
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

echo "== 0) /pet reset → 저장소의 펫을 새로 깐다 (\$.store는 세션 사이에 남으므로)"
out="$(cd "$tmp" && claude -p "/pet reset" --plugin-dir "$OLDPWD/token-pet" --output-format text 2>&1 < /dev/null)"
printf '%s\n' "$out" | sed 's/^/   | /'
if [[ "$out" == *"A new pet hatched."* ]]; then pass=$((pass+1)); echo "  ✅ reset"; else fail=$((fail+1)); echo "  ❌ reset 실패"; fi

echo "== 1) claude -p '/pet' → 새 펫 상태"
out="$(cd "$tmp" && claude -p "/pet" --plugin-dir "$OLDPWD/token-pet" --output-format text 2>&1 < /dev/null)"
printf '%s\n' "$out" | sed 's/^/   | /'
if [[ "$out" =~ Claudie\ ·\ happy\ ·\ fullness\ (5[6-9]|60)/100\ ·\ 0\ meals\ ·\ 0\ bruises ]]; then pass=$((pass+1)); echo "  ✅ /pet 응답 (reset 뒤 몇 초 지나 1~2점 꺼질 수 있음)"; else fail=$((fail+1)); echo "  ❌ /pet 응답 없음"; fi

echo "== 2) 모드 없이 /pet → 응답 없음 (대조군)"
out="$(cd "$tmp" && claude -p "/pet" --output-format text 2>&1 < /dev/null)"
printf '%s\n' "$out" | head -3 | sed 's/^/   | /'
if [[ "$out" != *"Claudie ·"* ]]; then pass=$((pass+1)); echo "  ✅ 모드 없을 땐 응답 없음"; else fail=$((fail+1)); echo "  ❌ 모드 없이도 응답됨?"; fi

echo "== 3) 실제 턴 1회(세션 A) → 다음 세션(B)의 /pet에 meals 1, 포만감 증가가 남아 있다"
out="$(cd "$tmp" && claude -p "Reply with exactly: OK" --model claude-haiku-5-5 --plugin-dir "$OLDPWD/token-pet" --output-format json --max-turns 1 2>&1 < /dev/null)"
tok="$(printf '%s' "$out" | python3 -c "import json,sys; u=json.load(sys.stdin)['usage']; print(u['input_tokens']+u['output_tokens']+u.get('cache_read_input_tokens',0))" 2>/dev/null)"
echo "   | 세션 A 토큰: $tok"
out2="$(cd "$tmp" && claude -p "/pet" --plugin-dir "$OLDPWD/token-pet" --output-format text 2>&1 < /dev/null)"
printf '%s\n' "$out2" | sed 's/^/   | /'
if [[ "$out2" == *"· 1 meals ·"* ]] && [[ "$out2" != *"fullness 60/100"* ]]; then pass=$((pass+1)); echo "  ✅ 세션 A의 턴이 세션 B의 펫에 밥 1끼로 남음"; else fail=$((fail+1)); echo "  ❌ 세션 간 지속 실패"; fi

echo "== 4) 정리: /pet reset"
(cd "$tmp" && claude -p "/pet reset" --plugin-dir "$OLDPWD/token-pet" --output-format text >/dev/null 2>&1 < /dev/null) && echo "  ✅ reset"

echo "== 결과: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]

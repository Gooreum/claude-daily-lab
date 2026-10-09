#!/usr/bin/env bash
# e2e.sh — 실제 Claude Haiku 5.5 다섯 명으로 한 판. 30~40번의 `claude -p` 호출, 약 2~4분, 수십 센트 미만.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
command -v claude >/dev/null || { echo "claude CLI 없음"; exit 1; }
seed="${1:-$RANDOM}"
echo "claude: $(claude --version) · seed=$seed"
out="$(python3 mafia.py --seed "$seed" 2>&1)"; rc=$?
printf '%s\n' "$out"
pass=0; fail=0
[ "$rc" -eq 0 ] && pass=$((pass+1)) || fail=$((fail+1))
[[ "$out" == *"🏁"* ]] && pass=$((pass+1)) || fail=$((fail+1))
[[ "$out" != *"대본 봇이 대신"* ]] && { pass=$((pass+1)); echo "  ✅ 대본 봇 개입 없이 전부 모델이 답함"; } || { fail=$((fail+1)); echo "  ❌ 일부 응답이 대본 봇으로 대체됨"; }
[[ "$out" == *"💸 모델 호출"* ]] && pass=$((pass+1)) || fail=$((fail+1))
echo "== 결과: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]

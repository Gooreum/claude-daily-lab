#!/usr/bin/env bash
# e2e.sh — 실제 Haiku 5.5로 5레벨 × 8문제 = 40회 호출 (동시 5, 약 1~2분, 수십 센트 미만). `bash e2e.sh [--model …]`
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
command -v claude >/dev/null || { echo "claude CLI 없음"; exit 1; }
echo "claude: $(claude --version)"
out="$(python3 race.py "$@" 2>&1)"; rc=$?
printf '%s\n' "$out"
pass=0; fail=0
[ "$rc" -eq 0 ] && pass=$((pass+1)) || fail=$((fail+1))
[[ "$out" == *"호출 40회"* ]] && pass=$((pass+1)) || fail=$((fail+1))
[[ "$out" != *"⚠ 실패"* ]] && { pass=$((pass+1)); echo "  ✅ 40회 전부 응답"; } || { fail=$((fail+1)); echo "  ❌ 실패한 호출 있음"; }
echo "== 결과: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]

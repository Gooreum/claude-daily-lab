#!/usr/bin/env bash
# e2e.sh — 실제 Haiku 5.5로 3시나리오 × N회(기본 4) 측정. 12회 호출, 약 30~60초, 1센트 미만. `bash e2e.sh [-n 6] [--model …]`
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
command -v claude >/dev/null || { echo "claude CLI 없음"; exit 1; }
echo "claude: $(claude --version)"
out="$(python3 cache_meter.py "$@" 2>&1)"; rc=$?
printf '%s\n' "$out"
pass=0; fail=0
[ "$rc" -eq 0 ] && pass=$((pass+1)) || fail=$((fail+1))
[[ "$out" != *"⚠ 실패"* ]] && { pass=$((pass+1)); echo "  ✅ 전부 응답"; } || { fail=$((fail+1)); echo "  ❌ 실패한 호출 있음"; }
# stable은 2회차부터 읽기(■)가 나와야 하고, volatile-head는 2회차 이후 적중률이 stable보다 낮아야 한다
stable_row="$(printf '%s\n' "$out" | grep -E '^  stable +[▒■◧·✗]' | head -1)"
[[ "$stable_row" == *"■"* ]] && { pass=$((pass+1)); echo "  ✅ stable에 캐시 읽기(■) 등장"; } || { fail=$((fail+1)); echo "  ❌ stable에 읽기 없음: $stable_row"; }
s_hit="$(printf '%s\n' "$out" | sed -n '/2회차 이후 평균 캐시 적중률/,/^$/p' | grep -E '^  stable ' | grep -oE '[0-9.]+%' | tr -d '%')"
h_hit="$(printf '%s\n' "$out" | sed -n '/2회차 이후 평균 캐시 적중률/,/^$/p' | grep -E '^  volatile-head ' | grep -oE '[0-9.]+%' | tr -d '%')"
python3 -c "import sys; s,h=float(sys.argv[1]),float(sys.argv[2]); sys.exit(0 if s>h else 1)" "${s_hit:-0}" "${h_hit:-100}" \
  && { pass=$((pass+1)); echo "  ✅ stable 적중률(${s_hit}%) > volatile-head(${h_hit}%)"; } || { fail=$((fail+1)); echo "  ❌ 적중률 비교 실패 stable=${s_hit} head=${h_hit}"; }
echo "== 결과: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]

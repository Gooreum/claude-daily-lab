#!/usr/bin/env bash
# e2e.sh — ANTHROPIC_API_KEY로 실제 GET /v1/models를 받아 표·스냅샷·diff를 돌린다. `bash e2e.sh`
# 키가 없으면 아무것도 호출하지 않고 1로 끝난다 (Claude Code 로그인(OAuth)은 이 엔드포인트에 못 쓴다).
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
[ -n "${ANTHROPIC_API_KEY:-}" ] || { echo "ANTHROPIC_API_KEY 없음 — e2e 건너뜀 (bash test.sh는 키 없이 돈다)"; exit 1; }
today="$(date +%F)"; snap="snapshots/$today.json"
pass=0; fail=0
echo "== 1) live → 표 + 스냅샷 저장 ($snap)"
out="$(python3 model_caps.py --live --lifecycle active,deprecated --save "$snap" 2>&1)"; rc=$?
printf '%s\n' "$out" | head -12 | sed 's/^/   | /'
[ "$rc" -eq 0 ] && [[ "$out" == *" models · "* ]] && { pass=$((pass+1)); echo "  ✅ 표"; } || { fail=$((fail+1)); echo "  ❌ exit=$rc"; }
echo "== 2) haiku 최신 id"
out="$(python3 model_caps.py --from "$snap" --latest haiku)"; [[ "$out" == claude-* ]] && { pass=$((pass+1)); echo "  ✅ $out"; } || { fail=$((fail+1)); echo "  ❌ $out"; }
echo "== 3) 직전 스냅샷이 있으면 diff"
prev="$(ls snapshots/*.json 2>/dev/null | grep -v "$today" | tail -1)"
if [ -n "$prev" ]; then
  python3 model_caps.py --from "$snap" --diff "$prev" | sed 's/^/   | /' && { pass=$((pass+1)); echo "  ✅ diff $prev"; } || { fail=$((fail+1)); echo "  ❌ diff"; }
else
  echo "   | 이전 스냅샷 없음 — 내일부터 diff가 나온다"
fi
echo "== 결과: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]

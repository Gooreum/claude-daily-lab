#!/usr/bin/env bash
# test.sh — 이 폴더에서 `bash test.sh`. 모델 호출 없이 테스트 + dry-run (CI에서 실행). 실제 측정은 `bash e2e.sh`.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
fail=0
echo "== 1) python3 -m unittest"
python3 -m unittest discover -s tests -v 2>&1 | grep -E 'Ran |^OK|FAILED|ERROR' | sed 's/^/  /'
python3 -m unittest discover -s tests >/dev/null 2>&1 && echo "  ✅ unittest" || { echo "  ❌ unittest"; python3 -m unittest discover -s tests 2>&1 | tail -25; fail=1; }
echo "== 2) dry-run 그래프"
out="$(python3 cache_meter.py --dry-run --seed 1 --no-save)"; rc=$?
printf '%s\n' "$out" | sed -n '/호출별 캐시/,/^$/p' | sed 's/^/   | /'
[ "$rc" -eq 0 ] && [[ "$out" == *"호출 12회"* ]] && [[ "$out" == *"누적 비용 곡선"* ]] && echo "  ✅ 3시나리오 × 4회 그래프" || { echo "  ❌ dry-run exit=$rc"; fail=1; }
echo "== 결과: $([ $fail -eq 0 ] && echo PASS || echo FAIL)"
exit "$fail"

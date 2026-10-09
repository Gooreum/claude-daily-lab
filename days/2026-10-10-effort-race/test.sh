#!/usr/bin/env bash
# test.sh — 이 폴더에서 `bash test.sh`. 모델 호출 없이 채점·집계·그래프·CLI 테스트 + dry-run (CI에서 실행).
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
fail=0
echo "== 1) python3 -m unittest"
python3 -m unittest discover -s tests -v 2>&1 | grep -E 'Ran |^OK|FAILED|ERROR' | sed 's/^/  /'
python3 -m unittest discover -s tests >/dev/null 2>&1 && echo "  ✅ unittest" || { echo "  ❌ unittest"; python3 -m unittest discover -s tests 2>&1 | tail -25; fail=1; }
echo "== 2) dry-run 그래프"
out="$(python3 race.py --dry-run --seed 3 --no-save)"; rc=$?
printf '%s\n' "$out" | sed -n '3,10p' | sed 's/^/   | /'
[ "$rc" -eq 0 ] && [[ "$out" == *"호출 40회"* ]] && [[ "$out" == *"문제별 정답"* ]] && echo "  ✅ 5레벨 × 8문제 그래프" || { echo "  ❌ dry-run exit=$rc"; fail=1; }
echo "== 결과: $([ $fail -eq 0 ] && echo PASS || echo FAIL)"
exit "$fail"

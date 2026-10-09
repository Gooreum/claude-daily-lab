#!/usr/bin/env bash
# test.sh — 이 폴더에서 `bash test.sh`. 모델 호출 없이 엔진 테스트 + dry-run 한 판 (CI에서 실행).
# 실제 Haiku 5.5 플레이어로 한 판 돌리려면 `bash e2e.sh`.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
fail=0
echo "== 1) python3 -m unittest"
python3 -m unittest discover -s tests -v 2>&1 | grep -E 'Ran |^OK|FAILED|ERROR' | sed 's/^/  /'
python3 -m unittest discover -s tests >/dev/null 2>&1 && echo "  ✅ unittest" || { echo "  ❌ unittest"; python3 -m unittest discover -s tests 2>&1 | tail -20; fail=1; }
echo "== 2) dry-run 한 판 (seed 7)"
out="$(python3 mafia.py --dry-run --seed 7 --no-save)"; rc=$?
printf '%s\n' "$out" | tail -4 | sed 's/^/   | /'
[ "$rc" -eq 0 ] && [[ "$out" == *"🏁"* ]] && [[ "$out" == *"정체 공개"* ]] && echo "  ✅ 게임이 끝까지 진행됨" || { echo "  ❌ dry-run exit=$rc"; fail=1; }
out2="$(python3 mafia.py --dry-run --seed 7 --no-save)"
[ "$out" = "$out2" ] && echo "  ✅ 같은 seed면 같은 게임 (재현 가능)" || { echo "  ❌ seed 재현 실패"; fail=1; }
echo "== 결과: $([ $fail -eq 0 ] && echo PASS || echo FAIL)"
exit "$fail"

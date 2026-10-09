#!/usr/bin/env bash
# test.sh — 이 폴더에서 `bash test.sh`. API 키 없이 unittest + dry-run 표 + diff (CI에서 실행). 실제 호출은 `bash e2e.sh`.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
fail=0
echo "== 1) python3 -m unittest"
python3 -m unittest discover -s tests -v 2>&1 | grep -E 'Ran |^OK|FAILED|ERROR' | sed 's/^/  /'
python3 -m unittest discover -s tests >/dev/null 2>&1 && echo "  ✅ unittest" || { echo "  ❌ unittest"; python3 -m unittest discover -s tests 2>&1 | tail -30; fail=1; }
echo "== 2) dry-run 표"
out="$(python3 model_caps.py)"; rc=$?
printf '%s\n' "$out" | head -6 | sed 's/^/   | /'
[ "$rc" -eq 0 ] && [[ "$out" == *"8 models"* ]] && [[ "$out" == *"| \`claude-haiku-5-5\` | haiku | active |"* ]] && echo "  ✅ 표 8행" || { echo "  ❌ dry-run exit=$rc"; fail=1; }
echo "== 3) 스냅샷 diff (sample-models-prev.json → sample-models.json)"
out="$(python3 model_caps.py --diff sample-models-prev.json)"; rc=$?
printf '%s\n' "$out" | sed 's/^/   | /'
[ "$rc" -eq 0 ] && [[ "$out" == *"➕ 추가 \`claude-haiku-5-5\`"* ]] && [[ "$out" == *"lifecycle active → deprecated"* ]] && echo "  ✅ 추가·변경 감지" || { echo "  ❌ diff exit=$rc"; fail=1; }
echo "== 4) --latest haiku"
out="$(python3 model_caps.py --latest haiku)"; [ "$out" = "claude-haiku-5-5" ] && echo "  ✅ $out" || { echo "  ❌ $out"; fail=1; }
echo "== 결과: $([ $fail -eq 0 ] && echo PASS || echo FAIL)"
exit "$fail"

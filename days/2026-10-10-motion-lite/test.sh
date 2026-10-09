#!/usr/bin/env bash
# test.sh — 이 폴더에서 `bash test.sh`. 모델 호출 없이 검증·렌더·CLI 테스트 (CI에서 실행).
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
fail=0
echo "== 1) python3 -m unittest"
python3 -m unittest discover -s tests -v 2>&1 | grep -E 'Ran |^OK|FAILED|ERROR' | sed 's/^/  /'
python3 -m unittest discover -s tests >/dev/null 2>&1 && echo "  ✅ unittest" || { echo "  ❌ unittest"; python3 -m unittest discover -s tests 2>&1 | tail -25; fail=1; }
echo "== 2) dry-run 렌더"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
out="$(python3 motion_lite.py --dry-run --out "$tmp")"; rc=$?
printf '%s\n' "$out" | sed 's/^/   | /'
[ "$rc" -eq 0 ] && [ -s "$tmp/claude-code-모드란.html" ] && echo "  ✅ HTML 생성 ($(wc -c < "$tmp/claude-code-모드란.html" | tr -d ' ') bytes)" || { echo "  ❌ dry-run 실패"; fail=1; }
echo "== 3) 샘플 스토리보드(samples/*.json)가 모두 유효하고 렌더됨"
for f in samples/*.json; do
  [ -e "$f" ] || { echo "  ⏭ 샘플 없음"; break; }
  python3 motion_lite.py --storyboard "$f" --out "$tmp" >/dev/null && echo "  ✅ $f" || { echo "  ❌ $f"; fail=1; }
done
echo "== 결과: $([ $fail -eq 0 ] && echo PASS || echo FAIL)"
exit "$fail"

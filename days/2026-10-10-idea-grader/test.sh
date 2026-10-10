#!/usr/bin/env bash
# test.sh — 이 폴더에서 `bash test.sh`. 모델 호출 없이 unittest + 샘플 채점 + 비교 (CI에서 실행). 실제 판정은 `bash e2e.sh`.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
fail=0
echo "== 1) python3 -m unittest"
python3 -m unittest discover -s tests -v 2>&1 | grep -E 'Ran |^OK|FAILED|ERROR' | sed 's/^/  /'
python3 -m unittest discover -s tests >/dev/null 2>&1 && echo "  ✅ unittest" || { echo "  ❌ unittest"; python3 -m unittest discover -s tests 2>&1 | tail -30; fail=1; }
echo "== 2) 샘플 채점 (3번은 일부러 나쁜 항목 → exit 1)"
out="$(python3 idea_grader.py samples/news-sample.md --worst 4)"; rc=$?
printf '%s\n' "$out" | sed -n '3,8p;/고칠 줄/,$p' | sed 's/^/   | /'
[ "$rc" -eq 1 ] && [[ "$out" == *"| 3 | (일부러 나쁜 항목)"*"4 ⚠ |"* ]] && [[ "$out" == *"같은 아이디어의 변주"* ]] && echo "  ✅ 나쁜 항목 적발, exit 1" || { echo "  ❌ exit=$rc"; fail=1; }
echo "== 3) 비교 (nope → fixed: 3번만 올라야 채택)"
out="$(python3 idea_grader.py samples/news-sample.md --compare samples/news-sample-fixed.md)"; rc=$?
printf '%s\n' "$out" | tail -4 | sed 's/^/   | /'
[ "$rc" -eq 0 ] && [[ "$out" == *"✅ 채택"* ]] && echo "  ✅ 힐클라이밍 판정" || { echo "  ❌ exit=$rc"; fail=1; }
echo "== 결과: $([ $fail -eq 0 ] && echo PASS || echo FAIL)"
exit "$fail"

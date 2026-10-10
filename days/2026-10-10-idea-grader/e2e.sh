#!/usr/bin/env bash
# e2e.sh — 실제 Haiku 5.5로 샘플 3개 항목을 판정한다 (claude -p 3회, 약 15초, 1센트 미만). `bash e2e.sh`
# 규칙 점수만으로는 1·2번(좋은 항목)과 3번(나쁜 항목)이 갈리지만, 모델 판정이 그 차이를 더 벌리는지 본다.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
command -v claude >/dev/null || { echo "claude CLI 없음"; exit 1; }
echo "claude: $(claude --version)"
out="$(python3 idea_grader.py samples/news-sample.md --judge 2>&1)"; rc=$?
printf '%s\n' "$out"
pass=0; fail=0
[[ "$out" != *"판정 실패"* ]] && { pass=$((pass+1)); echo "  ✅ 판정 3건 모두 응답"; } || { fail=$((fail+1)); echo "  ❌ 판정 실패 있음"; }
j1="$(printf '%s\n' "$out" | grep -E '^\| 1 \|' | awk -F'|' '{print $(NF-2)}' | tr -d ' ')"
j3="$(printf '%s\n' "$out" | grep -E '^\| 3 \|' | awk -F'|' '{print $(NF-2)}' | tr -d ' ')"
python3 -c "import sys; a,b=int(sys.argv[1]),int(sys.argv[2]); sys.exit(0 if a>b else 1)" "${j1:-0}" "${j3:-100}" \
  && { pass=$((pass+1)); echo "  ✅ 모델 판정: 좋은 1번(${j1}) > 나쁜 3번(${j3})"; } || { fail=$((fail+1)); echo "  ❌ 판정 순서 이상 1=${j1} 3=${j3}"; }
echo "== 결과: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]

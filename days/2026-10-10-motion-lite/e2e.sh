#!/usr/bin/env bash
# e2e.sh — 실제 Haiku 5.5에게 스토리보드를 받아 HTML을 만든다. `bash e2e.sh "컨셉"`
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
command -v claude >/dev/null || { echo "claude CLI 없음"; exit 1; }
concept="${1:-북마크 기반 증분 피드 읽기: 소스마다 마지막으로 본 항목을 기억하고 새 것만 보고하며, 읽기 실패는 조용함과 구분한다}"
echo "claude: $(claude --version)"
echo "컨셉: $concept"
out="$(python3 motion_lite.py "$concept" --save-json 2>&1)"; rc=$?
printf '%s\n' "$out" | sed 's/^/   | /'
pass=0; fail=0
[ "$rc" -eq 0 ] && pass=$((pass+1)) || fail=$((fail+1))
html="$(printf '%s\n' "$out" | grep -oE '/[^ ]+\.html' | head -1)"
[ -n "$html" ] && [ -s "$html" ] && { pass=$((pass+1)); echo "  ✅ HTML 생성: $html"; } || { fail=$((fail+1)); echo "  ❌ HTML 없음"; }
json="${html%.html}.json"
[ -s "$json" ] && python3 -c "import json,sys,motion_lite as M; M.validate_storyboard(json.load(open(sys.argv[1])))" "$json" && { pass=$((pass+1)); echo "  ✅ 스토리보드 JSON 재검증 통과"; } || { fail=$((fail+1)); echo "  ❌ JSON 검증 실패"; }
echo "== 결과: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]

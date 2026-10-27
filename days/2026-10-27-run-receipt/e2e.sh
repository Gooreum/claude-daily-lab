#!/usr/bin/env bash
# e2e.sh — 실제 claude CLI로 run-receipt의 프롬프트 점검이 맞는지 확인한다. `bash e2e.sh`
# 1) (로그인 불필요) `---`로 시작하는 프롬프트를 그대로 넘기면 CLI가 옵션 오류를 내는가, `--`를 붙이면 옵션 해석을 통과하는가
# 2) (로그인 필요) 모델이 실제로 파일을 쓰게 한 뒤 영수증이 통과하는가. 로그인이 없으면 건너뛴다(exit 0).
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
HERE="$(pwd)"
command -v claude >/dev/null || { echo "claude CLI 없음"; exit 1; }
echo "claude: $(claude --version)"
MODEL="${E2E_MODEL:-claude-haiku-5-5}"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
pass=0; fail=0
ok() { pass=$((pass+1)); echo "  ✅ $1"; }
ng() { fail=$((fail+1)); echo "  ❌ $1"; }

printf -- '---\nname: nightly\n---\nsay DONE\n' > "$T/p.md"
echo "== 1) 프롬프트가 '---'로 시작"
out="$(timeout 60 claude -p "$(cat "$T/p.md")" --model "$MODEL" --max-turns 3 --tools "" 2>&1 | head -3)"
echo "   | ${out//$'\n'/ ⏎ }"
[[ "$out" == *"unknown option"* ]] && ok "그대로 넘기면 CLI가 'unknown option'으로 거부" || ng "unknown option 오류가 나지 않음"
python3 -I run_receipt.py prompt "$T/p.md" >/dev/null && ng "run-receipt prompt가 문제를 못 찾음" || ok "run-receipt prompt가 같은 파일을 실패로 판정"
out2="$(timeout 60 claude -p --model "$MODEL" --max-turns 3 --tools "" -- "$(cat "$T/p.md")" 2>&1 | head -3)"
echo "   | ${out2//$'\n'/ ⏎ }"
[[ "$out2" == *"unknown option"* ]] && ng "'--'를 붙여도 옵션 오류" || ok "'--'를 붙이면 옵션 해석을 통과"

echo "== 2) 모델이 결과 파일을 쓰고 영수증 통과 (로그인 필요)"
if [[ "$out2" == *"Not logged in"* || "$out2" == *"/login"* ]]; then
  echo "  ⏭ 로그인 없음 — 2번 건너뜀"
else
  ( cd "$T" && timeout 180 claude -p --model "$MODEL" --effort low --max-turns 5 --allowedTools "Write" --output-format json -- \
      "Write a file out.csv with header 'id,name' and two data rows, then reply DONE." >/dev/null 2>&1 )
  printf '{"outputs":[{"path":"out.csv","min_data_rows":2}]}' > "$T/spec.json"
  python3 -I run_receipt.py check "$T/spec.json" && ok "모델이 쓴 out.csv가 영수증 통과" || ng "영수증 실패"
fi
echo "== 결과: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]

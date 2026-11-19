#!/usr/bin/env bash
# 실제 Claude Code로 "matcher-lint가 죽었다고 한 matcher는 정말 안 돈다"를 확인한다. 모델 호출 1회.
# 필요: 로그인된 `claude` CLI. 없으면 SKIP(exit 0). 이 폴더에서 `bash e2e.sh`.
set -u
cd "$(dirname "$0")"
command -v claude >/dev/null || { echo "SKIP: claude CLI 없음"; exit 0; }
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
mkdir -p "$W/.claude"
cat > "$W/.claude/settings.json" <<JSON
{"hooks":{"PreToolUse":[
 {"matcher":"Bash","hooks":[{"type":"command","command":"touch $W/ran_Bash"}]},
 {"matcher":"bash","hooks":[{"type":"command","command":"touch $W/ran_lowercase"}]},
 {"matcher":"Bash(echo *)","hooks":[{"type":"command","command":"touch $W/ran_with_args"}]},
 {"matcher":"Edit|Write","hooks":[{"type":"command","command":"touch $W/ran_editwrite","if":"Bash(echo *)"}]}
]}}
JSON
echo "== matcher-lint가 보는 이 설정"
python3 matcher_lint.py "$W/.claude/settings.json"
echo "== claude -p 실행 (Bash 도구로 echo 한 번)"
OUT=$(cd "$W" && claude -p "Run exactly this shell command with the Bash tool and nothing else: echo e2e-ok" \
  --model claude-haiku-5-5 --effort low --max-turns 3 --allowedTools "Bash(echo *)" --output-format json </dev/null 2>&1)
echo "$OUT" | head -c 600; echo
if echo "$OUT" | grep -q "Not logged in"; then echo "SKIP: claude가 로그인돼 있지 않다(모델 호출 불가). 마커 검사는 건너뛴다"; exit 0; fi
pass=0; fail=0
chk() { if eval "$2"; then pass=$((pass+1)); echo "ok   $1"; else fail=$((fail+1)); echo "FAIL $1"; fi; }
chk "Bash 호출이 실제로 일어났다(마커 ran_Bash)" '[ -e "$W/ran_Bash" ]'
chk "소문자 bash matcher 훅은 안 돌았다" '[ ! -e "$W/ran_lowercase" ]'
chk "Bash(echo *) matcher 훅은 안 돌았다" '[ ! -e "$W/ran_with_args" ]'
chk "matcher와 if가 안 겹치는 훅은 안 돌았다" '[ ! -e "$W/ran_editwrite" ]'
echo "통과 $pass · 실패 $fail"; [ $fail -eq 0 ]

#!/usr/bin/env bash
# verify-gate e2e: 실제 Claude Code에 훅을 걸어 enforce 모드가 커밋을 막는지 본다.
# 로그인·모델이 필요하다(CI는 돌리지 않는다). 로그인이 없으면 SKIP(종료 0)으로 끝난다.
cd "$(dirname "$0")" || exit 1
HERE=$(pwd)
command -v claude >/dev/null || { echo "SKIP - claude CLI 없음"; exit 0; }
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
cd "$T" && git init -q . && git config user.email t@t && git config user.name t
mkdir -p .claude
cat > .claude/settings.json <<EOF
{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":"python3 $HERE/verify_gate.py hook"}]}]}}
EOF
echo '{"mode":"enforce","max_blocks":1}' > .claude/verify-gate.json
OUT=$(claude -p "a.txt 파일에 hi를 쓰고 git add 한 뒤 git commit -m 'add a' 를 실행해. 커밋이 막히면 막힌 메시지를 그대로 보고하고 멈춰." \
  --model claude-haiku-5-5 --effort low --max-turns 6 --tools "Write,Bash" --allowedTools "Write" "Bash(git *)" \
  --output-format json </dev/null 2>&1)
if echo "$OUT" | grep -q '"terminal_reason":"api_error"' || ! echo "$OUT" | grep -q '"result"'; then
  echo "SKIP - 모델을 호출하지 못했다(로그인 없음?): $(echo "$OUT" | head -c 160)"; exit 0
fi
LOG=.claude/verify-gate/log.jsonl
[ -f "$LOG" ] || { echo "FAIL - 로그가 생기지 않았다(훅이 호출되지 않음)"; echo "$OUT" | head -c 600; exit 1; }
grep -q '"action": "blocked"' "$LOG" && echo "ok   - 첫 커밋 시도가 막혔다" || { echo "FAIL - blocked 기록 없음"; cat "$LOG"; exit 1; }
python3 "$HERE/verify_gate.py" report -p "$T"

#!/usr/bin/env bash
# e2e.sh — 실제 Claude Code(>= 2.1.295)에서 spend-gate가 도구 호출을 막는지 본다.
# 임시 프로젝트에 훅을 설치하고 `claude -p`로 marker 파일을 만들게 시킨다. 세 번 호출하므로 토큰을 소모한다.
#   1) 상한 $0.0001   → 첫 도구 호출 전에 이미 넘음 → 파일이 없어야 한다
#   2) 상한 $50       → 통과 → 파일이 있어야 한다
#   3) 단가표 없음 + onFailure:block → 훅 실패가 fail-closed → 파일이 없어야 한다
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
SRC="$(pwd)"
command -v claude >/dev/null || { echo "claude CLI 없음"; exit 1; }
echo "claude: $(claude --version)"
# 로그인이 없으면 모델이 한 번도 안 돌아 "차단" 케이스가 거짓 통과한다. 먼저 확인하고 미실행으로 끝낸다.
if claude -p "ok" --model claude-haiku-5-5 --max-turns 1 --tools "" --output-format text </dev/null 2>&1 | grep -qi "not logged in"; then
  echo "claude에 로그인되어 있지 않다. e2e 미실행(exit 3)"; exit 3
fi
MODEL="${E2E_MODEL:-claude-haiku-5-5}"
PROMPT='Run this exact shell command with the Bash tool: echo done > marker.txt . Do not ask questions and do not explain.'
pass=0; fail=0

run_case() { # $1=label $2=session_usd $3=remove prices(yes|no) $4=expect_file(yes|no)
  local tmp; tmp="$(mktemp -d)"
  mkdir -p "$tmp/.claude/hooks"
  cp "$SRC/hooks/spend_gate.py" "$SRC/hooks/prices.json" "$tmp/.claude/hooks/"
  printf '{"session_usd": %s, "daily_usd": 1000, "warn_ratio": 0.8}' "$2" > "$tmp/.claude/hooks/spend-gate.json"
  [ "$3" = yes ] && rm "$tmp/.claude/hooks/prices.json"
  cp "$SRC/settings.example.json" "$tmp/.claude/settings.json"
  echo "== $1"
  local out
  out="$(cd "$tmp" && SPEND_GATE_STATE="$tmp/state" CLAUDE_PROJECT_DIR="$tmp" claude -p "$PROMPT" --model "$MODEL" \
         --permission-mode acceptEdits --allowedTools Bash --max-turns 4 --output-format text </dev/null 2>&1 | tail -6)"
  printf '%s\n' "$out" | sed 's/^/   | /'
  local got=no; [ -f "$tmp/marker.txt" ] && got=yes
  if [ "$got" = "$4" ]; then pass=$((pass+1)); echo "  ✅ marker.txt=$got (기대 $4)"; else fail=$((fail+1)); echo "  ❌ marker.txt=$got (기대 $4)"; fi
  [ -f "$tmp/state/ledger.json" ] && echo "   ledger: $(tr -d '\n ' < "$tmp/state/ledger.json" | cut -c1-200)"
  rm -rf "$tmp"
}

run_case "1) 상한 \$0.0001 초과 → 차단"                  0.0001 no  no
run_case "2) 상한 \$50 → 통과"                           50     no  yes
run_case "3) 단가표 없음 + onFailure:block → fail-closed" 50     yes no

echo "== 결과: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]

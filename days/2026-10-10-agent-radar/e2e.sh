#!/usr/bin/env bash
# e2e.sh — 실제 Claude Code로 모드를 싣고, 모델이 Agent 도구로 서브에이전트를 하나 띄우게 한 뒤
# 다음 세션의 `/radar last`에 그 에이전트가 남았는지 본다 (agent.spawn·turn.complete 훅이 실제 스폰에도 도는지). `bash e2e.sh`
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
command -v claude >/dev/null || { echo "claude CLI 없음"; exit 1; }
echo "claude: $(claude --version)"
pass=0; fail=0
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
touch "$tmp/a.txt" "$tmp/b.txt" "$tmp/c.txt"
run() { (cd "$tmp" && claude -p "$1" --plugin-dir "$OLDPWD/agent-radar" --output-format text 2>&1 < /dev/null); }
stamp="radar-e2e-$$"

echo "== 1) /radar → 이 세션엔 아직 없음"
out="$(run "/radar")"; printf '%s\n' "$out" | sed 's/^/   | /'
[[ "$out" == *"No subagents yet this session."* ]] && { pass=$((pass+1)); echo "  ✅"; } || { fail=$((fail+1)); echo "  ❌"; }

echo "== 2) 모델이 Explore 서브에이전트를 띄운다 (Haiku, 실호출)"
out="$(cd "$tmp" && claude -p "Use the Agent tool exactly once: subagent_type Explore, description '$stamp', prompt 'Count the .txt files in the current directory and reply with just the number.' Then reply with only the number it returned." \
  --model claude-haiku-5-5 --plugin-dir "$OLDPWD/agent-radar" --output-format json --max-turns 6 --permission-mode acceptEdits 2>&1 < /dev/null)"
ans="$(printf '%s' "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); print(str(d.get('result','')).strip()[:40], '|', d.get('num_turns'), 'turns |', '$'+str(round(d.get('total_cost_usd',0),4)))" 2>/dev/null)"
echo "   | $ans"
[[ "$ans" == 3* ]] && { pass=$((pass+1)); echo "  ✅ 서브에이전트가 3을 셌다"; } || { fail=$((fail+1)); echo "  ❌ 답: $ans"; printf '%s\n' "$out" | head -5; }

echo "== 3) 다음 세션의 /radar last 에 그 에이전트가 남아 있다"
out="$(run "/radar last")"; printf '%s\n' "$out" | tail -3 | sed 's/^/   | /'
[[ "$out" == *"🔍 Explore · $stamp ·"* ]] && [[ "$out" == *" ✓ · "* ]] && { pass=$((pass+1)); echo "  ✅ agent.spawn·turn.complete가 실제 스폰에도 돌았다"; } || { fail=$((fail+1)); echo "  ❌ 기록 없음"; }

echo "== 4) 모드 없이 /radar → 명령 없음 (대조군)"
out="$(cd "$tmp" && claude -p "/radar" --output-format text 2>&1 < /dev/null)"; printf '%s\n' "$out" | head -2 | sed 's/^/   | /'
[[ "$out" != *"No subagents yet"* ]] && { pass=$((pass+1)); echo "  ✅"; } || { fail=$((fail+1)); echo "  ❌"; }

echo "== 결과: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]

#!/usr/bin/env bash
# 실제 Claude Code에서 AS001의 전제를 다시 확인한다 (로그인 필요, Haiku 5.5 호출 2회, 몇 센트).
# 서브에이전트 두 개(지정자 / 제한 없음)에게 "가진 도구 이름을 그대로 나열하라"고 시키고 Bash 유무를 본다.
set -u
cd "$(dirname "$0")"
command -v claude >/dev/null || { echo "SKIP: claude CLI 없음"; exit 0; }
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/.claude/agents"
mk() { cat > "$TMP/.claude/agents/$1.md" <<MD
---
name: $1
description: 도구 목록 점검용 프로브
model: haiku
$2
---
You are a probe. List ONLY the names of tools defined at the top of your prompt (the directly callable functions, not deferred ones), comma-separated. Do not call any tool.
MD
}
mk probe-spec "disallowedTools: Bash(git push *)"
mk probe-open ""

ask() {
  (cd "$TMP" && claude -p "Use the $1 subagent exactly once. Then reply with ONLY the subagent's answer, verbatim." \
    --model claude-haiku-5-5 --effort low --max-turns 4 --output-format json 2>/dev/null) \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('result','')); print('COST', d.get('total_cost_usd'), file=sys.stderr)"
}
has_bash() { echo "$1" | tr ',' '\n' | sed 's/^ *//;s/ *$//' | grep -qx 'Bash'; }

echo "claude $(claude --version 2>/dev/null)"
SPEC=$(ask probe-spec); echo "probe-spec: $SPEC"
OPEN=$(ask probe-open); echo "probe-open: $OPEN"
fail=0
if has_bash "$OPEN"; then echo "ok   대조군(제한 없음)은 Bash를 가짐"; else echo "FAIL 대조군에 Bash가 없음 — 프로브가 도구를 제대로 못 읽음"; fail=1; fi
if has_bash "$SPEC"; then echo "NOTE disallowedTools: Bash(git push *) 에이전트가 Bash를 가짐 → 이 버전에서는 AS001 전제가 바뀜"; fail=1
else echo "ok   disallowedTools: Bash(git push *) 에이전트는 Bash 전체가 없음 (AS001 전제 유지)"; fi
exit $fail

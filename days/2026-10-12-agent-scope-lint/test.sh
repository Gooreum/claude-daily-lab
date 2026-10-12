#!/usr/bin/env bash
# 키·모델 없이 도는 테스트. 이 폴더에서 `bash test.sh`.
set -u
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "ok   $1"; }
bad() { fail=$((fail+1)); echo "FAIL $1"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }

J=$($PY agent_scope_lint.py --json fixtures/bad); rc=$?
check "bad 픽스처는 exit 1" '[ $rc -eq 1 ]'
count() { echo "$J" | $PY -c "import json,sys; d=json.load(sys.stdin); print(sum(f['code']=='$1' and '$2' in f['file'] for f in d['findings']))"; }
check "AS001: pusher의 Bash(git push *) 지정자 error" '[ "$(count AS001 pusher.md)" = 1 ]'
check "AS002: pusher는 Bash가 통째로 빠지고 Agent는 남음" '[ "$(count AS002 pusher.md)" = 1 ]'
check "AS002: 블록 리스트로 Bash만 막은 no-shell" '[ "$(count AS002 no-shell.md)" = 1 ]'
check "AS003: settings deny Bash(git push *) 우회 경고" '[ "$(count AS003 settings.json)" = 1 ]'
check "AS003: git이 아닌 deny(rm -rf, Read)는 경고 없음" '[ "$(echo "$J" | grep -c "rm -rf")" = 0 ]'
check "AS004: 허용 목록 지정자 경고" '[ "$(count AS004 allowlist.md)" = 1 ]'
check "allowlist는 Bash도 Agent도 가졌으니 AS002 없음" '[ "$(count AS002 allowlist.md)" = 0 ]'
check "AS003 줄 번호가 deny 규칙 줄(5)을 가리킴" '$PY agent_scope_lint.py fixtures/bad/.claude/settings.json | grep -q "settings.json:5: warn AS003"'

$PY agent_scope_lint.py fixtures/good >/dev/null; rc=$?
check "good 픽스처는 exit 0" '[ $rc -eq 0 ]'
check "good 픽스처는 지적 0건" '$PY agent_scope_lint.py fixtures/good | grep -q "error 0 · warn 0"'

$PY agent_scope_lint.py fixtures/bad/.claude/settings.json >/dev/null; rc=$?
check "warn만 있으면 exit 0" '[ $rc -eq 0 ]'
$PY agent_scope_lint.py --strict fixtures/bad/.claude/settings.json >/dev/null; rc=$?
check "--strict면 warn도 exit 1" '[ $rc -eq 1 ]'
$PY agent_scope_lint.py no/such/path 2>/dev/null; rc=$?
check "없는 경로는 exit 2" '[ $rc -eq 2 ]'

# 파서 단위 테스트
check "split_top은 괄호 안 쉼표를 보존" "$PY -c 'import agent_scope_lint as m; assert m.split_top(\"Read, Bash(a, b), \\\"Grep\\\"\")==[\"Read\",\"Bash(a, b)\",\"Grep\"]'"
check "프론트매터 없으면 AS000" "$PY -c 'import agent_scope_lint as m; assert m.lint_agent(\"x.md\",\"hello\")[0][\"code\"]==\"AS000\"'"
check "Task(옛 이름)도 Agent로 취급" "$PY -c 'import agent_scope_lint as m; r=m.lint_agent(\"x.md\",\"---\ntools: Read, Task\n---\n\"); assert [f[\"code\"] for f in r]==[\"AS002\"], r'"
check "PowerShell 지정자도 AS001" "$PY -c 'import agent_scope_lint as m; r=m.lint_agent(\"x.md\",\"---\ndisallowedTools: PowerShell(git push *), Agent\n---\n\"); assert [f[\"code\"] for f in r]==[\"AS001\"], r'"
check "직접 지정한 .md에 프론트매터가 없으면 AS000" '$PY agent_scope_lint.py fixtures/good/.claude/agents/guides/notes.md | grep -q AS000'
check "JSON 파싱 실패는 AS000" "$PY -c 'import agent_scope_lint as m; assert m.lint_settings(\"s.json\",\"{bad\")[0][\"code\"]==\"AS000\"'"

echo "통과 $pass · 실패 $fail"
[ $fail -eq 0 ]

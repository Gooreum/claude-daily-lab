#!/usr/bin/env bash
# 키·모델 없이 도는 테스트. 이 폴더에서 `bash test.sh`.
set -u
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "ok   $1"; }
bad() { fail=$((fail+1)); echo "FAIL $1"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }

J=$($PY mcp_rule_audit.py --json fixtures/bad); rc=$?
check "bad 픽스처는 exit 1" '[ $rc -eq 1 ]'
count() { echo "$J" | $PY -c "import json,sys; d=json.load(sys.stdin); print(sum(f['code']=='$1' and '$2' in f['file'] and (not '${3:-}' or '${3:-}' in f['rule']) for f in d['findings']))"; }
check "MR001: settings allow mcp__github (github__enterprise와 겹침) error" '[ "$(count MR001 settings.json mcp__github)" -ge 1 ]'
check "MR001: allow는 error 등급" "echo \"\$J\" | $PY -c \"import json,sys; d=json.load(sys.stdin); sys.exit(0 if any(f['code']=='MR001' and f['level']=='error' and f['rule']=='mcp__db' for f in d['findings']) else 1)\""
check "MR001: ask 규칙은 warn 등급" "echo \"\$J\" | $PY -c \"import json,sys; d=json.load(sys.stdin); sys.exit(0 if any(f['code']=='MR001' and f['level']=='warn' and f['line']==14 for f in d['findings']) else 1)\""
check "MR001: 서브에이전트 tools의 mcp__github도 잡힘" '[ "$(count MR001 reviewer.md mcp__github)" = 1 ]'
check "MR001: 워크플로 --allowedTools의 mcp__db도 잡힘" '[ "$(count MR001 claude.yml mcp__db)" = 1 ]'
check "MR001: db_admin 도구 deny(mcp__db_admin__drop_table)는 지적 없음" '[ "$(echo "$J" | grep -c drop_table)" = 0 ]'
check "MR004: mcp__a__b가 서버 a / a__b 둘로 읽힘" '[ "$(count MR004 settings.json mcp__a__b)" -ge 1 ]'
check "MR004: mcp__a__b__whoami도 모호" '[ "$(count MR004 settings.json whoami)" = 1 ]'
check "MR005: 서버 이름 github__enterprise, a__b 두 건" '[ "$(count MR005 .mcp.json)" = 2 ]'
check "줄 번호가 규칙 줄을 가리킴 (settings.json:5 MR001 mcp__db)" '$PY mcp_rule_audit.py fixtures/bad | grep -q "settings.json:5: error MR001"'
check "Read 같은 비MCP 규칙은 무시" '[ "$(echo "$J" | grep -c "\"rule\": \"Read\"")" = 0 ]'

$PY mcp_rule_audit.py fixtures/good >/dev/null; rc=$?
check "good 픽스처는 exit 0" '[ $rc -eq 0 ]'
check "good 픽스처는 지적 0건" '$PY mcp_rule_audit.py fixtures/good | grep -q "error 0 · warn 0"'

$PY mcp_rule_audit.py fixtures/mr003 | grep -q "MR003"; check "MR003: 서버 x__y 하나뿐일 때 mcp__x__y는 'x의 도구 y'로 읽힘" '[ $? -eq 0 ]'
$PY mcp_rule_audit.py fixtures/mr003 >/dev/null; rc=$?
check "warn만 있으면 exit 0" '[ $rc -eq 0 ]'
$PY mcp_rule_audit.py --strict fixtures/mr003 >/dev/null; rc=$?
check "--strict면 warn도 exit 1" '[ $rc -eq 1 ]'
$PY mcp_rule_audit.py --server a_extra fixtures/good/.claude/settings.json >/dev/null; rc=$?
check "--server 추가로 파일 하나만 줘도 동작" '[ $rc -eq 0 ]'
printf '{"permissions":{"allow":["mcp__a"]}}' > /tmp/mra-single.json
$PY mcp_rule_audit.py --server a__b /tmp/mra-single.json >/dev/null; rc=$?
check "--server a__b + 규칙 mcp__a → exit 1 (겹침 error)" '[ $rc -eq 1 ]'
$PY mcp_rule_audit.py -v fixtures/good | grep -q MR002; check "-v 없이는 info 없음/있으면 MR002는 겹침 없는 맨몸 규칙" '[ $? -ne 0 ]'
$PY mcp_rule_audit.py no/such/path 2>/dev/null; rc=$?
check "없는 경로는 exit 2" '[ $rc -eq 2 ]'
mkdir -p /tmp/mra-empty && $PY mcp_rule_audit.py /tmp/mra-empty 2>/dev/null; rc=$?
check "읽을 파일이 없으면 exit 2" '[ $rc -eq 2 ]'
printf '{bad' > /tmp/mra-bad.json
$PY mcp_rule_audit.py /tmp/mra-bad.json | grep -q MR000; check "JSON 파싱 실패는 MR000" '[ $? -eq 0 ]'

# 단위 테스트
check "norm: 점·공백은 _로 치환" "$PY -c 'import mcp_rule_audit as m; assert m.norm(\"my.server x\")==\"my_server_x\"'"
check "split_list는 괄호 안 쉼표를 보존" "$PY -c 'import mcp_rule_audit as m; assert m.split_list(\"Read, Bash(a, b), mcp__x\")==[\"Read\",\"Bash(a, b)\",\"mcp__x\"]'"
check "와일드카드 규칙 mcp__a__*는 지적 없음" "$PY -c 'import mcp_rule_audit as m; r=m.analyze([(\"f\",1,\"allow\",\"mcp__a__*\")],{\"a\":[(\"f\",1)],\"a__b\":[(\"f\",1)]}); assert [x[\"code\"] for x in r]==[\"MR005\"], r'"
check "모든 도구 규칙 mcp__는 무시" "$PY -c 'import mcp_rule_audit as m; assert m.analyze([(\"f\",1,\"allow\",\"mcp__*\")],{\"a\":[(\"f\",1)]})==[]'"

echo "통과 $pass · 실패 $fail"
[ $fail -eq 0 ]

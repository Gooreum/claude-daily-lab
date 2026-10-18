#!/usr/bin/env bash
# 키·모델·claude CLI 없이 도는 테스트. 이 폴더에서 `bash test.sh`.
set -u
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "ok   $1"; }
bad() { fail=$((fail+1)); echo "FAIL $1"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
A() { $PY hook_exit_audit.py "$@" 2>&1; }

# --- 정상 훅: exit 2 + try/except
O=$(A --hook "$PY fixtures/good_exit2.py" --guard); rc=$?
check "good_exit2: exit 0" '[ $rc -eq 0 ]'
check "good_exit2: 위험 7건 모두 막음" 'echo "$O" | grep -q "위험: 7건 중 막음 7 · 종료 코드 2×7"'
check "good_exit2: 정상 4건 통과" 'echo "$O" | grep -q "정상: 4건 중 막음 0 · 종료 코드 0×4"'
check "good_exit2: 깨진 입력 4건도 exit 2" 'echo "$O" | grep -q "깨진입력: 4건 중 막음 4 · 종료 코드 2×4"'
check "good_exit2: 지적 없음" 'echo "$O" | grep -q "(지적 없음)"'

# --- exit 1 훅: 차단 문구는 찍지만 막지 못함
O=$(A --hook "$PY fixtures/bad_exit1.py" --guard); rc=$?
check "bad_exit1: exit 1 (error)" '[ $rc -eq 1 ]'
check "bad_exit1: 위험 7건 중 막음 0" 'echo "$O" | grep -q "위험: 7건 중 막음 0"'
check "bad_exit1: 동적 HE01 (차단 문구 + exit 1, 5개)" 'echo "$O" | grep -q "error HE01 .*exit 1로 끝난 입력 5개"'
check "bad_exit1: 정적 HS01 (줄 번호 포함)" 'echo "$O" | grep -q "error HS01 bad_exit1.py:8"'
check "bad_exit1: HE06 위험 입력 못 막음" 'echo "$O" | grep -q "error HE06 위험 입력 7개 중 7개"'
check "bad_exit1: 깨진 입력 HE04 warn" 'echo "$O" | grep -q "warn  HE04"'
O=$(A --hook "$PY fixtures/bad_exit1.py"); rc=$?
check "--guard 없이도 HE01은 error (의도를 몰라도 exit 1+차단 문구는 틀림)" '[ $rc -eq 1 ] && echo "$O" | grep -q "error HE01" && ! echo "$O" | grep -q HE06'

# --- 크래시로 fail-open: 위험은 막지만 깨진 입력은 트레이스백(1)
O=$(A --hook "$PY fixtures/crash_open.py" --guard); rc=$?
check "crash_open: 위험 7건은 막음" 'echo "$O" | grep -q "위험: 7건 중 막음 7"'
check "crash_open: 깨진 입력 4건 fail-open HE04" 'echo "$O" | grep -q "HE04 깨진 입력 4개가 fail-open"'
check "crash_open: 정적 HS03 (except 없음)" 'echo "$O" | grep -q "warn  HS03 crash_open.py"'
check "crash_open: warn만이라 기본 exit 0" '[ $rc -eq 0 ]'
A --hook "$PY fixtures/crash_open.py" --guard --fail-on warn >/dev/null; rc=$?
check "crash_open: --fail-on warn이면 exit 1" '[ $rc -eq 1 ]'
O=$(A --hook "$PY fixtures/crash_open.py" --guard --probes push)
check "push 세트: 우회 변형 놓침을 센다 (20개 중 8개)" 'echo "$O" | grep -q "위험 입력 20개 중 8개를 못 막음"'

# --- 출력 JSON 방식(permissionDecision deny)은 막은 것으로 센다
O=$(A --hook "$PY fixtures/json_deny.py" --guard); rc=$?
check "json_deny: exit 0 + deny JSON을 막음으로 셈" '[ $rc -eq 0 ] && echo "$O" | grep -q "위험: 7건 중 막음 7 · 종료 코드 0×7"'
check "json_deny: 깨진 입력도 deny" 'echo "$O" | grep -q "깨진입력: 4건 중 막음 4"'

# --- 셸 훅 정적 점검 (jq 의존)
O=$(A --hook "bash fixtures/jq_guard.sh" --no-run); rc=$?
check "jq_guard: HS02 jq 분기 없음 warn" 'echo "$O" | grep -q "warn  HS02 jq_guard.sh"'
check "--no-run: 훅을 실행하지 않음" 'echo "$O" | grep -q "정적 점검만" && ! echo "$O" | grep -q "위험:"'

# --- settings.json: matcher 대소문자, 없는 스크립트, 훅 종류
O=$(A fixtures/settings_bad.json --guard --cwd fixtures); rc=$?
check "settings_bad: exit 1" '[ $rc -eq 1 ]'
check "settings_bad: matcher 'bash' 대소문자 HX01" 'echo "$O" | grep -q "error HX01 matcher .bash.는 대소문자"'
check "settings_bad: matcher가 안 맞는 훅은 돌리지 않음" 'echo "$O" | grep -q "Bash에 걸리지 않아"'
check "settings_bad: 없는 스크립트 HS04" 'echo "$O" | grep -q "warn  HS04"'
check "settings_bad: 없는 python 스크립트는 exit 2라 정상 입력까지 막음(HE05)" 'echo "$O" | grep -q "error HE05 정상 입력 .ls -la."'
check "settings_bad: 훅 3개" 'echo "$O" | grep -q "훅 3개"'
O=$(A fixtures/settings_good.json --guard --cwd fixtures); rc=$?
check "settings_good: exit 0" '[ $rc -eq 0 ]'
check "settings_good: http 훅은 건너뜀" 'echo "$O" | grep -q "type=http"'
check "settings_good: Edit|Write는 Bash로 돌리지 않음" 'echo "$O" | grep -q "matcher=Edit|Write" '

# --- 입력 오류·옵션
A fixtures/nope.json >/dev/null; check "없는 파일: exit 2" '[ $? -eq 2 ]'
O=$(A fixtures/settings_good.json --cwd fixtures --json); rc=$?
check "--json: 파싱 가능한 JSON" 'echo "$O" | $PY -c "import json,sys; d=json.load(sys.stdin); assert len(d)==3"'
O=$(A --hook "$PY fixtures/good_exit2.py" --probes push --guard)
check "push 세트 20개 + 기본 아닌 것: good_exit2는 20개 중 일부 놓침" 'echo "$O" | grep -q "위험: 20건 중 막음 1[0-9]"'
EMPTY=$(mktemp -d); O=$(cd "$EMPTY" && HOME="$EMPTY" $PY "$OLDPWD/hook_exit_audit.py" 2>&1 </dev/null); rc=$?; rmdir "$EMPTY"
check "인자 없고 settings도 없으면 안내 후 exit 2" '[ $rc -eq 2 ] && echo "$O" | grep -q "settings.json이 없다"'
O=$(A --hook "sleep 5" --timeout 0.5 --guard)
check "시간 초과: HE03" 'echo "$O" | grep -q "warn  HE03"'

echo
echo "통과 $pass · 실패 $fail"
[ $fail -eq 0 ]

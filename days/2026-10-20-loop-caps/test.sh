#!/usr/bin/env bash
# 키·모델·claude CLI 없이 도는 테스트. 이 폴더에서 `bash test.sh`.
set -u
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "ok   $1"; }
bad() { fail=$((fail+1)); echo "FAIL $1"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
# run NAME SCENARIO [옵션...] : 시나리오대로 응답하는 가짜 명령을 감싸 돌린다
run() {
  local name=$1 sc=$2; shift 2
  rm -f "$T/$name.state" "$T/$name.log"
  O=$($PY loop_caps.py --log "$T/$name.log" "$@" -- $PY fixtures/flaky.py "$T/$name.state" "$sc" 2>&1); rc=$?
}
calls() { cat "$T/$1.state"; }
stopreason() { tail -1 "$T/$1.log" | $PY -c 'import json,sys; print(json.load(sys.stdin)["reason"])'; }

# --- 연속 실패 상한
run f1 fail --max-failures 3
check "연속 실패 3회: exit 4"        '[ $rc -eq 4 ]'
check "연속 실패 3회: 호출 3번에서 멈춤" '[ "$(calls f1)" = 3 ]'
check "연속 실패 3회: 로그 reason"    '[ "$(stopreason f1)" = max_failures ]'

# --- 성공이 끼면 연속 카운트가 리셋된다 (fail,fail,ok,fail,fail,ok... → 호출 상한까지 간다)
run f2 fail,fail,ok,fail,fail,ok --max-failures 3 --max-calls 6
check "성공이 끼면 리셋: exit 3 (max_calls)" '[ $rc -eq 3 ]'
check "성공이 끼면 리셋: 6번 모두 호출"      '[ "$(calls f2)" = 6 ]'

# --- 총 호출 상한
run c1 ok --max-calls 5
check "호출 상한 5: exit 3"          '[ $rc -eq 3 ]'
check "호출 상한 5: 정확히 5번"       '[ "$(calls c1)" = 5 ]'
check "호출 상한: 로그 reason"        '[ "$(stopreason c1)" = max_calls ]'
check "호출 상한: 로그에 call 5줄+stop 1줄" '[ "$(wc -l < "$T/c1.log")" = 6 ]'
check "자식 출력이 전달된다"           'echo "$O" | grep -q "^working$"'
check "요약 줄이 나온다"               'echo "$O" | grep -q "loop-caps: stop=max_calls calls=5 failures=0"'

# --- 한도/지출 소진은 즉시 멈춘다 (연속 실패 상한 전에)
run q1 ok,quota --max-failures 3
check "quota: exit 2"                '[ $rc -eq 2 ]'
check "quota: 두 번째 호출에서 즉시 멈춤" '[ "$(calls q1)" = 2 ]'
check "quota: 로그 class=quota"       'grep -q "\"class\": \"quota\"" "$T/q1.log"'
check "quota: reason=quota"          '[ "$(stopreason q1)" = quota ]'
run q2 fail --quota-regex "boom" --max-failures 5
check "--quota-regex로 기준을 바꾼다"   '[ $rc -eq 2 ] && [ "$(calls q2)" = 1 ]'

# --- 종료 코드 0인 is_error JSON도 실패다 (claude -p --output-format json)
run j1 errjson --max-failures 2
check "is_error JSON: 실패로 센다 (exit 4)" '[ $rc -eq 4 ] && [ "$(calls j1)" = 2 ]'

# --- 정상 종료 조건
run s1 ok --stop-on-success
check "--stop-on-success: exit 0, 1번"  '[ $rc -eq 0 ] && [ "$(calls s1)" = 1 ] && [ "$(stopreason s1)" = done ]'
run d1 ok,ok,done --done-regex TASK_COMPLETE
check "--done-regex: 3번째에 done (exit 0)" '[ $rc -eq 0 ] && [ "$(calls d1)" = 3 ] && [ "$(stopreason d1)" = done ]'
touch "$T/STOP"
run st1 ok --stop-file "$T/STOP"
check "--stop-file: 한 번도 안 돌고 exit 0" '[ $rc -eq 0 ] && [ ! -e "$T/st1.state" ] && [ "$(stopreason st1)" = stop_file ]'

# --- 시간 상한: 호출당 제한과 경과 시간
run t1 slow --call-timeout 0.3 --max-failures 2
check "호출 타임아웃: 실패 2회로 exit 4"  '[ $rc -eq 4 ] && grep -q "\"class\": \"timeout\"" "$T/t1.log"'
run h1 ok --max-hours 0.00008 --interval 0.1
check "경과 상한: exit 3, reason=max_hours" '[ $rc -eq 3 ] && [ "$(stopreason h1)" = max_hours ]'

# --- 사용법 오류와 dry-run
$PY loop_caps.py --max-calls 5 echo hi >/dev/null 2>&1;  rc=$?
check "-- 없으면 exit 1"                '[ $rc -eq 1 ]'
$PY loop_caps.py --max-calls 0 -- echo hi >/dev/null 2>&1; rc=$?
check "상한 0은 거부(끌 수 없다) exit 1"   '[ $rc -eq 1 ]'
$PY loop_caps.py --max-hours -1 -- echo hi >/dev/null 2>&1; rc=$?
check "음수 상한도 거부 exit 1"           '[ $rc -eq 1 ]'
$PY loop_caps.py -- >/dev/null 2>&1; rc=$?
check "명령 없으면 exit 1"               '[ $rc -eq 1 ]'
O=$($PY loop_caps.py --dry-run --log "$T/dry.log" -- touch "$T/should-not-exist" 2>&1); rc=$?
check "--dry-run: 명령을 실행하지 않는다"   '[ $rc -eq 0 ] && [ ! -e "$T/should-not-exist" ] && [ ! -e "$T/dry.log" ]'
check "--dry-run: 기본 상한 3·200·3시간 출력" 'echo "$O" | grep -q "연속 실패 3회 · 총 호출 200회 · 경과 3.0시간"'
$PY loop_caps.py -- /nonexistent/cmd-xyz >/dev/null 2>&1; rc=$?
check "없는 명령도 실패로 세고 멈춘다 (exit 4)" '[ $rc -eq 4 ]'

echo "---"; echo "통과 $pass · 실패 $fail"
[ $fail -eq 0 ]

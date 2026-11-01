#!/usr/bin/env bash
# 키·모델 없이 도는 테스트. 이 폴더에서 `bash test.sh`.
set -u
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "ok   $1"; }
bad() { fail=$((fail+1)); echo "FAIL $1"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
probe() { $PY mcp_probe.py --timeout 2 "$@"; }

# 정상 서버
OUT=$(probe -- $PY fixtures/good_server.py); rc=$?
check "good: exit 0" '[ $rc -eq 0 ]'
check "good: 지적 0건 (검사 12개)" 'echo "$OUT" | grep -q "검사 12개 · error 0 · warn 0"'
if command -v node >/dev/null 2>&1; then
  OUT=$(probe -- node fixtures/good_server.js); rc=$?
  check "node good: exit 0, 지적 0건 (도구에 required 없으면 P08 건너뜀 → 11개)" '[ $rc -eq 0 ] && echo "$OUT" | grep -q "검사 11개 · error 0 · warn 0"'
else
  echo "skip node 픽스처 (node 없음)"
fi

# 나쁜 서버: 코드마다 하나씩
OUT=$(probe -- $PY fixtures/bad_server.py); rc=$?
check "bad: exit 1" '[ $rc -eq 1 ]'
has() { echo "$OUT" | grep -q "$1"; }
check "P01 capabilities·serverInfo 누락"          'has "error P01: .*capabilities, serverInfo"'
check "P02 stdout 오염 (시작 메시지 줄)"          'has "error P02: .*bad_server 시작"'
check "P03 알림에 응답"                           'has "error P03: 알림에 응답"'
check "P04 ping 결과가 빈 객체 아님 (warn)"        'has "warn  P04"'
check "P05 inputSchema.type 틀림"                  'has "error P05: 도구 echo: inputSchema"'
check "P05 name 없는 도구"                         'has "error P05: name이 없는"'
check "P06 모르는 메서드에 성공 응답"              'has "error P06"'
check "P07 모르는 도구를 isError로 (warn)"         'has "warn  P07"'
check "P08 필수 인자 없이 성공"                    'has "error P08"'
check "P12 stdin 닫아도 종료 안 함 (warn)"         'has "warn  P12"'
check "bad: 요약이 error 7 · warn 3"               'has "error 7 · warn 3"'

# 개별 결함 서버
OUT=$(probe -- $PY fixtures/crash_server.py); rc=$?
check "crash: P11 (깨진 JSON에 죽음) exit 1" '[ $rc -eq 1 ] && has "error P11"'
OUT=$(probe -- $PY fixtures/silent_server.py); rc=$?
check "silent: P01 시간 초과 exit 1, 검사 1개에서 중단" '[ $rc -eq 1 ] && has "error P01: initialize에 2초" && has "검사 1개"'
OUT=$(probe -- $PY fixtures/strid_server.py); rc=$?
check "strid: P10 id 타입 불일치" '[ $rc -eq 1 ] && has "error P10"'
OUT=$(probe -- $PY fixtures/no_such_file.py 2>/dev/null); rc=$?
check "없는 스크립트: P01 error로 끝남 (예외 없음)" '[ $rc -eq 1 ] && has "error P01"'
OUT=$(probe -- /nonexistent/binary-xyz); rc=$?
check "없는 실행 파일: P00 error, exit 1" '[ $rc -eq 1 ] && has "error P00"'

# 옵션
OUT=$(probe --strict -- $PY fixtures/good_server.py); rc=$?
check "--strict: 정상 서버는 여전히 exit 0" '[ $rc -eq 0 ]'
OUT=$(probe --json -- $PY fixtures/bad_server.py)
check "--json: 파싱되고 errors=7, warnings=3" 'echo "$OUT" | $PY -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if (d[\"errors\"],d[\"warnings\"])==(7,3) and d[\"findings\"][0][\"code\"] else 1)"'
OUT=$($PY mcp_probe.py --list)
check "--list: 검사 12개 나열" '[ "$(echo "$OUT" | wc -l)" -eq 12 ]'
$PY mcp_probe.py >/dev/null 2>&1; rc=$?
check "명령 없이 실행하면 exit 2" '[ $rc -eq 2 ]'

echo
echo "통과 $pass · 실패 $fail"
[ $fail -eq 0 ]

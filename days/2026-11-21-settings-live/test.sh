#!/usr/bin/env bash
# 키·모델 없이 도는 테스트. 이 폴더에서 `bash test.sh`.
set -u
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "ok   $1"; }
bad() { fail=$((fail+1)); echo "FAIL $1"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
sl() { $PY settings_live.py "$@"; }
has() { echo "$OUT" | grep -q -- "$1"; }
export HOME=/nonexistent-home   # $HOME 확장 테스트가 실제 홈에 기대지 않게

# 모범 설정: 지적 0건, 담당 목록 출력
OUT=$(sl fixtures/good.json --root fixtures); rc=$?
check "good: exit 0" '[ $rc -eq 0 ]'
check "good: error 0 · warn 0 · info 0" 'has "error 0 · warn 0 · info 0"'
check "good: deny 2 · 훅 3 담당 표시" 'has "deny 2 · ask 1 · allow 2 · 훅 3"'

# JSON 깨짐: 위치·원인 힌트, 고치면 살아날 것
OUT=$(sl fixtures/trailing_comma.json); rc=$?
check "SL01 후행 쉼표: exit 1" '[ $rc -eq 1 ]'
check "SL01 후행 쉼표: 3행과 원인" 'has "SL01 3행" && has "마지막 항목 뒤에 쉼표"'
check "SL01 후행 쉼표: 고치면 살아날 deny 2 · 훅 1" 'has "고치면 살아날 것: deny 2 · ask 1 · allow 0 · 훅 1"'
check "SL01 후행 쉼표: 꺼진 채 시작 경고" 'has "deny 2개·훅 1개가 적용되지 않은 채"'
OUT=$(sl fixtures/comments.json); rc=$?
check "SL01 주석: 원인을 주석으로 짚음" '[ $rc -eq 1 ] && has "주석(// 또는 /\* \*/)이 있다"'
OUT=$(sl fixtures/empty.json); rc=$?
check "SL01 빈 파일: error" '[ $rc -eq 1 ] && has "빈 파일이다"'
OUT=$(sl fixtures/array_top.json); rc=$?
check "SL02 최상위가 배열: error" '[ $rc -eq 1 ] && has "SL02" && has "지금 list"'

# 중복 키: 앞 내용이 사라진다, 사라지는 deny 개수까지
OUT=$(sl fixtures/dup_keys.json); rc=$?
check "SL09 중복 키: warn이라 exit 0" '[ $rc -eq 0 ] && has "warn  SL09"'
check "SL09 중복 키: 사라지는 deny 2" 'has "사라지는 쪽에 든 것: deny 2"'
OUT=$(sl --strict fixtures/dup_keys.json); rc=$?
check "--strict: warn도 exit 1" '[ $rc -eq 1 ]'

# 모양 어긋남
OUT=$(sl fixtures/bad_shapes.json); rc=$?
check "bad_shapes: exit 1" '[ $rc -eq 1 ]'
check "SL03 deny가 문자열" 'has "permissions.deny는 문자열 배열이어야 한다(지금 str)"'
check "SL03 빈 규칙·숫자 규칙" 'has "allow\[1\]" && has "(지금 7)"'
check "SL10 괄호 짝 안 맞음 (warn)" 'has "warn  SL10 permissions.allow\[0\]"'
check "SL03 defaultMode 모름 (warn)" 'has "defaultMode — .yolo."'
check "SL03 이벤트 값이 객체" 'has "이벤트 값은 그룹 배열이어야 한다(지금 dict)"'
check "SL03 그룹에 hooks 배열 없음" 'has "그룹에 \"hooks\" 배열이 없다"'
check "SL03 command 핸들러에 command 없음" 'has "type \"command\" 핸들러에는 문자열 \"command\"가 필요하다"'
check "SL03 알 수 없는 핸들러 type (warn)" 'has "type .cmd.는 알려진 핸들러 종류"'
check "SL03 timeout 문자열 (warn)" 'has "timeout은 숫자여야 한다(지금 .5.)"'
check "SL03 env 값이 숫자 (warn)" 'has "env.RETRIES"'
check "SL03 enabledPlugins 가 배열" 'has "enabledPlugins는 {플러그인: true|false} 객체여야 한다(지금 list)"'
check "SL03 model 이 숫자" 'has "model은 문자열이어야 한다(지금 int)"'
check "요약: error 8 · warn 5" 'has "error 8 · warn 5"'

# 오타: 가까운 이름만 warn, 모르는 이름은 info
OUT=$(sl fixtures/typos.json); rc=$?
check "typos: warn·info만이라 exit 0" '[ $rc -eq 0 ]'
check "SL04 permisions → permissions" 'has "\"permissions\"? 오타면 이 값은 적용되지 않는다"'
check "SL04 permissions.denny → deny" 'has "\"deny\"? 오타면 규칙이 적용되지 않는다"'
check "SL04 모르는 키는 info" 'has "info  SL04 futureKeyNobodyKnows"'
check "SL04 enviroment 는 가까운 키가 없어 info" 'has "info  SL04 enviroment"'
check "SL05 pretooluse → PreToolUse" 'has "\"PreToolUse\"? 이름은 대소문자를 구분하므로"'
check "SL05 모르는 이벤트는 info" 'has "info  SL05 hooks.MyEvent"'
check "요약: error 0 · warn 3 · info 3" 'has "error 0 · warn 3 · info 3"'

# 없는 훅 스크립트: 변수 확장·인터프리터 건너뛰기, 있는 파일은 통과
OUT=$(sl fixtures/missing_script.json --root fixtures); rc=$?
check "SL06 \$CLAUDE_PROJECT_DIR/hooks/nope.sh 없음" 'has "SL06" && has "fixtures/hooks/nope.sh 가 없다"'
check "SL06 exit 127은 막지 못한다고 설명" 'has "127은 호출을 막지 못한다"'
check "SL06 \$HOME 확장 경로도 검사" 'has "/nonexistent-home/.local/bin/whatever 가 없다"'
check "SL06 있는 ./hooks/guard.sh 는 지적 안 함" '! has "guard.sh 가 없다"'
check "SL06 요약: warn 2" 'has "error 0 · warn 2"'

# BOM
OUT=$(sl fixtures/bom.json); rc=$?
check "SL07 BOM: warn, 내용은 읽힘" '[ $rc -eq 0 ] && has "SL07" && has "BOM"'

# 자동 탐색: 홈 + 프로젝트 settings.json + settings.local.json
OUT=$(sl --root fixtures/tree/proj --home fixtures/tree/home); rc=$?
check "탐색: 파일 3개" 'has "파일 3개"'
check "탐색: settings.local.json 만 error" '[ $rc -eq 1 ] && has "settings.local.json" && has "error 1 · warn 0"'
OUT=$(sl --root fixtures/tree/empty --home fixtures/tree/empty); rc=$?
check "탐색: 파일이 없으면 안내하고 exit 0" '[ $rc -eq 0 ] && has "점검할 설정 파일이 없다"'

# SDK query()의 settings 문자열
OUT=$(sl --string '{"permissions": {"deny": ["Read(./.env)"],}}'); rc=$?
check "--string: 깨진 문자열은 exit 1 + query() 오류 안내" '[ $rc -eq 1 ] && has "query()가 오류로 끝난다"'
check "--string: 세션 시작 문구는 붙이지 않음" '! has "세션이 시작된다"'
OUT=$(sl --string '{"permissions": {"deny": ["Read(./.env)"]}}'); rc=$?
check "--string: 정상 문자열은 exit 0" '[ $rc -eq 0 ]'

# --json
OUT=$(sl --json fixtures/trailing_comma.json); rc=$?
check "--json: 올바른 JSON이고 rule SL01" 'echo "$OUT" | $PY -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d[0][\"findings\"][0][\"rule\"]==\"SL01\" and d[0][\"stake\"][\"deny\"]==2 else 1)"'

# 없는 파일
OUT=$(sl fixtures/does-not-exist.json); rc=$?
check "없는 파일: error 읽을 수 없다" '[ $rc -eq 1 ] && has "읽을 수 없다"'

echo
echo "통과 $pass · 실패 $fail"
[ $fail -eq 0 ]

#!/usr/bin/env bash
# 키·모델 없이 도는 테스트. 이 폴더에서 `bash test.sh`.
set -u
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "ok   $1"; }
bad() { fail=$((fail+1)); echo "FAIL $1"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
hm() { $PY hook_manners.py "$@"; }

# 모범 훅: 지적 0건
OUT=$(hm fixtures/settings_good.json); rc=$?
check "good: exit 0" '[ $rc -eq 0 ]'
check "good: 훅 3개 error 0 warn 0" 'echo "$OUT" | grep -q "훅 3개 · error 0 · warn 0"'
check "good: PreToolUse 가드는 점검 제외로 표시" 'echo "$OUT" | grep -q "가드(점검 제외)"'
check "good: Stop 훅이 비활성일 때는 막음(정상 동작)으로 보고" 'echo "$OUT" | grep -q "비활성 때 막음"'

# 나쁜 훅: 코드마다 하나씩
OUT=$(hm --timeout 2 fixtures/settings_bad.json); rc=$?
has() { echo "$OUT" | grep -q "$1"; }
check "bad: exit 1" '[ $rc -eq 1 ]'
check "HM06 stop_hook_active=true인데 또 막음 (loop_stop)" 'has "error HM06: stop_hook_active=true인데 또 막는다"'
check "HM02 깨진 입력에서 exit 1 (crash_hook)" 'has "error HM02: .*깨진 JSON→exit 1"'
check "HM02 깨진 입력에서 exit 2 (exit2_hook)" 'has "error HM02: .*빈 입력→exit 2"'
check "HM05 데드라인 없이 멈춤 (slow_hook)" 'has "error HM05: 깨진 입력에서 2.0초"'
check "HM01 timeout 없음 / 120초" 'has "warn  HM01: 설정에 timeout이 없다" && has "warn  HM01: timeout 120초"'
check "HM03 깨진 입력에서 stdout 출력 (loop_stop)" 'has "warn  HM03"'
check "HM04 stdout이 JSON 아닌 글자 (crash_hook)" 'has "warn  HM04: stdout이 JSON이 아닌 글자다"'
check "http 훅은 건너뜀 (훅 4개)" 'has "훅 4개 · error 5 · warn 5"'

# 정적 점검만
OUT=$(hm --no-run --event Stop --hook "python3 fixtures/loop_stop.py"); rc=$?
check "HM07 block을 내면서 stop_hook_active를 안 읽음 (--no-run은 warn만 → exit 0)" 'has "warn  HM07" && [ $rc -eq 0 ]'
OUT=$(hm --no-run --hook "python3 fixtures/loop_stop.py" --fail-on warn); rc=$?
check "--fail-on warn이면 exit 1" '[ $rc -eq 1 ]'
OUT=$(hm --no-run --hook "python3 fixtures/good_stop.py"); rc=$?
check "good_stop은 stop_hook_active를 읽으므로 HM07 없음" '! has "HM07"'
OUT=$(hm --event PostToolUse --hook "python3 fixtures/no_such_file.py"); rc=$?
check "HM08 없는 스크립트 (+깨진 입력 exit 2)" 'has "warn  HM08: 스크립트 파일이 없다: fixtures/no_such_file.py" && has "error HM02" && [ $rc -eq 1 ]'

OUT=$(hm --no-run --hook "./fixtures/no_such.sh"); rc=$?
check "HM08 직접 실행하는 없는 스크립트는 exit 127 안내" 'has "HM08: 스크립트 파일이 없다: ./fixtures/no_such.sh — 셸이 exit 127"'

# 가드 이벤트는 깨진 입력으로 점검하지 않는다
OUT=$(hm --event PreToolUse --hook "python3 fixtures/crash_hook.py" --no-run); rc=$?
check "PreToolUse 훅은 HM02를 내지 않는다" '! has "HM02"'

# JSON 출력과 입력 오류
OUT=$(hm --json fixtures/settings_good.json) 
check "--json이 유효한 JSON 배열" 'echo "$OUT" | $PY -c "import json,sys; d=json.load(sys.stdin); assert isinstance(d,list) and len(d)==3"'
OUT=$(HOME=/nonexistent $PY hook_manners.py --cwd /tmp 2>&1 </dev/null); rc=$?
check "settings가 없으면 exit 2" '[ $rc -eq 2 ]'
echo '{"hooks": {"Stop": []}}' > /tmp/hm_empty.json
OUT=$(hm /tmp/hm_empty.json); rc=$?
check "훅이 없으면 exit 0" '[ $rc -eq 0 ] && has "command 훅이 없다"'
rm -f /tmp/hm_empty.json

echo; echo "통과 $pass · 실패 $fail"
[ $fail -eq 0 ]

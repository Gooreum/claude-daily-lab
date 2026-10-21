#!/usr/bin/env bash
# 키·모델 없이 도는 테스트. 이 폴더에서 `bash test.sh`.
set -u
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "ok   $1"; }
bad() { fail=$((fail+1)); echo "FAIL $1"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
jq_() { $PY -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

# --- lint
O=$($PY home_canary.py lint fixtures/bad_wipe.sh); rc=$?
check "lint: 가드 없는 rm -rf → exit 1"        '[ $rc -eq 1 ]'
check "lint: unguarded-rm 2건"                 '[ "$(echo "$O" | grep -c unguarded-rm)" = 2 ]'
O=$($PY home_canary.py lint fixtures/good_wipe.sh); rc=$?
check "lint: 가드 있는 스크립트 → exit 0"       '[ $rc -eq 0 ]'
O=$($PY home_canary.py lint fixtures); rc=$?
check "lint: 진짜 HOME을 넘기는 테스트를 지적"    'echo "$O" | grep -q "test_bad.sh:3: \[real-path-to-destructive\]"'
check "lint: 임시 폴더 없는 테스트를 지적"        'echo "$O" | grep -q "test_notmp.sh:3: \[no-tmpdir\]"'
check "lint: mktemp 쓰는 테스트는 지적 안 함"      '! echo "$O" | grep -q test_good.sh'
check "lint: 가드 있는 스크립트는 지적 안 함"      '! echo "$O" | grep -q good_wipe.sh'
check "lint: 주석 속 rm -rf는 무시"             '[ "$($PY home_canary.py lint fixtures/commented.sh >/dev/null; echo $?)" = 0 ]'
N=$($PY home_canary.py lint fixtures --json | jq_ 'len(d["findings"])')
check "lint --json: 지적 5건(픽스처 noext 포함)"  '[ "$N" = 5 ]'
check "lint: 폴더 재귀로 8개 파일 검사"          'echo "$O" | grep -q "검사 8개 파일"'
check "lint: 확장자 없는 #!/bin/bash도 검사"     '[ "$($PY home_canary.py lint fixtures/noext >/dev/null; echo $?)" = 1 ]'

O=$($PY home_canary.py lint fixtures/idioms.sh); rc=$?
check "lint: mktemp 변수·/tmp/x.\$\$·trap·문자열 속 rm은 오탐 아님" '[ $rc -eq 0 ]'

# --- run: 위험한 스크립트에 진짜 HOME($HOME)을 넘기는 테스트를 가짜 HOME에서 돌린다
O=$($PY home_canary.py run --json -- bash fixtures/test_bad.sh); rc=$?
check "run: 사고 재현 → exit 3"                '[ $rc -eq 3 ]'
D=$(echo "$O" | jq_ 'len(d["damage"])')
check "run: 미끼 5개 중 훼손이 보고됨"           '[ "$D" -ge 4 ]'
check "run: .git/HEAD 삭제도 잡음"              'echo "$O" | grep -q "work/project/.git/HEAD"'
check "run: 진짜 HOME은 무사"                  '[ -d "$HOME" ] && [ "$(echo "$O" | jq_ "d[\"fake_home\"] != \"$HOME\"")" = True ]'
check "run: 끝나면 임시 폴더 정리"               '[ ! -e "$(echo "$O" | jq_ "d[\"fake_home\"]")" ]'

O=$($PY home_canary.py run -- bash -c 'bash fixtures/good_wipe.sh "$HOME"'); rc=$?
check "run: 가드 있는 스크립트에 HOME → 미끼 무사, rc 2" '[ $rc -eq 2 ] && echo "$O" | grep -q "모두 무사"'
O=$($PY home_canary.py run -- bash fixtures/test_good.sh); rc=$?
check "run: mktemp 쓰는 안전한 테스트 → exit 0"  '[ $rc -eq 0 ] && echo "$O" | grep -q "모두 무사"'
O=$($PY home_canary.py run -- bash -c 'echo hi > "$HOME/Documents/notes.txt"'); rc=$?
check "run: 내용 수정도 잡음(modified)"          '[ $rc -eq 3 ] && echo "$O" | grep -q "modified: ~/Documents/notes.txt"'
O=$($PY home_canary.py run -- bash -c 'exit 7'); rc=$?
check "run: 훼손 없으면 명령 종료 코드 그대로(7)"   '[ $rc -eq 7 ]'
O=$($PY home_canary.py run -- no-such-command-xyz); rc=$?
check "run: 없는 명령 → 127"                   '[ $rc -eq 127 ]'
O=$($PY home_canary.py run); rc=$?
check "run: 명령 없으면 exit 2"                '[ $rc -eq 2 ]'
O=$($PY home_canary.py run --dry-run --json -- bash fixtures/test_bad.sh); rc=$?
check "run --dry-run: 실행 안 하고 exit 0"      '[ $rc -eq 0 ] && [ "$(echo "$O" | jq_ "d[\"dry_run\"]")" = True ]'
check "run --dry-run: 가짜 HOME 경로·미끼 목록을 보여줌" '[ "$(echo "$O" | jq_ "len(d[\"canaries\"])")" = 5 ]'
O=$($PY home_canary.py run --keep --json -- true); H=$(echo "$O" | jq_ 'd["fake_home"]')
check "run --keep: 임시 폴더를 남김"            '[ -d "$H" ]'
rm -rf "$(dirname "$H")"

echo "---"; echo "통과 $pass · 실패 $fail"
[ $fail -eq 0 ]

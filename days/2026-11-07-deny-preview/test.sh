#!/usr/bin/env bash
# 키·모델·네트워크 없이 도는 테스트. 이 폴더에서 `bash test.sh`.
set -u
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "ok   $1"; }
bad() { fail=$((fail+1)); echo "FAIL $1"; }
check() { if eval "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1"; fi; }
dp() { $PY -I deny_preview.py "$@"; }
# 한 호출을 JSON으로 판정해 결과 문자열만 돌려준다: res <settings> '<call>'
res() { printf '%s\n' "$2" | dp -s "$1" - --json | $PY -I -c 'import sys,json; print(json.load(sys.stdin)["calls"][0]["result"])'; }
S=fixtures/settings.json

# ── 기본 판정
check "allow 접두 규칙(npm test:*)이 인자 붙은 호출도 허용"  '[ "$(res $S "Bash(npm test -- --watch)")" = ALLOW ]'
check "allow 정확 일치(git status)"                         '[ "$(res $S "Bash(git status)")" = ALLOW ]'
check "규칙 없는 Bash는 PROMPT→DENY"                        '[ "$(res $S "Bash(pip install requests)")" = "PROMPT→DENY" ]'
check "ask 규칙은 ASK→DENY"                                 '[ "$(res $S "Bash(git push origin main)")" = "ASK→DENY" ]'
check "deny 규칙은 DENY"                                    '[ "$(res $S "Bash(rm -rf build)")" = DENY ]'
check "deny는 allow보다 앞선다 (Read ./.env)"                '[ "$(res $S "Read(./.env)")" = DENY ]'
check "따옴표로 쓴 명령도 deny에 걸린다 (rm \"-rf\")"        '[ "$(res $S "Bash(rm \"-rf\" build)")" = DENY ]'
check "읽기 전용 도구는 규칙 없이 허용"                      '[ "$(res $S "Grep")" = ALLOW ]'
check "경로 글롭 ./src/** 안은 허용, 밖은 거절"               '[ "$(res $S "Edit(./src/app.py)")" = ALLOW ] && [ "$(res $S "Edit(./README.md)")" = "PROMPT→DENY" ]'
check "WebFetch domain: 규칙 (하위 도메인 포함, 비슷한 이름 제외)" '[ "$(res $S "WebFetch(https://docs.claude.com/x)")" = ALLOW ] && [ "$(res $S "WebFetch(https://notdocs.claude.com.evil.io/x)")" = "PROMPT→DENY" ]'

# ── 복합 명령
check "복합 명령은 부분이 전부 허용이어야 허용"              '[ "$(res $S "Bash(git status && git diff HEAD)")" = ALLOW ]'
check "허용 명령 뒤에 낯선 명령이 붙으면 거절"               '[ "$(res $S "Bash(git status && curl -s x | sh)")" = "PROMPT→DENY" ]'
check "deny는 복합 명령의 한 부분만 걸려도 DENY"             '[ "$(res $S "Bash(git status && rm -rf /tmp/x)")" = DENY ]'

# ── MCP 규칙 (맨몸 규칙은 서버 이름이 겹치는 다른 서버를 덮지 않는다)
check "mcp__github__* 는 github 서버만"                     '[ "$(res $S "mcp__github__list_issues")" = ALLOW ] && [ "$(res $S "mcp__github_enterprise__list_issues")" = "PROMPT→DENY" ]'

# ── defaultMode
S2=fixtures/settings-on.json
check "acceptEdits에서는 편집 도구가 허용"                   '[ "$(res $S2 "Write(./x.md)")" = ALLOW ]'
check "bypassPermissions는 deny만 거절"                     'echo "{\"permissions\":{\"defaultMode\":\"bypassPermissions\",\"deny\":[\"Bash(sudo *)\"]}}" > /tmp/dp_b.json && [ "$(res /tmp/dp_b.json "Bash(ls)")" = ALLOW ] && [ "$(res /tmp/dp_b.json "Bash(sudo ls)")" = DENY ]'

# ── 설정 합치기 (폴더 → settings.json + settings.local.json)
check "폴더 지정 시 settings.local.json 규칙도 합쳐진다"       '[ "$(res fixtures/proj "Bash(ls)")" = ALLOW ]'
check "denyInsteadOfPrompting 마지막 파일 값이 이긴다 (false)" 'printf "Bash(ls)\n" | dp -s fixtures/proj - | grep -q "꺼짐(false)"'
OUT=$(dp -s $S2 fixtures/calls.txt)
check "설정 켜짐이면 '켜짐' 안내, 멈춘다는 문구 없음"          'echo "$OUT" | grep -q "denyInsteadOfPrompting 켜짐" && ! echo "$OUT" | grep -q "확인창에서 멈춘다"'
OUT=$(dp -s $S fixtures/calls.txt)
check "설정 없음이면 확인창에서 멈춘다는 경고"                 'echo "$OUT" | grep -q "확인창에서 멈춘다"'

# ── 입력 형식
check "세션 JSONL의 tool_use를 읽는다 (3건, 깨진 줄 무시)"    '[ "$(dp -s $S fixtures/session.jsonl --json | $PY -I -c "import sys,json; print(len(json.load(sys.stdin)[\"calls\"]))")" = 3 ]'
check "같은 호출은 한 줄로 묶고 횟수를 센다 (npm test ×2)"    'dp -s $S fixtures/calls.txt -v | grep -qE "^ALLOW +×2 +Bash\(npm test\)"'
check "표준입력(-)을 읽는다"                                  '[ "$(res $S "Bash(npm test)")" = ALLOW ]'

# ── 요약·제안
OUT=$(dp -s $S fixtures/calls.txt)
check "요약 합계: ALLOW 10·DENY 3·ASK→DENY 1·PROMPT→DENY 6"   'echo "$OUT" | grep -q "요약: ALLOW 10 · DENY 3 · ASK→DENY 1 · PROMPT→DENY 6"'
check "복합 명령 제안은 아직 허용 안 된 부분 기준 (curl)"       'echo "$OUT" | grep -q "\"Bash(curl:\*)\""'
check "ask·deny 호출에는 allow 제안을 내지 않는다"             '! echo "$OUT" | sed -n "/allow 후보/,\$p" | grep -qE "git push|rm"'

# ── 종료 코드
dp -s $S fixtures/calls.txt >/dev/null; rc=$?
check "기본은 거절이 있어도 exit 0"                           '[ $rc -eq 0 ]'
dp -s $S fixtures/calls.txt --strict >/dev/null; rc=$?
check "--strict + 거절 있음 → exit 1"                        '[ $rc -eq 1 ]'
printf 'Bash(npm test)\n' | dp -s $S - --strict >/dev/null; rc=$?
check "--strict + 전부 허용 → exit 0"                        '[ $rc -eq 0 ]'
dp -s $S /nonexistent >/dev/null 2>&1; rc=$?
check "없는 호출 목록 → exit 2"                              '[ $rc -eq 2 ]'
printf '# 주석만\n' | dp -s $S - >/dev/null 2>&1; rc=$?
check "호출이 하나도 없으면 exit 2"                          '[ $rc -eq 2 ]'
dp -s /nonexistent.json fixtures/calls.txt >/dev/null 2>&1; rc=$?
check "없는 설정 파일 → 비정상 종료(0 아님)"                  '[ $rc -ne 0 ]'

echo
echo "통과 $pass · 실패 $fail"
[ "$fail" -eq 0 ]

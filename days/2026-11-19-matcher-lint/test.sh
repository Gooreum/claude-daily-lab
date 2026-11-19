#!/usr/bin/env bash
# 키·모델 없이 도는 테스트. 이 폴더에서 `bash test.sh`.
set -u
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "ok   $1"; }
bad() { fail=$((fail+1)); echo "FAIL $1"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
ml() { $PY matcher_lint.py "$@"; }

# 모범 설정: 지적 0건
OUT=$(ml fixtures/good.json); rc=$?
check "good: exit 0" '[ $rc -eq 0 ]'
check "good: 그룹 11개 · error 0 · warn 0" 'echo "$OUT" | grep -q "matcher 그룹 11개 · error 0 · warn 0"'

# 나쁜 설정: 규칙마다 하나씩
OUT=$(ml fixtures/bad.json); rc=$?
has() { echo "$OUT" | grep -q -- "$1"; }
check "bad: exit 1" '[ $rc -eq 1 ]'
check "ML01 대소문자 bash → Bash" 'has "\"bash\"는 도구 이름과 정확히 일치하지 않는다 — 대소문자를 구분한다. \"Bash\""'
check "ML01 Write|edit 의 edit" 'has "\"edit\"는 도구 이름과 정확히 일치하지 않는다"'
check "ML01 mcp__memory 는 정확 일치라 안 맞음" 'has "\"mcp__memory\"는 정확 일치로만 비교돼"'
check "ML04 Bash(git commit*) 는 if로" 'has "인자 조건은 핸들러의 if에 쓴다"'
check "ML02 *.ts 는 정규식이 아님" 'has "정규식으로 해석되지 않는다"'
check "ML02 어떤 도구에도 안 맞는 정규식" 'has "알려진 어떤 도구 이름에도 맞지 않는다"'
check "ML07 matcher와 if의 도구가 겹치지 않음" 'has "한 번도 실행되지 않는다"'
check "ML07 if 안의 도구 이름 대소문자" 'has "if \"bash(git \*)\"의 도구 이름"'
check "ML00 matcher가 배열" 'has "matcher는 문자열이어야 한다(지금 list)"'
check "ML06 Edit.* 는 NotebookEdit도 맞음 (warn)" 'has "warn  ML06" && has "NotebookEdit도 맞는다"'
check "ML01 Task·MultiEdit 는 옛 이름 (warn)" 'has "\"Task\"는 지금 도구 목록에 없다" && has "\"MultiEdit\"는 지금 도구 목록에 없다"'
check "ML03 UserPromptSubmit matcher는 무시됨 (warn)" 'has "UserPromptSubmit는 matcher를 지원하지 않아"'
check "ML05 SessionStart Startup 대소문자 (warn)" 'has "\"startup\"?"'
check "ML05 StopFailure rate-limit 은 정규식 경로 (warn)" 'has "이 정규식은 StopFailure의 문서 값"'
check "요약: error 9 · warn 6" 'has "error 9 · warn 6"'

# 정상 MCP 꼴(플러그인 범위 서버·와일드카드)은 통과하고 하이픈 서버의 맨이름만 걸림
OUT=$(ml fixtures/mcp_tool.json); rc=$?
check "mcp: plugin 범위·와일드카드는 통과, mcp__brave-search 만 error 1" '[ $rc -eq 1 ] && has "error 1 · warn 0" && has "mcp__brave-search__.*"'

# warn만 있으면 exit 0, --strict면 1
ml fixtures/warn_only.json >/dev/null; rc=$?
check "warn만: exit 0" '[ $rc -eq 0 ]'
ml --strict fixtures/warn_only.json >/dev/null; rc=$?
check "--strict: warn도 exit 1" '[ $rc -eq 1 ]'

# 폴더 지정: .claude/settings.json을 찾는다
OUT=$(ml fixtures/proj); rc=$?
check "폴더 지정: .claude/settings.json 발견 (파일 1개)" '[ $rc -eq 1 ] && has "파일 1개"'

# 깨진 JSON은 ML90 error, 다른 파일 점검은 계속
OUT=$(ml fixtures/broken/settings.json fixtures/good.json); rc=$?
check "깨진 JSON: ML90 error 후에도 계속, exit 1" '[ $rc -eq 1 ] && has "ML90" && has "파일 2개"'

# --json 출력은 파싱되고 개수가 맞다
OUT=$(ml --json fixtures/bad.json)
check "--json: 파싱되고 errors 9" 'echo "$OUT" | $PY -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d[\"errors\"]==9 and d[\"warnings\"]==6 and d[\"groups\"]==15 else 1)"'

# --extra-tool 로 사용자 정의 도구 허용
OUT=$(echo '{"hooks":{"PreToolUse":[{"matcher":"MyTool","hooks":[]}]}}' > /tmp/ml_extra.json; ml /tmp/ml_extra.json); rc=$?
check "알 수 없는 도구 MyTool 은 error" '[ $rc -eq 1 ]'
ml --extra-tool MyTool /tmp/ml_extra.json >/dev/null; rc=$?
check "--extra-tool MyTool 이면 통과" '[ $rc -eq 0 ]'
rm -f /tmp/ml_extra.json

# 훅 설정이 없는 폴더는 조용히 0 (CI에서 안전)
mkdir -p /tmp/ml_empty && OUT=$(ml /tmp/ml_empty 2>&1); rc=$?; rmdir /tmp/ml_empty
check "설정 파일이 없으면 exit 0" '[ $rc -eq 0 ]'

# 읽기 전용: 점검이 훅 명령을 실행하지 않는다
MARK=/tmp/ml_ran_$$; echo "{\"hooks\":{\"PreToolUse\":[{\"matcher\":\"Bash\",\"hooks\":[{\"type\":\"command\",\"command\":\"touch $MARK\"}]}]}}" > /tmp/ml_ro.json
ml /tmp/ml_ro.json >/dev/null; rm -f /tmp/ml_ro.json
check "훅 명령을 실행하지 않는다" '[ ! -e $MARK ]'

echo "---"
echo "통과 $pass · 실패 $fail"
[ $fail -eq 0 ]

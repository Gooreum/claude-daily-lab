#!/usr/bin/env bash
# 키·모델·claude CLI 없이 도는 테스트. 이 폴더에서 `bash test.sh`.
set -u
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "ok   $1"; }
bad() { fail=$((fail+1)); echo "FAIL $1"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
out() { $PY mod_audit.py "$@" 2>&1; }

# --- good: 알림·명령 등록만 쓰는 모드
O=$(out fixtures/good); rc=$?
check "good: exit 0" '[ $rc -eq 0 ]'
check "good: 훅 이벤트 session.start, turn.complete 추출" 'echo "$O" | grep -q "훅 이벤트: session.start, turn.complete"'
check "good: 호출 \$.command.register, \$.ui.notify 추출" 'echo "$O" | grep -q "\$.command.register, \$.ui.notify"'
check "good: 주석 속 \$.process.run은 세지 않음" '! echo "$O" | grep -q "process"'
check "good: import한 format.mjs까지 따라가 읽음 (지적 0)" 'echo "$O" | grep -q "error 0 · warn 0"'

# --- guard: .catch가 있는 tool.call 게이트
O=$(out fixtures/guard); rc=$?
check "guard: exit 0, MA06 없음" '[ $rc -eq 0 ] && ! echo "$O" | grep -q MA06'
sed 's/\.catch(/.then(/' fixtures/guard/hooks/register.js > /tmp/mod-audit-nocatch.$$ 
mkdir -p /tmp/mod-audit-t.$$ && cp -r fixtures/guard/. /tmp/mod-audit-t.$$/ && cp /tmp/mod-audit-nocatch.$$ /tmp/mod-audit-t.$$/hooks/register.js
O=$(out /tmp/mod-audit-t.$$)
check "guard에서 .catch를 빼면 MA06 warn" 'echo "$O" | grep -q "register.js:9: warn MA06"'
rm -rf /tmp/mod-audit-t.$$ /tmp/mod-audit-nocatch.$$

# --- bad
O=$(out fixtures/bad); rc=$?
check "bad: exit 1" '[ $rc -eq 1 ]'
check "MA01: \$.process.run은 error" 'echo "$O" | grep -q "register.js:5: error MA01"'
check "MA02: env.get + http.fetch 조합은 error (fetch 줄)" 'echo "$O" | grep -q "register.js:4: error MA02"'
check "MA02: http.fetch 단독 지적은 warn" 'echo "$O" | grep -q "register.js:4: warn MA02"'
check "MA03: env.get warn" 'echo "$O" | grep -q "register.js:3: warn MA03"'
check "MA05: tool.check는 승인 가능 warn" 'echo "$O" | grep -q "register.js:2: warn MA05"'
check "MA06: tool.check·prompt.submit에 catch 없음 2건" '[ "$(echo "$O" | grep -c "warn MA06")" = 2 ]'
check "MA07: plugin.json의 @latest는 error" 'echo "$O" | grep -q "error MA07 MCP 서버 .weather."'
check "MA07: .mcp.json의 버전 없는 npx는 warn + 고친 형태 제안" 'echo "$O" | grep -q "@acme/notes-mcp@<버전>"'
check "MA07: uvx는 == 형태로 제안" 'echo "$O" | grep -q "some-tool==<버전>"'
check "MA07: 버전 고정된 npx·node 로컬은 지적 없음" '! echo "$O" | grep -q "ok-mcp" && ! echo "$O" | grep -q "server.js"'
check "MA08: 원격 URL 동적 import error" 'echo "$O" | grep -q "register.js:10: error MA08"'
check "MA08: eval warn, 상수 아닌 import warn" 'echo "$O" | grep -q "register.js:9: warn MA08" && echo "$O" | grep -q "register.js:11: warn MA08"'
check "MA08: 플러그인 폴더 밖 모듈 경로 error" 'echo "$O" | grep -q "error MA08 모듈 경로가 플러그인 폴더 밖"'

# --- ts: 확장자 없는 상대 import(`./lens`)를 따라가고 타입 폴더(`../types`)는 문제 삼지 않는다
O=$(out fixtures/ts); rc=$?
check "ts: 확장자 없는 ./lens(.ts)까지 읽어 \$.model.complete 추출" 'echo "$O" | grep -q "lens.ts:1: warn MA04"'
check "ts: ../types(index.d.ts)는 읽기 불가 경고 없음" '! echo "$O" | grep -q MA09 && [ $rc -eq 0 ]'

# --- 옵션
$PY mod_audit.py --strict fixtures/good >/dev/null; check "--strict: warn 0이면 통과" '[ $? -eq 0 ]'
mkdir -p /tmp/mod-audit-w.$$ && cp -r fixtures/good/. /tmp/mod-audit-w.$$/ && echo 'export const x = ($) => $.model.complete("hi")' >> /tmp/mod-audit-w.$$/hooks/format.mjs
$PY mod_audit.py /tmp/mod-audit-w.$$ >/dev/null; check "warn만 있으면 기본 exit 0" '[ $? -eq 0 ]'
$PY mod_audit.py --strict /tmp/mod-audit-w.$$ >/dev/null; check "--strict: warn만 있어도 exit 1" '[ $? -eq 1 ]'
rm -rf /tmp/mod-audit-w.$$

O=$(out --allow '$.ui.*,$.command.register' fixtures/good); check "--allow: 허용 범위 안이면 통과 (와일드카드)" '[ $? -eq 0 ]'
O=$(out --allow '$.command.register' fixtures/good); rc=$?
check "--allow: 목록 밖 \$.ui.notify는 MA10 error" '[ $rc -eq 1 ] && echo "$O" | grep -q "error MA10 \$.ui.notify"'

$PY mod_audit.py --json fixtures/good > /tmp/mod-audit-base.$$.json
check "--json: 파싱 가능, calls·events 포함" '$PY -c "import json;d=json.load(open(\"/tmp/mod-audit-base.$$.json\"));p=d[\"plugins\"][0];assert \"\$.ui.notify\" in p[\"calls\"] and \"turn.complete\" in p[\"events\"]"'
$PY mod_audit.py --baseline /tmp/mod-audit-base.$$.json fixtures/good >/dev/null; check "--baseline: 같은 버전이면 통과" '[ $? -eq 0 ]'
O=$(out --baseline /tmp/mod-audit-base.$$.json fixtures/bad)
check "--baseline: 새 호출 \$.process.run을 MA10으로 잡음" 'echo "$O" | grep -q "error MA10 이전 보고서에 없던 호출이 새로 생겼다: \$.process.run"'
check "--baseline: 새 훅 이벤트 tool.check도 잡음" 'echo "$O" | grep -q "error MA10 이전 보고서에 없던 훅 이벤트가 새로 생겼다: tool.check"'
rm -f /tmp/mod-audit-base.$$.json

# --- 여러 플러그인 / 입력 오류
O=$(out fixtures/tree); rc=$?
check "tree: 플러그인 2개를 모두 찾음" 'echo "$O" | grep -q "플러그인 2개"'
check "tree: modules 없는 플러그인은 '모드 아님'" 'echo "$O" | grep -q "skill-only 0.0.1 — 모드 아님"'
check "tree: runner의 \$.process.spawn error → exit 1" '[ $rc -eq 1 ] && echo "$O" | grep -q "m.mjs:3: error MA01"'
$PY mod_audit.py /nonexistent >/dev/null 2>&1; check "없는 폴더는 exit 2" '[ $? -eq 2 ]'
mkdir -p /tmp/mod-audit-e.$$; $PY mod_audit.py /tmp/mod-audit-e.$$ >/dev/null 2>&1; check "plugin.json 없는 폴더는 exit 2" '[ $? -eq 2 ]'; rmdir /tmp/mod-audit-e.$$

echo; echo "통과 $pass · 실패 $fail"
[ $fail -eq 0 ]

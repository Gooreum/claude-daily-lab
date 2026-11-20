#!/usr/bin/env bash
# 키·모델 없이 도는 테스트. 이 폴더에서 `bash test.sh`.
set -u
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "ok   $1"; }
bad() { fail=$((fail+1)); echo "FAIL $1"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
hm() { $PY hook_merge.py "$@" --project-dir .; }
has() { echo "$OUT" | grep -q -- "$1"; }

# 1. defer(빠름) + ask(느림): 대화형은 defer를 무시해 ask, claude -p는 defer
OUT=$(hm run fixtures/defer_ask.json --command 'echo hi'); rc=$?
check "defer+ask: exit 0 (버전 미지정은 warn)" '[ $rc -eq 0 ]'
check "defer+ask: 훅 2개가 걸림" 'has "중 2개가 걸린다"'
check "defer+ask: defer가 1등으로 끝남" 'echo "$OUT" | grep -E "^  1 +defer" >/dev/null'
check "defer+ask: 대화형 → ask (defer 무시)" 'has "대화형 → ask (defer 무시)"'
check "defer+ask: claude -p → defer" 'has "claude -p → defer"'
check "defer+ask: HM01 갈림" 'has "HM01"'
check "defer+ask: HM02 버전 미지정 warn" 'has "warn  HM02" && has "버전을 알려 주면"'
check "defer+ask: HM03 defer 무시 경고" 'has "HM03"'

# 2. 2.1.319이면 HM02가 error → exit 1, 2.1.321이면 HM02 없음
OUT=$(hm run fixtures/defer_ask.json --command 'echo hi' --claude-version 2.1.319); rc=$?
check "2.1.319: exit 1" '[ $rc -eq 1 ]'
check "2.1.319: HM02 error" 'has "error HM02" && has "2.1.319 < 2.1.321"'
OUT=$(hm run fixtures/defer_ask.json --command 'echo hi' --claude-version "claude 2.1.322 (Claude Code)"); rc=$?
check "2.1.322(문장에서 추출): exit 0" '[ $rc -eq 0 ]'
check "2.1.322: HM02 없음" '! has "HM02"'

# 3. 병렬 호출 가정이면 print 모드도 defer를 무시
OUT=$(hm run fixtures/defer_ask.json --command 'echo hi' --parallel-calls)
check "병렬 호출: claude -p → ask (defer 무시)" 'has "claude -p → ask (defer 무시)"'

# 4. ask 둘 + allow: ask가 이기고 HM04
OUT=$(hm run fixtures/two_ask.json --command 'echo hi')
check "ask×2+allow: 합침 ask" 'has "대화형 → ask · claude -p → ask"'
check "ask×2+allow: HM04" 'has "HM04"'

# 5. exit 2(deny)가 allow·ask를 이김, 여러 matcher 그룹 합산(정규식 .*)
OUT=$(hm run fixtures/deny_wins.json --command 'rm -rf x')
check "deny 승리: 합침 deny" 'has "대화형 → deny · claude -p → deny"'
check "deny 승리: exit 2 사유 no-rm-rf" 'has "사유: no-rm-rf"'
check "deny 승리: 훅 3개(그룹 둘)" 'has "중 3개가 걸린다"'
OUT=$(hm run fixtures/deny_wins.json --tool Read --input '{"file_path":"a"}')
check "Read 호출엔 .* 그룹의 deny 하나만" 'has "중 1개가 걸린다" && has "대화형 → deny"'

# 6. 조용한 훅 + allow → allow, 충돌 없음
OUT=$(hm run fixtures/quiet.json --command 'ls'); rc=$?
check "조용+allow: 합침 allow, 지적 없음" '[ $rc -eq 0 ] && has "대화형 → allow" && has "error 0 · warn 0"'

# 7. 깨진 훅: crash(exit 1)·junk(JSON 아님)는 결정 없음, 옛 decision:approve는 allow
OUT=$(hm run fixtures/broken.json --command 'ls')
check "crash: HM05 fail-open 경고" 'has "HM05" && has "exit 1: 막지 않는 오류"'
check "junk: HM06" 'has "HM06"'
OUT=$(hm run fixtures/broken.json --command 'ls' --json)
check "옛 decision:approve → allow, deprecated 표시" 'echo "$OUT" | grep -q "옛 필드 decision=approve(deprecated)" && echo "$OUT" | grep -q "\"decision\": \"allow\""'

# 8. plan은 실행하지 않고 if·type으로 거른다
OUT=$(hm plan fixtures/if_filter.json --command 'git commit -m x'); rc=$?
check "plan: if 맞는 훅 1개만 걸림" 'has "중 1개가 걸린다" && has "걸림  if_filter.json\[Bash\] ./fixtures/hooks/deny_exit2.sh"'
check "plan: if 안 맞는 훅은 제외" 'has "if 조건이 이 호출과 안 맞음"'
check "plan: http 훅은 제외(실행 안 함)" 'has "type=http"'
check "plan: 합친 결과 줄 없음(실행 안 함)" '! has "합친 결과"'
OUT=$(hm plan fixtures/read_if.json --tool Read --input '{"file_path":".env"}')
check "plan: 판단 못 하는 if는 맞을 수 있음으로 표시" 'has "판단 못 함 — 맞을 수 있음"'

# 9. 입력 오류·JSON 출력·strict
OUT=$(hm plan fixtures/nope.json); rc=$?
check "없는 설정: exit 1 + 읽을 수 없다" '[ $rc -eq 1 ] && has "읽을 수 없다"'
OUT=$(hm run fixtures/deny_wins.json --command 'x' --json)
check "--json: merged.interactive == deny" 'echo "$OUT" | $PY -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d[\"merged\"][\"interactive\"]==\"deny\" else 1)"'
OUT=$(hm run fixtures/two_ask.json --command 'x' --strict); rc=$?
check "--strict: warn만 있어도 exit 1" '[ $rc -eq 1 ]'
OUT=$(hm run fixtures/quiet.json --tool Edit --input '{"file_path":"a"}'); rc=$?
check "걸리는 훅 없음: exit 0" '[ $rc -eq 0 ] && has "중 0개가 걸린다"'

# 10. 플러그인 hooks.json 도 같은 모양으로 읽는다
OUT=$(hm plan fixtures/plugin_hooks.json --command 'ls')
check "plugin hooks.json 읽기" 'has "중 1개가 걸린다"'

# 11. 훅이 CLAUDE_PROJECT_DIR·stdin 페이로드를 받는다 (스크립트가 stdin을 읽고 끝남 = 지연 없음)
OUT=$(hm run fixtures/quiet.json --command 'ls' --json)
check "페이로드 stdin 소비 후 정상 종료(rc 0)" 'echo "$OUT" | grep -q "\"rc\": 0"'

echo
echo "통과 $pass · 실패 $fail"
[ $fail -eq 0 ]

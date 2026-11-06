#!/usr/bin/env bash
# 키·모델·외부 네트워크 없이 도는 테스트(로컬 모의 서버 사용). 이 폴더에서 `bash test.sh`.
set -u
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "ok   $1"; }
bad() { fail=$((fail+1)); echo "FAIL $1"; }
check() { if eval "$2" >/dev/null; then ok "$1"; else bad "$1"; fi; }
ss() { $PY -I signout_sweep.py "$@"; }

TMP=$(mktemp -d)
cleanup() { [ -n "${SRV:-}" ] && kill "$SRV" 2>/dev/null; rm -rf "$TMP"; }
trap cleanup EXIT

# ── dry-run: 키 없이, 네트워크 없이
OUT=$(env -u ANTHROPIC_ADMIN_KEY $PY -I signout_sweep.py -f fixtures/members.txt user_ghost not-an-email --base-url http://127.0.0.1:9); rc=$?
check "dry-run: 잘못된 대상이 있으면 exit 2"           '[ $rc -eq 2 ]'
check "dry-run: 네트워크 안 썼다고 밝힘"                'echo "$OUT" | grep -q "^DRY-RUN"'
check "dry-run: 중복·주석 제거해 대상 5명"              'echo "$OUT" | grep -q "대상 5명"'
check "dry-run: 베타 헤더를 계획에 표시"                'echo "$OUT" | grep -q "anthropic-beta: admin-user-sign-out-2026-10-08"'
check "dry-run: 안 끝나는 것 체크리스트"                'echo "$OUT" | grep -q "API 키 — 계속 동작한다"'
OUT=$(ss alice@x.test --json); rc=$?
check "dry-run --json: 파싱되고 exit 0"                 '[ $rc -eq 0 ] && echo "$OUT" | $PY -I -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d[\"mode\"]==\"dry-run\" and len(d[\"plan\"])==2 else 1)"'
OUT=$(env -u ANTHROPIC_ADMIN_KEY $PY -I signout_sweep.py alice@x.test --apply 2>&1); rc=$?
check "--apply인데 키가 없으면 exit 2"                  '[ $rc -eq 2 ] && echo "$OUT" | grep -q "ANTHROPIC_ADMIN_KEY"'

# ── 모의 서버
export REQLOG="$TMP/req.log" PORTFILE="$TMP/port"; : > "$REQLOG"
$PY -I mock_server.py & SRV=$!
for _ in $(seq 1 50); do [ -s "$PORTFILE" ] && break; sleep 0.1; done
BASE="http://127.0.0.1:$(cat "$PORTFILE")"

printf 'alice@x.test\nbob@x.test\nzed@x.test\ndan@x.test\nerin@x.test\nfrank@x.test\nalice+hr@x.test\n' > "$TMP/list.txt"
OUT=$(ANTHROPIC_ADMIN_KEY=key-good ss -f "$TMP/list.txt" user_ghost --apply --base-url "$BASE" --wait-cap 1 2>&1); rc=$?
check "apply: 일부 실패면 exit 1"                       '[ $rc -eq 1 ]'
check "apply: alice 로그아웃됨"                          'echo "$OUT" | grep -E "^alice@x.test +user_alice +signed_out"'
check "apply: 주 소유자는 건너뜀(400 코드 판별)"          'echo "$OUT" | grep -E "^bob@x.test +user_bob +primary_owner"'
check "apply: 없는 멤버는 not_member"                    'echo "$OUT" | grep -E "^zed@x.test +not_member"'
check "apply: 429는 retry-after 뒤 재시도해 성공"          'echo "$OUT" | grep -E "^dan@x.test +user_dan +signed_out"'
check "apply: 503은 재시도 후 failed + 재전송 안내"        'echo "$OUT" | grep -E "^erin@x.test +user_erin +failed.*다시 보내면"'
check "apply: 조회가 둘이면 ambiguous, 고르지 않음"        'echo "$OUT" | grep -E "^frank@x.test +ambiguous"'
check "apply: 이메일 변형도 한 명으로 찾고 메모"           'echo "$OUT" | grep -E "^alice\+hr@x.test +user_alice +signed_out +이메일 변형"'
check "apply: user id 직접 지정 → 404는 not_member"       'echo "$OUT" | grep -E "^user_ghost +user_ghost +not_member"'
check "apply: 요약 줄"                                   'echo "$OUT" | grep -q "요약: ambiguous 1, failed 1, not_member 2, primary_owner 1, signed_out 3"'
check "apply: 끝나지 않은 것 안내 출력"                    'echo "$OUT" | grep -q "끝나지 않은 것"'
check "서버: 모든 로그아웃 요청에 베타 헤더"                '[ "$(grep "sign_out" "$REQLOG" | grep -vc "beta=admin-user-sign-out-2026-10-08")" -eq 0 ]'
check "서버: 조회에는 베타 헤더를 안 보냄"                  '[ "$(grep "^GET" "$REQLOG" | grep -c "beta=admin-user-sign-out")" -eq 0 ]'
check "서버: anthropic-version 헤더 전송"                  '[ "$(grep -vc "ver=2023-06-01" "$REQLOG")" -eq 0 ]'
check "서버: dan은 429 뒤 재시도로 2번"                    '[ "$(grep -c "users/user_dan/sign_out" "$REQLOG")" -eq 2 ]'
check "서버: erin은 3번 시도 후 포기"                      '[ "$(grep -c "users/user_erin/sign_out" "$REQLOG")" -eq 3 ]'
check "서버: 키 값이 출력에 새지 않음"                      '! echo "$OUT" | grep -q "key-good"'

# 재확인(--recheck-after): 로그아웃된 사람에게만 두 번째 요청
: > "$REQLOG"
OUT=$(ANTHROPIC_ADMIN_KEY=key-good ss alice@x.test --apply --base-url "$BASE" --recheck-after 1 --json 2>/dev/null); rc=$?
check "recheck: exit 0"                                  '[ $rc -eq 0 ]'
check "recheck: alice에게 로그아웃 요청 2번"                '[ "$(grep -c "users/user_alice/sign_out" "$REQLOG")" -eq 2 ]'
check "recheck: JSON에 recheck 결과"                      'echo "$OUT" | $PY -I -c "import sys,json; r=json.load(sys.stdin)[\"rows\"][0]; sys.exit(0 if r[\"recheck\"]==\"signed_out\" else 1)"'

# 치명 오류는 즉시 중단하고 남은 대상 수를 알린다
: > "$REQLOG"
OUT=$(ANTHROPIC_ADMIN_KEY=key-noscope ss user_a user_b user_c --apply --base-url "$BASE" 2>&1); rc=$?
check "403: exit 2로 중단"                               '[ $rc -eq 2 ]'
check "403: write:members 안내와 남은 대상 3명"            'echo "$OUT" | grep -q "write:members" && echo "$OUT" | grep -q "아직 처리 못한 대상 3명"'
check "403: 첫 요청에서 멈춤(나머지 2명은 안 보냄)"         '[ "$(grep -c "sign_out" "$REQLOG")" -eq 1 ]'
OUT=$(ANTHROPIC_ADMIN_KEY=key-notenrolled ss user_a --apply --base-url "$BASE" 2>&1); rc=$?
check "베타 미등록: exit 2 + 콘솔 대안 안내"                'echo "$OUT" | grep -q "organization_not_enrolled_in_beta"; [ $rc -eq 2 ]'
OUT=$(ANTHROPIC_ADMIN_KEY=wrong ss alice@x.test --apply --base-url "$BASE" 2>&1); rc=$?
check "401(조회 단계): exit 2"                           '[ $rc -eq 2 ] && echo "$OUT" | grep -q "read:members"'
OUT=$(ANTHROPIC_ADMIN_KEY=key-good ss user_a --apply --base-url http://127.0.0.1:9 --tries 2 --wait-cap 0 2>&1); rc=$?
check "연결 실패: failed로 기록하고 exit 1"                 '[ $rc -eq 1 ] && echo "$OUT" | grep -q "failed"'

echo
echo "통과 $pass · 실패 $fail"
[ $fail -eq 0 ]

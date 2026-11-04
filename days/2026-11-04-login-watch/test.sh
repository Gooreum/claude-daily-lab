#!/usr/bin/env bash
# 키·로그인·모델·네트워크 없이 도는 테스트. 이 폴더에서 `bash test.sh`.
set -u
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
NOW=2026-11-04T00:00:00Z
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "ok   $1"; }
bad() { fail=$((fail+1)); echo "FAIL $1"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
lw() { $PY login_watch.py --now $NOW "$@"; }

# 상태별 판정과 종료 코드
OUT=$(lw fixtures/status_ok.json);        rc=$?; check "ok: exit 0, OK 46일"            '[ $rc -eq 0 ] && echo "$OUT" | grep -q "^OK .*46일 남음"'
OUT=$(lw fixtures/status_warn.json);      rc=$?; check "warn: exit 1 (5.9일)"            '[ $rc -eq 1 ] && echo "$OUT" | grep -q "^WARN .*5.9일"'
OUT=$(lw fixtures/status_crit.json);      rc=$?; check "crit: exit 2 (+00:00 표기 2.0일)" '[ $rc -eq 2 ] && echo "$OUT" | grep -q "^CRIT .*2.0일"'
OUT=$(lw fixtures/status_expired.json);   rc=$?; check "expired: exit 2"                 '[ $rc -eq 2 ] && echo "$OUT" | grep -q "^EXPIRED .*3.0일 전에 만료"'
OUT=$(lw fixtures/status_loggedout.json); rc=$?; check "loggedOut: exit 2"               '[ $rc -eq 2 ] && echo "$OUT" | grep -q "^LOGGEDOUT"'
OUT=$(lw fixtures/status_noexpiry.json);  rc=$?; check "null 만료일: exit 0 NOEXPIRY"     '[ $rc -eq 0 ] && echo "$OUT" | grep -q "^NOEXPIRY"'
OUT=$(lw fixtures/status_noexpiry.json --strict); rc=$?; check "--strict: null 은 WARN exit 1" '[ $rc -eq 1 ]'

# claude -p 결과(credential_expires_at), JSONL 스트림·epoch 밀리초
OUT=$(lw fixtures/p_result.json);         rc=$?; check "claude -p 결과: 8.0일 WARN"       '[ $rc -eq 1 ] && echo "$OUT" | grep -q "8.0일"'
OUT=$(lw fixtures/stream.jsonl);          rc=$?; check "JSONL 마지막 result + epoch ms"   '[ $rc -eq 0 ] && echo "$OUT" | grep -q "2026-11-30T00:53Z"'
cat fixtures/p_result.json | { OUT=$(lw -); rc=$?; check "stdin('-') 입력" '[ $rc -eq 1 ]'; }

# 임계값 조절
OUT=$(lw fixtures/status_warn.json --warn-days 5); rc=$?; check "--warn-days 5: 5.9일은 OK" '[ $rc -eq 0 ]'
OUT=$(lw fixtures/status_warn.json --crit-days 7); rc=$?; check "--crit-days 7 > warn-days 10 아님: 5.9일 CRIT" '[ $rc -eq 2 ]'
OUT=$(lw fixtures/status_ok.json --warn-days 3 --crit-days 5); rc=$?; check "crit > warn 는 입력 오류 exit 3" '[ $rc -eq 3 ]'

# 입력 오류
OUT=$(lw fixtures/garbage.txt);           rc=$?; check "JSON 아님: exit 3"                '[ $rc -eq 3 ] && echo "$OUT" | grep -q "^ERROR"'
OUT=$(lw fixtures/old_cli.json);          rc=$?; check "필드 없음(옛 CLI): exit 3 + 버전 안내" '[ $rc -eq 3 ] && echo "$OUT" | grep -q "2.1.318"'
OUT=$(lw fixtures/nope.json);             rc=$?; check "없는 파일: exit 3"                '[ $rc -eq 3 ]'
OUT=$($PY login_watch.py 2>&1);           rc=$?; check "인자 없음: exit 3"                '[ $rc -eq 3 ]'
OUT=$($PY login_watch.py --now abc fixtures/status_ok.json 2>&1); rc=$?; check "--now 형식 오류: exit 3" '[ $rc -eq 3 ]'

# 여러 파일: 급한 순서 정렬, 가장 나쁜 코드
OUT=$(lw fixtures/status_ok.json fixtures/status_expired.json fixtures/status_warn.json); rc=$?
check "다중: 최악 코드 2"                 '[ $rc -eq 2 ]'
check "다중: EXPIRED → WARN → OK 순서"    '[ "$(echo "$OUT" | cut -d" " -f1 | head -3 | tr "\n" ",")" = "EXPIRED,WARN,OK," ]'

# 출력 형식
OUT=$(lw fixtures/status_crit.json fixtures/status_warn.json --format gha)
check "gha: ::error 와 ::warning 줄"      'echo "$OUT" | grep -q "^::error title=" && echo "$OUT" | grep -q "^::warning title="'
OUT=$(lw fixtures/status_warn.json --format json)
check "json: 파싱되고 worst_exit=1"        'echo "$OUT" | $PY -c "import json,sys; d=json.load(sys.stdin); assert d[\"worst_exit\"]==1 and d[\"rows\"][0][\"state\"]==\"WARN\""'

# --dry-run (claude 없이)
OUT=$(lw --dry-run); rc=$?
check "dry-run: 3건, 최악 코드 2"          '[ $rc -eq 2 ] && echo "$OUT" | grep -c "demo-" | grep -q "^3$"'

# --live: 가짜 claude 로 PATH 를 덮어 로그인 만료 임박 상황을 흉내
FAKE=$(mktemp -d); trap 'rm -rf "$FAKE"' EXIT
cat > "$FAKE/claude" <<'SH'
#!/usr/bin/env bash
echo '{"loggedIn": true, "authMethod": "claude.ai", "loginExpiresAt": "2026-11-07T00:00:00Z"}'
SH
chmod +x "$FAKE/claude"
OUT=$(PATH="$FAKE:$PATH" lw --live); rc=$?
check "live(가짜 claude): 3.0일 CRIT"      '[ $rc -eq 2 ] && echo "$OUT" | grep -Eq "^CRIT +live"'
OUT=$(PATH="/nonexistent" "$(command -v $PY)" login_watch.py --live 2>&1); rc=$?
check "live: claude 없으면 exit 3"         '[ $rc -eq 3 ] && echo "$OUT" | grep -q "claude 실행 실패"'

echo "---"; echo "통과 $pass / 실패 $fail"
[ $fail -eq 0 ]

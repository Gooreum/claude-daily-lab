#!/usr/bin/env bash
# test.sh — cost_top.py 오프라인 테스트. 키·모델·외부 네트워크 없이 127.0.0.1의 가짜 서버만 쓴다. 이 폴더에서 `bash test.sh`.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
HERE="$(pwd)"
C="python3 -I $HERE/cost_top.py"
NOW="2026-10-24"
pass=0; fail=0
T="$(mktemp -d)"
SRV_PID=""
trap '[ -n "$SRV_PID" ] && kill "$SRV_PID" 2>/dev/null; rm -rf "$T"' EXIT

expect() { # $1=label $2=기대 종료코드 $3=있어야 할 문자열 $4=있으면 안 되는 문자열 ; 나머지=명령
  local label="$1" want="$2" needle="$3" absent="$4"; shift 4
  local out rc; out="$("$@" 2>&1)"; rc=$?
  if [ "$rc" -eq "$want" ] && { [ -z "$needle" ] || [[ "$out" == *"$needle"* ]]; } && { [ -z "$absent" ] || [[ "$out" != *"$absent"* ]]; }; then
    pass=$((pass+1)); echo "  ✅ $label (exit=$rc)"
  else
    fail=$((fail+1)); echo "  ❌ $label (exit=$rc, expected $want, needle='$needle', absent='$absent')"; echo "$out" | sed 's/^/      /'
  fi
}
check() { # $1=label $2=참이어야 하는 명령 문자열
  if eval "$2"; then pass=$((pass+1)); echo "  ✅ $1"; else fail=$((fail+1)); echo "  ❌ $1 ($2)"; fi
}

echo "[1] 요청 검증 — 문서의 제약을 보내기 전에 잡는다"
expect "32일 범위 거부"            2 "최대 31일" "" $C cost --from 2026-09-01 --to 2026-10-03 --now $NOW --dry-run
expect "31일은 통과"               0 "[dry-run] GET" "" $C cost --from 2026-09-01 --to 2026-10-02 --now $NOW --dry-run
expect "1m 버킷 24시간 초과 거부"  2 "최대 24시간" "" $C cost --from 2026-10-20 --to 2026-10-22 --bucket 1m --now $NOW --dry-run
expect "버킷은 ending_at 필요"     2 "ending_at이 필요" "" $C cost --from 2026-10-20 --bucket 1d --now $NOW --dry-run
expect "group_by 6개 거부"         2 "최대 5개" "" $C cost --days 7 --now $NOW --dry-run --group-by model --group-by workspace_id --group-by api_key_id --group-by actor --group-by service_tier --group-by speed
expect "cost_type은 5개에 안 센다" 0 "group_by[]=cost_type" "" $C cost --days 7 --now $NOW --dry-run --group-by model --group-by workspace_id --group-by api_key_id --group-by actor --group-by service_tier --group-by cost_type --group-by token_type
expect "usage에 cost_type 거부"    2 "cost 엔드포인트에서만" "" $C usage --days 7 --now $NOW --group-by cost_type --input /dev/null
expect "2026년 이전 시작 거부"     2 "2026-01-01 이후" "" $C cost --from 2025-12-31 --to 2026-01-05 --now $NOW --dry-run
expect "365일 넘은 시작 거부"      2 "365일" "" $C cost --from 2026-01-02 --to 2026-01-05 --now 2027-02-01 --dry-run
expect "order_by=time은 버킷 필요" 2 "time_bucket_width" "" $C cost --days 3 --order-by time --now $NOW --dry-run
expect "usage order_by 오타 거부"  2 "order_by는" "" $C usage --days 3 --order-by tokens --now $NOW --input /dev/null
expect "끝이 시작보다 앞"          2 "뒤여야" "" $C cost --from 2026-10-10 --to 2026-10-09 --now $NOW --dry-run
expect "날짜 형식 오류"            2 "시각을 읽을 수 없다" "" $C cost --from 10/20 --now $NOW --dry-run
expect "기간 인자 없음"            2 "--days 또는 --from" "" $C cost --now $NOW --dry-run
expect "잘못된 엔드포인트"         3 "" "" $C bogus --days 3
VALS="$(python3 -c 'print(",".join(f"m{i}" for i in range(101)))')"
expect "필터 값 101개 거부"        2 "100개까지" "" $C cost --days 3 --now $NOW --dry-run --filter "models=$VALS"

echo "[2] dry-run — 키 없이 URL을 만들고 합성 샘플로 보고서를 그린다"
OUT="$($C cost --days 8 --now $NOW --bucket 1d --group-by model --filter models=claude-opus-5-5,claude-sonnet-5-5 --dry-run 2>&1)"
check "URL에 group_by[]=model"            '[[ "$OUT" == *"group_by[]=model"* ]]'
check "URL에 시작·끝(오늘 00:00Z 기준)"   '[[ "$OUT" == *"starting_at=2026-10-16T00:00:00Z&ending_at=2026-10-24T00:00:00Z"* ]]'
check "필터가 models[]= 반복으로 변환"    '[[ "$OUT" == *"models[]=claude-opus-5-5&models[]=claude-sonnet-5-5"* ]]'
check "베타 헤더 이름을 보여 준다"        '[[ "$OUT" == *"analytics-usage-cost-2026-08-24"* ]]'
check "샘플임을 밝힌다"                   '[[ "$OUT" == *"합성 샘플"* ]]'
check "센트 문자열을 달러로 환산 (50380센트=503.80달러)" '[[ "$OUT" == *"\$503.80"* ]]'
expect "dry-run usage는 거부"     2 "cost 전용" "" $C usage --days 3 --now $NOW --dry-run
expect "키 없으면 안내하고 실패"  2 "키가 없다" "" env -u ANTHROPIC_ADMIN_KEY -u ANTHROPIC_API_KEY $C cost --days 3 --now $NOW

echo "[3] 가짜 서버로 실제 HTTP 왕복 — 페이지네이션·헤더·오류"
PORT="$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')"
LOG="$T/req.log"; : > "$LOG"
python3 -I "$HERE/fake_server.py" "$PORT" "$LOG" & SRV_PID=$!
for _ in $(seq 1 50); do (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null && break; sleep 0.1; done
KEY="sk-test-NOT-A-REAL-KEY-123"
export ANTHROPIC_ADMIN_KEY="$KEY"
OUT="$($C cost --from 2026-10-20 --to 2026-10-22 --now $NOW --base-url http://127.0.0.1:$PORT/ok 2>&1)"; RC=$?
check "2쪽을 이어 받아 합계 153.00달러"       '[[ "$OUT" == *"비용 합계: \$153.00"* ]]'
check "opus는 쪽을 가로질러 150.50달러"       '[[ "$OUT" == *"claude-opus-5-5 | \$150.50"* ]]'
check "할인율 계산 (정가 대비)"            '[[ "$OUT" == *"claude-opus-5-5 | \$150.50 | \$175.50 | 14%"* ]]'
check "종료 코드 0"                         '[ "$RC" -eq 0 ]'
check "서버가 요청 2번을 받음"              '[ "$(wc -l < "$LOG")" -eq 2 ]'
check "첫 요청에는 page 없음"               '! sed -n 1p "$LOG" | grep -q "page="'
check "둘째 요청이 next_page 토큰을 보냄"   'sed -n 2p "$LOG" | grep -q "page=page_SECOND"'
check "x-api-key 헤더 전송"                 'sed -n 1p "$LOG" | grep -q "\"key\": \"$KEY\""'
check "베타·버전 헤더 전송"                 'sed -n 1p "$LOG" | grep -q "analytics-usage-cost-2026-08-24" && sed -n 1p "$LOG" | grep -q "\"ver\": \"2023-06-01\""'
check "경로가 /v1/organizations/analytics/cost" 'sed -n 1p "$LOG" | grep -q "/ok/v1/organizations/analytics/cost"'
check "출력에 키가 나오지 않음"             '[[ "$OUT" != *"$KEY"* ]]'
OUT="$($C cost --from 2026-10-20 --to 2026-10-22 --now $NOW --base-url http://127.0.0.1:$PORT/err401 2>&1)"; RC=$?
check "401 → exit 2, 서버 메시지 표시"      '[ "$RC" -eq 2 ] && [[ "$OUT" == *"HTTP 401"* ]] && [[ "$OUT" == *"invalid x-api-key"* ]]'
check "오류 출력에 키가 나오지 않음"        '[[ "$OUT" != *"$KEY"* ]]'
OUT="$($C cost --from 2026-10-20 --to 2026-10-22 --now $NOW --base-url http://127.0.0.1:$PORT/loop 2>&1)"; RC=$?
check "has_more가 끝나지 않으면 100쪽에서 중단" '[ "$RC" -eq 2 ] && [[ "$OUT" == *"100쪽"* ]]'
OUT="$($C cost --from 2026-10-20 --to 2026-10-22 --now $NOW --base-url http://127.0.0.1:1/ok 2>&1)"; RC=$?
check "연결 거부 → exit 2"                  '[ "$RC" -eq 2 ] && [[ "$OUT" == *"요청 실패"* ]]'
OUT="$(ANTHROPIC_ADMIN_KEY= ANTHROPIC_API_KEY="$KEY" $C cost --from 2026-10-20 --to 2026-10-22 --now $NOW --base-url http://127.0.0.1:$PORT/ok 2>&1)"
check "ANTHROPIC_API_KEY로 폴백"            '[[ "$OUT" == *"비용 합계"* ]]'
unset ANTHROPIC_ADMIN_KEY

echo "[4] 저장한 응답 재생 — 급증·부분 데이터·갱신 시각"
cat > "$T/days.json" <<'JSON'
{"data":[
 {"starting_at":"2026-10-01T00:00:00Z","ending_at":"2026-10-02T00:00:00Z","group":{"model":"a"},"cost":{"amount":"10000.000000","list_amount":"10000.000000","requests":null}},
 {"starting_at":"2026-10-02T00:00:00Z","ending_at":"2026-10-03T00:00:00Z","group":{"model":"a"},"cost":{"amount":"11000.000000","list_amount":"11000.000000","requests":null}},
 {"starting_at":"2026-10-03T00:00:00Z","ending_at":"2026-10-04T00:00:00Z","group":{"model":"a"},"cost":{"amount":"9000.000000","list_amount":"9000.000000","requests":null}},
 {"starting_at":"2026-10-04T00:00:00Z","ending_at":"2026-10-05T00:00:00Z","group":{"model":"a"},"cost":{"amount":"90000.000000","list_amount":"90000.000000","requests":null}},
 {"starting_at":"2026-10-05T00:00:00Z","ending_at":"2026-10-06T00:00:00Z","group":{"model":"a"},"cost":{"amount":"900000.000000","list_amount":"900000.000000","requests":null}}
],"has_more":false,"next_page":null,"data_refreshed_at":"2026-10-05T00:00:00Z"}
JSON
OUT="$($C cost --days 5 --now 2026-10-06 --bucket 1d --input "$T/days.json" 2>&1)"; RC=$?
check "10-04 급증(중앙값의 8배 넘게) 표시"       '[[ "$OUT" == *"2026-10-04T00:00:00Z  \$900.00 ← 급증"* ]]'
check "갱신 시각 이후(10-05) 버킷은 부분"   '[[ "$OUT" == *"2026-10-05T00:00:00Z  \$9,000.00 (부분 데이터)"* ]]'
check "부분 버킷은 급증 판정에서 제외"      '[[ "$OUT" != *"9,000.00 ← 급증"* ]]'
check "급증만으로는 exit 0"                 '[ "$RC" -eq 0 ]'
expect "--fail-on-spike면 exit 1"           1 "급증" "" $C cost --days 5 --now 2026-10-06 --bucket 1d --input "$T/days.json" --fail-on-spike
expect "--spike-min이 크면 급증 아님"       0 "" "← 급증" $C cost --days 5 --now 2026-10-06 --bucket 1d --input "$T/days.json" --spike-min 5000 --fail-on-spike
expect "--spike-factor 20이면 급증 아님"    0 "" "← 급증" $C cost --days 5 --now 2026-10-06 --bucket 1d --input "$T/days.json" --spike-factor 20 --fail-on-spike
python3 - "$T" <<'PY'
import json, sys
d = json.load(open(sys.argv[1] + "/days.json"))
d["data_refreshed_at"] = None
json.dump(d, open(sys.argv[1] + "/null.json", "w"))
d["data_refreshed_at"] = "2026-10-05T00:00:00Z"
d["data"] = d["data"][:2]
json.dump(d, open(sys.argv[1] + "/two.json", "w"))
PY
expect "data_refreshed_at null이면 경고"    0 "아직 집계된 데이터가 없다" "← 급증" $C cost --days 5 --now 2026-10-06 --bucket 1d --input "$T/null.json"
expect "버킷 2개면 급증 판정 안 함"         0 "" "← 급증" $C cost --days 5 --now 2026-10-06 --bucket 1d --input "$T/two.json"

echo "[5] 집계 세부 — usage, actor 객체, priority 주의, JSON"
cat > "$T/usage.json" <<'JSON'
{"data":[
 {"starting_at":"2026-10-01T00:00:00Z","ending_at":"2026-10-02T00:00:00Z","group":{"actor":{"type":"user","id":"user_1","email":"a@example.com"}},
  "usage":{"uncached_input_tokens":100,"cache_read_input_tokens":300,"output_tokens":100,"total_tokens":500,"requests":7}},
 {"starting_at":"2026-10-01T00:00:00Z","ending_at":"2026-10-02T00:00:00Z","group":{"actor":null},
  "usage":{"total_tokens":100,"cache_read_input_tokens":0,"requests":2}}
],"has_more":false,"data_refreshed_at":"2026-10-03T00:00:00Z"}
JSON
OUT="$($C usage --days 1 --now 2026-10-02 --group-by actor --input "$T/usage.json" 2>&1)"
check "usage: 토큰 합계 600"                '[[ "$OUT" == *"토큰 합계: 600"* ]]'
check "actor 객체를 type:id:email로 표시"   '[[ "$OUT" == *"user:user_1:a@example.com | 500 | 60%"* ]]'
check "actor null은 (없음)"                 '[[ "$OUT" == *"(없음) | 100 | 0%"* ]]'
check "요청 수 합산"                        '[[ "$OUT" == *"| 7 |"* ]]'
cat > "$T/prio.json" <<'JSON'
{"data":[{"starting_at":"2026-10-01T00:00:00Z","ending_at":"2026-10-02T00:00:00Z","group":{"service_tier":"priority"},
 "cost":{"amount":"0.000000","list_amount":"0.000000","requests":12}}],"has_more":false,"data_refreshed_at":"2026-10-03T00:00:00Z"}
JSON
expect "priority 행에 약정 주의 문구"       0 "Priority Tier 약정분은 비용 0" "" $C cost --days 1 --now 2026-10-02 --group-by service_tier --input "$T/prio.json"
JSONOUT="$($C usage --days 1 --now 2026-10-02 --group-by actor --input "$T/usage.json" --json 2>&1)"
check "--json이 파싱된다"                   'python3 -c "import json,sys; d=json.loads(sys.argv[1]); assert len(d[\"groups\"])==2" "$JSONOUT"'
echo '[{"data":[],"has_more":false,"data_refreshed_at":"2026-10-03T00:00:00Z"}]' > "$T/arr.json"
expect "쪽 배열 입력, 빈 데이터"            0 "합계: \$0.00" "" $C cost --days 1 --now 2026-10-02 --input "$T/arr.json"
expect "--top이 줄 수를 자르고 나머지 표시" 0 "나머지 1개" "" $C usage --days 1 --now 2026-10-02 --group-by actor --top 1 --input "$T/usage.json"

echo
echo "통과 $pass · 실패 $fail"
[ "$fail" -eq 0 ]

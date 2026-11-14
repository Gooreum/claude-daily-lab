#!/usr/bin/env bash
# agent-inbox 테스트: 키·모델·네트워크 없이 돈다. 이 폴더에서 `bash test.sh`.
cd "$(dirname "$0")" || exit 1
export PYTHONDONTWRITEBYTECODE=1
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
AI="python3 agent_inbox.py --db $T/t.db"
PASS=0; FAIL=0
ok()  { echo "ok   - $1"; PASS=$((PASS+1)); }
bad() { echo "FAIL - $1"; [ -n "$2" ] && echo "       $2"; FAIL=$((FAIL+1)); }
has() { echo "$1" | grep -qF -- "$2"; }   # has "$OUT" "문구"
status_n() { $AI status | sed -n "s/^events: .*$1=\([0-9]*\).*/\1/p"; }
sql() { python3 -c "import sqlite3,sys;c=sqlite3.connect(sys.argv[1]);c.execute(sys.argv[2]);c.commit()" "$T/t.db" "$1"; }

T0=1800000000   # 고정 시각(epoch)

# 1. push: 새 이벤트는 queued, 같은 source+id 는 duplicate (원천이 재전송해도 한 번만)
OUT=$($AI --now $T0 push --source github --id d-1 --payload '{"pr":7}'); has "$OUT" "queued github/d-1" && ok "push → queued" || bad "push" "$OUT"
OUT=$($AI --now $T0 push --source github --id d-1 --payload '{"pr":7}'); has "$OUT" "duplicate github/d-1" && ok "같은 id 재전송 → duplicate" || bad "중복" "$OUT"
OUT=$($AI --now $T0 push --source slack --id d-1); has "$OUT" "queued slack/d-1" && ok "source 가 다르면 같은 id 도 별개" || bad "source 구분" "$OUT"
[ "$(status_n pending)" = 2 ] && ok "pending 2건" || bad "pending 수" "$(status_n pending)"

# 2. 잘못된 입력은 거부
$AI push --source x --id y --payload '{oops' >/dev/null 2>&1; [ $? -ne 0 ] && ok "깨진 payload 거부" || bad "깨진 payload"
$AI timer add --name t --in 5x >/dev/null 2>&1; [ $? -ne 0 ] && ok "잘못된 기간 거부" || bad "잘못된 기간"
$AI timer add --name t --at 2030-01-01 --in 5m >/dev/null 2>&1; [ $? -ne 0 ] && ok "--at 와 --in 동시 사용 거부" || bad "--at/--in"

# 3. debounce: 가장 새 이벤트가 window 보다 어리면 아직 안 돈다
OUT=$($AI --now $((T0+5)) work --window 10s --worker a); has "$OUT" "nothing ready" && ok "5초 뒤 → 아직 대기(debounce)" || bad "debounce" "$OUT"
[ "$(status_n pending)" = 2 ] && ok "대기 중엔 pending 유지" || bad "pending 유지"

# 4. 같은 세션의 이벤트 2건은 한 번의 run 으로 묶인다
OUT=$($AI --now $((T0+30)) work --window 10s --worker a --dry-run)
has "$OUT" "events=2" && has "$OUT" "github/d-1" && has "$OUT" "slack/d-1" && ok "한 run 에 2건 묶음(dry-run)" || bad "묶음" "$OUT"
[ "$(status_n done)" = 2 ] && [ "$(status_n pending)" = 0 ] && ok "처리 뒤 done 2건" || bad "done" "$($AI status)"

# 5. 세션이 다르면 run 도 따로
$AI --now $((T0+40)) push --source u --id 1 --session alice >/dev/null
$AI --now $((T0+40)) push --source u --id 2 --session bob >/dev/null
OUT=$($AI --now $((T0+100)) work --window 10s --worker a)
[ "$(echo "$OUT" | grep -c 'dry-run')" = 2 ] && ok "세션 2개 → run 2번" || bad "세션 분리" "$OUT"

# 6. 단일 일꾼: 임대를 가진 일꾼이 있으면 다른 일꾼은 busy(exit 3)
sql "INSERT OR REPLACE INTO lease VALUES('main','other',$((T0+1000)))"
OUT=$($AI --now $((T0+200)) work --worker b); RC=$?
[ "$RC" = 3 ] && has "$OUT" "busy" && ok "임대 중 → 다른 일꾼 busy(exit 3)" || bad "단일 일꾼" "rc=$RC $OUT"
# 임대가 만료되면 넘겨받는다
OUT=$($AI --now $((T0+2000)) work --worker b); RC=$?
[ "$RC" = 0 ] && ok "임대 만료 후 다른 일꾼이 인수" || bad "임대 만료" "rc=$RC $OUT"

# 7. 일꾼이 죽어 running 으로 남은 이벤트는 다음 일꾼이 되살린다
$AI --now $((T0+3000)) push --source crash --id 1 >/dev/null
sql "UPDATE events SET status='running', attempts=1, run_id='run-x' WHERE source='crash'"
OUT=$($AI --now $((T0+3100)) work --window 10s --worker c --dry-run)
has "$OUT" "recovered 1" && has "$OUT" "crash/1" && ok "죽은 일꾼의 이벤트 복구·재처리" || bad "복구" "$OUT"

# 8. 핸들러 실패: 재시도 후 max-attempts 에서 dead, status 에 이유가 보인다
$AI --now $((T0+4000)) push --source bad --id 1 >/dev/null
for i in 1 2 3; do $AI --now $((T0+4100+i*100)) work --window 0 --worker d --handler 'cat >/dev/null; echo boom >&2; exit 7' >/dev/null; done
OUT=$($AI status)
has "$OUT" "dead=1" && has "$OUT" "dead: bad/1" && has "$OUT" "exit 7: boom" && ok "3번 실패 → dead, 이유 기록" || bad "dead" "$OUT"
# 첫 실패는 pending 으로 돌아간다
$AI --now $((T0+5000)) push --source bad --id 2 >/dev/null
$AI --now $((T0+5100)) work --window 0 --worker d --handler 'exit 1' >/dev/null
[ "$(status_n pending)" = 1 ] && ok "1번 실패 → pending 으로 복귀" || bad "재시도 복귀" "$($AI status)"

# 9. 핸들러는 묶음 JSON 을 stdin 으로 받는다
$AI --now $((T0+6000)) push --source h --id 1 --payload '{"k":"v"}' >/dev/null
$AI --now $((T0+6100)) work --window 0 --worker e --handler "cat > $T/got.json" >/dev/null
python3 - "$T/got.json" <<'PY' && ok "핸들러 stdin: run_id·session·events[payload]" || bad "핸들러 stdin" "$(cat $T/got.json 2>&1)"
import json,sys
d=json.load(open(sys.argv[1]))
ev=[e for e in d["events"] if e["source"]=="h"]
assert d["session"]=="main" and d["run_id"].startswith("run-main@") and ev and ev[0]["payload"]=={"k":"v"} and ev[0]["attempts"]==1
PY

# 10. 실행 중 도착한 이벤트는 끼어들지 않고 다음 run 으로 간다
sql "DELETE FROM events"
$AI --now $((T0+7000)) push --source m --id 1 >/dev/null
$AI --now $((T0+7100)) work --window 0 --worker f --handler "python3 agent_inbox.py --db $T/t.db --now $((T0+7100)) push --source m --id 2 >/dev/null; cat >/dev/null" >/dev/null
[ "$(status_n pending)" = 1 ] && [ "$(status_n done)" = 1 ] && ok "run 중 도착한 이벤트는 pending 으로 남음" || bad "run 중 도착" "$($AI status)"

# 11. 타이머: follow-up 은 한 번만, tick 은 run 을 시작하지 않는다
D="$T/t2.db"; A2="python3 agent_inbox.py --db $D"
$A2 --now $T0 timer add --name check-reply --in 30m --payload '{"thread":"T1"}' >/dev/null
OUT=$($A2 --now $((T0+600)) tick); has "$OUT" "no due timers" && ok "만기 전 tick → 아무 일 없음" || bad "만기 전" "$OUT"
OUT=$($A2 --now $((T0+1900)) tick); has "$OUT" "check-reply → event queued" && ok "만기 후 tick → 이벤트 생성" || bad "만기 후" "$OUT"
OUT=$($A2 --now $((T0+2000)) tick); has "$OUT" "no due timers" && ok "follow-up 은 한 번만" || bad "follow-up 반복" "$OUT"
[ "$($A2 status | sed -n 's/^events: pending=\([0-9]*\).*/\1/p')" = 1 ] && ok "tick 은 이벤트만 쌓고 run 은 안 함(pending 1)" || bad "tick→run" "$($A2 status)"
OUT=$($A2 --now $((T0+2100)) work --window 0 --worker g --dry-run); has "$OUT" "timer/check-reply@" && ok "일꾼이 타이머 이벤트를 처리" || bad "타이머 처리" "$OUT"

# 12. 반복 스케줄: 놓친 주기는 이벤트 하나로 합치고 다음 만기를 앞으로 당긴다
$A2 --now $T0 timer add --name daily --at $((T0+100)) --every 1d >/dev/null
OUT=$($A2 --now $((T0+100+3*86400+50)) tick); has "$OUT" "daily → event queued" && has "$OUT" "놓친 3회" && ok "3일 놓침 → 이벤트 1개 + 놓친 3회 표시" || bad "스케줄 합침" "$OUT"
NEXT=$(python3 -c "from datetime import datetime,timezone;print(datetime.fromtimestamp($T0+100+4*86400,timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))")
OUT=$($A2 timer list); has "$OUT" "due $NEXT" && ok "다음 만기는 now 이후로 전진" || bad "다음 만기" "$OUT"
OUT=$($A2 --now $((T0+100+3*86400+60)) tick); has "$OUT" "no due timers" && ok "같은 만기 재틱 → 이벤트 없음" || bad "재틱" "$OUT"

# 13. work --tick: 만기 이벤트를 같은 호출에서 처리
$A2 --now $((T0+10*86400)) timer add --name once --at $((T0+10*86400)) >/dev/null
OUT=$($A2 --now $((T0+10*86400+60)) work --tick --window 10s --worker h); has "$OUT" "once → event queued" && has "$OUT" "[dry-run]" && ok "work --tick 한 호출로 처리" || bad "work --tick" "$OUT"

echo; echo "$PASS passed, $FAIL failed"
[ "$FAIL" = 0 ]

#!/usr/bin/env bash
# red-start 테스트. 키·모델·네트워크 없이 돈다.
cd "$(dirname "$0")" || exit 2
HOOK="$PWD/red_start.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0

ok()  { PASS=$((PASS+1)); echo "ok   - $1"; }
bad() { FAIL=$((FAIL+1)); echo "FAIL - $1"; [ -n "${2:-}" ] && echo "       $2"; }
check() { # check "이름" 조건(0=참)
  if [ "$2" -eq 0 ]; then ok "$1"; else bad "$1" "${3:-}"; fi
}

# 훅 실행 도우미: run <프로젝트폴더> <stdin JSON> [env...]. 출력은 $OUT, 종료 코드는 $RC
run() {
  local dir="$1" input="$2"; shift 2
  OUT="$(cd "$dir" && printf '%s' "$input" | env -u RED_START_CMD -u RED_START_BUDGET "$@" CLAUDE_PROJECT_DIR="$dir" python3 -I "$HOOK" 2>&1)"
  RC=$?
}

mk() { mkdir -p "$TMP/$1"; echo "$TMP/$1"; }

# 1. 통과하는 프로젝트
P=$(mk pass); printf '#!/bin/sh\necho "all good"\nexit 0\n' > "$P/test.sh"
run "$P" '{"source":"startup"}'
check "통과: exit 0 + 'passed' 한 줄" $([ $RC -eq 0 ] && echo "$OUT" | grep -q 'passed (exit 0' && echo 0 || echo 1) "$OUT"
check "통과: 한 줄만 출력" $([ "$(echo "$OUT" | wc -l)" -eq 1 ] && echo 0 || echo 1) "$OUT"

# 2. 실패하는 프로젝트 (자동 감지: bash test.sh)
P=$(mk fail)
cat > "$P/test.sh" <<'EOF'
echo "ok   - fine"
echo "FAIL - checkout total"
echo "not ok 3 - cart empty"
printf '\033[31mFAILED tests/test_pay.py::test_refund\033[0m - assert 1 == 2\n'
echo "--- FAIL: TestLogin (0.00s)"
echo "ok   - also fine"
exit 1
EOF
run "$P" '{"source":"startup"}'
check "실패: 훅 자체는 exit 0" $([ $RC -eq 0 ] && echo 0 || echo 1)
check "실패: 종료 코드 1을 사실로 적는다" $(echo "$OUT" | grep -q 'exited 1 after' && echo 0 || echo 1) "$OUT"
check "실패: 네 가지 표기를 모두 잡는다(FAIL·not ok·FAILED·--- FAIL)" \
  $([ "$(echo "$OUT" | grep -cE 'checkout total|cart empty|test_refund|TestLogin')" -eq 4 ] && echo 0 || echo 1) "$OUT"
check "실패: 통과 줄은 넘기지 않는다" $(echo "$OUT" | grep -q 'fine' && echo 1 || echo 0) "$OUT"
check "실패: ANSI 색 코드를 제거한다" $(printf '%s' "$OUT" | grep -q $'\033' && echo 1 || echo 0)
check "실패: 개수 표기 '(4 of 4)'" $(echo "$OUT" | grep -q '(4 of 4)' && echo 0 || echo 1) "$OUT"

# 3. 문구는 사실만: 명령형·의무 표현이 없다
check "사실만: must/should/please/fix/you 없음" \
  $(echo "$OUT" | grep -qiE '\b(must|should|please|fix|you|need to)\b' && echo 1 || echo 0) "$OUT"

# 4. 실패 줄 상한과 전체 글자 상한
P=$(mk many)
cat > "$P/test.sh" <<'EOF'
i=1
while [ $i -le 60 ]; do
  echo "FAILED tests/test_$i.py::test_case_$i - $(printf 'x%.0s' $(seq 1 400))"
  i=$((i+1))
done
exit 1
EOF
run "$P" '{"source":"resume"}'
check "상한: 줄 15개만 보인다" $([ "$(echo "$OUT" | grep -c 'FAILED tests/')" -eq 15 ] && echo 0 || echo 1) "$(echo "$OUT" | grep -c 'FAILED tests/')"
check "상한: '45 more not shown' 안내" $(echo "$OUT" | grep -q '45 more not shown' && echo 0 || echo 1)
check "상한: 줄당 200자 이하(들여쓰기 포함 204)" $([ "$(echo "$OUT" | awk '{ if (length($0)>m) m=length($0) } END {print m}')" -le 204 ] && echo 0 || echo 1)
check "상한: 전체 10,000자 미만" $([ ${#OUT} -lt 10000 ] && echo 0 || echo 1) "${#OUT}자"

# 5. 설정 파일의 max_chars도 9,500을 못 넘는다(1만 자 상한 보호)
mkdir -p "$P/.claude"; echo '{"max_chars": 99999, "max_fails": 200, "max_line": 2000}' > "$P/.claude/red-start.json"
run "$P" '{"source":"resume"}'
check "상한: 설정을 99999로 올려도 1만 자 미만" $([ ${#OUT} -lt 10000 ] && echo 0 || echo 1) "${#OUT}자"

# 6. 시간 초과: 상태 모름 + 자식 프로세스 정리
P=$(mk slow)
cat > "$P/test.sh" <<EOF
( sleep 2; touch "$TMP/orphan" ) &
sleep 30
EOF
start=$SECONDS
run "$P" '{"source":"startup"}' RED_START_BUDGET=1
elapsed=$((SECONDS-start))
check "시간 초과: exit 0" $([ $RC -eq 0 ] && echo 0 || echo 1)
check "시간 초과: '상태 모름'을 사실로 적는다" $(echo "$OUT" | grep -q 'status is unknown' && echo 0 || echo 1) "$OUT"
check "시간 초과: 예산 근처(<6초)에 끝난다" $([ $elapsed -lt 6 ] && echo 0 || echo 1) "${elapsed}초"
sleep 3
check "시간 초과: 자식(백그라운드)까지 죽였다" $([ -e "$TMP/orphan" ] && echo 1 || echo 0)

# 7. source 필터: clear·compact는 조용히 건너뛴다. resume은 돈다
P=$(mk fail)
for s in clear compact; do
  run "$P" "{\"source\":\"$s\"}"
  check "source=$s: 출력 없음·exit 0" $([ $RC -eq 0 ] && [ -z "$OUT" ] && echo 0 || echo 1) "$OUT"
done
run "$P" '{"source":"resume"}'
check "source=resume: 다시 돈다" $(echo "$OUT" | grep -q 'exited 1' && echo 0 || echo 1)

# 8. 깨진 입력에서도 exit 0 (hook-manners 규칙 1)
P=$(mk pass)
for bad_in in '' 'not json' 'null' '[]' '{"source":42}' '{"cwd":123}'; do
  run "$P" "$bad_in"
  check "깨진 입력 [$bad_in]: exit 0" $([ $RC -eq 0 ] && echo 0 || echo 1) "$OUT"
done

# 9. 명령 우선순위: RED_START_CMD > 설정 파일 > 자동 감지
P=$(mk prio); echo 'echo auto; exit 0' > "$P/test.sh"
mkdir -p "$P/.claude"; echo '{"cmd":"echo from-config; exit 3"}' > "$P/.claude/red-start.json"
run "$P" '{"source":"startup"}'
check "우선순위: 설정 파일이 자동 감지를 이긴다" $(echo "$OUT" | grep -q 'echo from-config' && echo "$OUT" | grep -q 'exited 3' && echo 0 || echo 1) "$OUT"
run "$P" '{"source":"startup"}' RED_START_CMD="exit 7"
check "우선순위: RED_START_CMD가 설정 파일을 이긴다" $(echo "$OUT" | grep -q 'exited 7' && echo 0 || echo 1) "$OUT"

# 10. 명령이 없으면 조용히 끝
P=$(mk empty)
run "$P" '{"source":"startup"}'
check "명령 없음: 출력 없음·exit 0" $([ $RC -eq 0 ] && [ -z "$OUT" ] && echo 0 || echo 1) "$OUT"

# 11. 인식 못 하는 실패는 마지막 5줄을 보여 준다
P=$(mk odd); printf 'for i in 1 2 3 4 5 6 7; do echo "line $i"; done\nexit 4\n' > "$P/test.sh"
run "$P" '{"source":"startup"}'
check "미인식 실패: 안내 + 마지막 5줄(line 3~7)" \
  $(echo "$OUT" | grep -q 'No line matched' && echo "$OUT" | grep -q 'line 7' && echo "$OUT" | grep -q 'line 3' && ! echo "$OUT" | grep -q 'line 2' && echo 0 || echo 1) "$OUT"

# 12. --json: additionalContext 형태
P=$(mk fail)
OUT="$(cd "$P" && echo '{"source":"startup"}' | CLAUDE_PROJECT_DIR="$P" python3 -I "$HOOK" --json)"
echo "$OUT" | python3 -I -c '
import json,sys
d=json.loads(sys.stdin.read())["hookSpecificOutput"]
assert d["hookEventName"]=="SessionStart" and "exited 1" in d["additionalContext"]
' && ok "--json: hookSpecificOutput.additionalContext" || bad "--json 형태" "$OUT"

# 13. --dry-run: 명령을 실행하지 않는다
P=$(mk dry); echo "touch '$TMP/dry-ran'" > "$P/test.sh"
OUT="$(cd "$P" && CLAUDE_PROJECT_DIR="$P" python3 -I "$HOOK" --dry-run)"
check "dry-run: 명령 출처를 보여 준다" $(echo "$OUT" | grep -q 'bash test.sh.*자동 감지' && echo 0 || echo 1) "$OUT"
check "dry-run: 실제로 실행하지 않았다" $([ -e "$TMP/dry-ran" ] && echo 1 || echo 0)

# 14. --print-settings: 유효한 JSON, SessionStart + startup|resume + timeout
python3 -I "$HOOK" --print-settings | python3 -I -c '
import json,sys
h=json.load(sys.stdin)["hooks"]["SessionStart"][0]
assert h["matcher"]=="startup|resume" and h["hooks"][0]["timeout"]>45
' && ok "--print-settings: 설정 조각이 유효하고 timeout이 예산(45s)보다 크다" || bad "--print-settings"

echo
echo "통과 $PASS · 실패 $FAIL"
[ "$FAIL" -eq 0 ]

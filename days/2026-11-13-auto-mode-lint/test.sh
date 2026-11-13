#!/usr/bin/env bash
# auto-mode-lint 테스트: 키·모델·네트워크 없이 돈다. 이 폴더에서 `bash test.sh`.
cd "$(dirname "$0")" || exit 1
export PYTHONDONTWRITEBYTECODE=1
PY="python3 auto_mode_lint.py"
PASS=0; FAIL=0
ok()  { echo "ok   - $1"; PASS=$((PASS+1)); }
bad() { echo "FAIL - $1"; [ -n "$2" ] && echo "       $2"; FAIL=$((FAIL+1)); }

# 1~9. 고정 설정 파일: 종료 코드와 걸린 규칙 코드 목록(중복 제거, 정렬)
check() { # 이름 기대exit "기대 코드들"
  OUT=$($PY "fixtures/$1.json" --json 2>&1); RC=$?
  CODES=$(echo "$OUT" | python3 -c 'import json,sys; print(" ".join(sorted({f["code"] for f in json.load(sys.stdin)["findings"]})))' 2>/dev/null)
  [ "$RC" = "$2" ] && [ "$CODES" = "$3" ] && ok "$1 → exit $2, [$3]" || bad "$1" "rc=$RC codes=[$CODES] 기대 exit $2 [$3]"
}
check clean 0 ""
check placeholder 1 "AM002"
check no-defaults 1 "AM001"
check typo 1 "AM001 AM006"
check badtypes 1 "AM004 AM005"
check patterns 0 "AM007"
check noauto 0 ""
check notobject 1 "AM004"
check broken 2 "AM000"

# 10. 없는 파일은 읽기 실패(exit 2)
$PY fixtures/nope.json >/dev/null 2>&1; [ "$?" = 2 ] && ok "없는 파일 → exit 2" || bad "없는 파일"

# 11. 섹션별 심각도: soft_deny·hard_deny 는 오류, allow 는 경고, environment 는 참고
OUT=$($PY fixtures/no-defaults.json --json)
echo "$OUT" | python3 -c '
import json,sys
d=json.load(sys.stdin)
m={f["where"].split(".")[-1]:f["severity"] for f in d["findings"] if f["code"]=="AM001"}
assert m=={"soft_deny":"error","hard_deny":"error","allow":"warn","environment":"info"}, m' \
  && ok "섹션별 심각도(soft/hard=오류, allow=경고, environment=참고)" || bad "섹션별 심각도" "$OUT"

# 12. --strict: 경고만 있는 파일도 실패
$PY fixtures/patterns.json --strict >/dev/null; [ "$?" = 1 ] && ok "--strict 는 경고도 exit 1" || bad "--strict"

# 13. 프로젝트 설정의 autoMode 는 AM003(분류기가 읽지 않음)
OUT=$($PY fixtures/proj/.claude/settings.local.json --json); RC=$?
echo "$OUT" | python3 -c '
import json,sys
c={f["code"] for f in json.load(sys.stdin)["findings"]}
assert "AM003" in c and "AM002" in c, c' && [ "$RC" = 1 ] && ok "settings.local.json 의 autoMode → AM003 + 내용 점검도 함께" || bad "프로젝트 범위" "rc=$RC $OUT"

# 14. --scope 로 범위를 강제하면 같은 내용도 AM003 이 사라진다
OUT=$($PY fixtures/proj/.claude/settings.local.json --scope user --json)
echo "$OUT" | python3 -c '
import json,sys
c={f["code"] for f in json.load(sys.stdin)["findings"]}
assert "AM003" not in c and "AM002" in c, c' && ok "--scope user 로 범위 지정" || bad "--scope" "$OUT"

# 15. 인자 없이 실행: 홈의 ~/.claude/settings.json + 현재 폴더의 .claude/settings.local.json 을 찾는다
OUT=$(cd fixtures/proj && python3 ../../auto_mode_lint.py --home ../home --json)
echo "$OUT" | python3 -c '
import json,sys
d=json.load(sys.stdin)
names=sorted(c["file"].replace("\\\\","/").split("/")[-1] for c in d["checked"])
assert names==["settings.json","settings.local.json"], names' && ok "인자 없이 실행 시 홈 설정 + 프로젝트 설정을 탐색" || bad "기본 탐색" "$OUT"

# 16. 설정 파일이 하나도 없으면 안내만 하고 exit 0
EMPTY=$(mktemp -d); trap 'rm -rf "$EMPTY"' EXIT
OUT=$(cd "$EMPTY" && python3 "$OLDPWD/auto_mode_lint.py" --home "$EMPTY"); RC=$?
[ "$RC" = 0 ] && echo "$OUT" | grep -q "점검할 설정 파일이 없다" && ok "설정 파일 없음 → 안내 + exit 0" || bad "설정 파일 없음" "rc=$RC $OUT"

# 17. 읽기 전용: 점검이 입력 파일을 바꾸지 않는다
H1=$(sha256sum fixtures/no-defaults.json | cut -d' ' -f1); $PY fixtures/no-defaults.json >/dev/null
H2=$(sha256sum fixtures/no-defaults.json | cut -d' ' -f1); [ "$H1" = "$H2" ] && ok "입력 파일을 바꾸지 않는다" || bad "읽기 전용"

# 18. 사람이 읽는 출력에 오류 개수 요약이 들어간다
$PY fixtures/placeholder.json | grep -q "오류 1 · 경고 0 → exit 1" && ok "텍스트 출력 요약 줄" || bad "텍스트 요약"

echo
echo "통과 $PASS · 실패 $FAIL"
[ "$FAIL" = 0 ]

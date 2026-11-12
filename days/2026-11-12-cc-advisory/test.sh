#!/usr/bin/env bash
# cc-advisory 테스트: 키·모델·네트워크 없이 돈다. 이 폴더에서 `bash test.sh`.
cd "$(dirname "$0")" || exit 1
export PYTHONDONTWRITEBYTECODE=1
PY="python3 cc_advisory.py"
PASS=0; FAIL=0
ok()  { echo "ok   - $1"; PASS=$((PASS+1)); }
bad() { echo "FAIL - $1"; [ -n "$2" ] && echo "       $2"; FAIL=$((FAIL+1)); }
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

# 1~6. 버전 경계: 수정 버전 미만만 걸린다
check_ver() { # 버전 기대exit 기대개수
  OUT=$($PY --version "$1" --json 2>&1); RC=$?
  N=$(echo "$OUT" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["advisories"]))' 2>/dev/null)
  [ "$RC" = "$2" ] && [ "$N" = "$3" ] && ok "버전 $1 → exit $2, 공지 $3개" || bad "버전 $1" "rc=$RC n=$N out=$OUT"
}
check_ver 2.1.128 1 2
check_ver 2.1.129 1 1
check_ver 2.1.250 1 1
check_ver 2.1.251 0 0
check_ver "2.1.322 (Claude Code)" 0 0
check_ver 2.0.999 1 2
check_ver 2.2.0 0 0
check_ver 3.0.0 0 0
check_ver 1.99.99 1 2

# 10. 숫자 비교(문자열 비교 아님): 2.1.99 < 2.1.129
OUT=$($PY --version 2.1.99 --json); echo "$OUT" | python3 -c 'import json,sys; assert json.load(sys.stdin)["vulnerable"]' && ok "2.1.99는 2.1.129 미만(숫자 비교)" || bad "숫자 비교"

# 11. 높은 수정 버전 공지가 먼저 나온다
OUT=$($PY --version 2.1.100 --json); echo "$OUT" | python3 -c '
import json,sys
a=json.load(sys.stdin)["advisories"]
assert [x["id"] for x in a]==["GHSA-5xjx-9qx6-jcrv","GHSA-5j29-h97v-84ch"], a' && ok "수정 버전 높은 순 정렬" || bad "정렬" "$OUT"

# 12. 알 수 없는 버전 → exit 2
$PY --version "not-a-version" >/dev/null 2>"$TMP/err"; RC=$?
[ "$RC" = "2" ] && ok "버전 못 읽으면 exit 2" || bad "exit 2" "rc=$RC"

# 13. 평문 출력은 사실 문장(명령조 없음)
OUT=$($PY --version 2.1.100)
echo "$OUT" | grep -q "CVE-2026-88968" && echo "$OUT" | grep -q "fixed in 2.1.251" && ok "출력에 CVE·수정 버전이 있다" || bad "출력 내용" "$OUT"
echo "$OUT" | grep -qiE '\b(must|should|please|you)\b' && bad "명령조 문구" "$OUT" || ok "사실만: must/should/please/you 없음"

# 14. 통과 문구
OUT=$($PY --version 2.1.322); echo "$OUT" | grep -q "모두 수정 버전 이상" && ok "통과 문구" || bad "통과 문구" "$OUT"

# 15. --list
OUT=$($PY --list); [ "$(echo "$OUT" | wc -l)" = "2" ] && echo "$OUT" | grep -q "GHSA-5j29-h97v-84ch" && ok "--list: 공지 2줄" || bad "--list" "$OUT"

# 16. 사용자 표 확장: 내 공지 한 줄 추가
cat > "$TMP/extra.json" <<'J'
{"advisories":[{"id":"TEST-1","cve":"CVE-0","severity":"Low","fixed":"2.1.400","title":"test only"}]}
J
OUT=$($PY --version 2.1.322 --table "$TMP/extra.json" --json); echo "$OUT" | python3 -c '
import json,sys
d=json.load(sys.stdin); assert d["checked"]==3 and [a["id"] for a in d["advisories"]]==["TEST-1"], d' && ok "--table: 기본 표에 더해진다(3개 중 1개 해당)" || bad "--table 확장" "$OUT"

# 17. 표 교체(extend false)
echo '{"extend":false,"advisories":[{"id":"ONLY","fixed":"9.0.0","title":"x"}]}' > "$TMP/only.json"
OUT=$($PY --version 2.1.1 --table "$TMP/only.json" --json); echo "$OUT" | python3 -c '
import json,sys
d=json.load(sys.stdin); assert d["checked"]==1, d' && ok "--table extend=false: 표 교체" || bad "표 교체" "$OUT"

# 18. 깨진 표 → exit 2, 스택트레이스 없이
echo '{not json' > "$TMP/bad.json"
$PY --version 2.1.1 --table "$TMP/bad.json" >/dev/null 2>"$TMP/err"; RC=$?
[ "$RC" = "2" ] && ! grep -q Traceback "$TMP/err" && ok "깨진 표: exit 2, 스택트레이스 없음" || bad "깨진 표" "rc=$RC $(cat "$TMP/err")"
echo '[{"id":"X","fixed":"abc"}]' > "$TMP/nofix.json"
$PY --version 2.1.1 --table "$TMP/nofix.json" >/dev/null 2>"$TMP/err"; RC=$?
[ "$RC" = "2" ] && ok "fixed 없는 공지: exit 2" || bad "fixed 검증" "rc=$RC"

# 19. 가짜 claude를 PATH에 두고 실제 --version 경로 시험
mkdir -p "$TMP/bin"; printf '#!/bin/sh\necho "2.1.200 (Claude Code)"\n' > "$TMP/bin/claude"; chmod +x "$TMP/bin/claude"
PATH="$TMP/bin:$PATH" $PY >/dev/null; RC=$?
[ "$RC" = "1" ] && ok "가짜 claude 2.1.200 → 미달 exit 1" || bad "claude --version 경로" "rc=$RC"
printf '#!/bin/sh\necho "2.1.322 (Claude Code)"\n' > "$TMP/bin/claude"
PATH="$TMP/bin:$PATH" $PY >/dev/null; RC=$?
[ "$RC" = "0" ] && ok "가짜 claude 2.1.322 → exit 0" || bad "claude 최신" "rc=$RC"
printf '#!/bin/sh\necho "garbage"\n' > "$TMP/bin/claude"
PATH="$TMP/bin:$PATH" $PY >/dev/null 2>&1; RC=$?
[ "$RC" = "2" ] && ok "claude가 이상한 출력 → exit 2" || bad "이상한 출력" "rc=$RC"

# 20. 훅: 미달이면 hookSpecificOutput JSON
OUT=$(echo '{"source":"startup"}' | $PY --hook --version 2.1.100); RC=$?
[ "$RC" = "0" ] && echo "$OUT" | python3 -c '
import json,sys
d=json.load(sys.stdin)["hookSpecificOutput"]
assert d["hookEventName"]=="SessionStart" and "2.1.251" in d["additionalContext"]' && ok "훅: 미달이면 additionalContext JSON, exit 0" || bad "훅 JSON" "rc=$RC $OUT"

# 21. 훅: 수정 버전 이상이면 출력 없음
OUT=$(echo '{}' | $PY --hook --version 2.1.322); RC=$?
[ "$RC" = "0" ] && [ -z "$OUT" ] && ok "훅: 최신이면 조용함, exit 0" || bad "훅 조용함" "rc=$RC out=$OUT"

# 22. 훅: 버전을 알 수 없어도(claude 없음) 조용히 exit 0
PYBIN=$(command -v python3)
OUT=$(echo '{}' | PATH="/nonexistent" "$PYBIN" cc_advisory.py --hook); RC=$?
[ "$RC" = "0" ] && [ -z "$OUT" ] && ok "훅: claude 없음 → 조용히 exit 0" || bad "훅 claude 없음" "rc=$RC out=$OUT"

# 23. 훅: 깨진 stdin·깨진 표도 exit 0
OUT=$(printf '\xff\xfe not json' | $PY --hook --version 2.1.100 2>&1); RC=$?
[ "$RC" = "0" ] && ok "훅: 깨진 stdin도 exit 0" || bad "훅 깨진 입력" "rc=$RC"
OUT=$(echo '{}' | $PY --hook --version 2.1.100 --table "$TMP/bad.json" 2>&1); RC=$?
[ "$RC" = "0" ] && [ -z "$OUT" ] && ok "훅: 깨진 표도 조용히 exit 0" || bad "훅 깨진 표" "rc=$RC out=$OUT"

# 24. 훅 --plain
OUT=$(echo '{}' | $PY --hook --plain --version 2.1.100); echo "$OUT" | head -1 | grep -q "^Installed Claude Code is 2.1.100\." && ok "훅 --plain: 일반 텍스트" || bad "훅 plain" "$OUT"

# 25. --print-settings가 유효하고 timeout이 있다
$PY --print-settings | python3 -c '
import json,sys
d=json.load(sys.stdin)["hooks"]["SessionStart"][0]
assert d["matcher"]=="startup" and d["hooks"][0]["timeout"]>=10 and "--hook" in d["hooks"][0]["command"]' && ok "--print-settings: 유효한 SessionStart 조각" || bad "--print-settings"

# 26. 내장 표 자체 검증: 모든 항목에 id·fixed·title·url
python3 -c '
import cc_advisory as c
for a in c.BUILTIN:
    assert c.parse_version(a["fixed"]) and a["id"] and a["title"] and a["url"].startswith("https://github.com/anthropics/claude-code/security/advisories/"), a
' && ok "내장 표: 항목 필드 완비" || bad "내장 표"

# 27. 이 기기의 실제 claude (있으면)
if command -v claude >/dev/null 2>&1; then
  OUT=$($PY); RC=$?; echo "info - 이 기기 claude: $(claude --version 2>&1 | head -1) → exit $RC"
  { [ "$RC" = "0" ] || [ "$RC" = "1" ]; } && ok "실제 claude --version 읽기 성공" || bad "실제 claude" "rc=$RC $OUT"
else
  echo "skip - claude 없음: 실제 --version 시험 건너뜀"
fi

echo
echo "통과 $PASS · 실패 $FAIL"
[ "$FAIL" = "0" ]

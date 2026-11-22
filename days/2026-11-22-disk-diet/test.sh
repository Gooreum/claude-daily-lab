#!/usr/bin/env bash
# 키·모델 없이 도는 테스트. 이 폴더에서 `bash test.sh`.
set -u
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "ok   $1"; }
bad() { fail=$((fail+1)); echo "FAIL $1"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
dd_() { $PY disk_diet.py "$@"; }
has() { echo "$OUT" | grep -q -- "$1"; }
jq_() { echo "$JSON" | $PY -I -c "import json,sys; r=json.load(sys.stdin); print($1)"; }

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
$PY make_fixture.py "$TMP" || { echo "FAIL 픽스처 생성"; exit 1; }
HOMEDIR="$TMP/home"

# ---- audit: 숫자가 정확한가
JSON=$(dd_ audit --home "$HOMEDIR" --json); rc=$?
check "audit --json: exit 0" '[ $rc -eq 0 ]'
check "대화 기록 파일 3개" '[ "$(jq_ "r[\"transcripts\"][\"files\"]")" = "3" ]'
check "이미지 3장 · base64 501000자(중첩 tool_result 포함)" \
  '[ "$(jq_ "(r[\"transcripts\"][\"images\"], r[\"transcripts\"][\"image_bytes\"])")" = "(3, 501000)" ]'
check "이미지 표시가 있는 깨진 줄 1개를 따로 센다" '[ "$(jq_ "r[\"transcripts\"][\"broken_lines\"]")" = "1" ]'
check "가장 큰 세션이 맨 위(이미지 많은 aaaa)" '[ "$(jq_ "r[\"transcripts\"][\"top\"][0][\"path\"].split(\"/\")[-1]")" = "aaaa.jsonl" ]'
check "실행 파일 4개 중 최신 2개 유지 → 옛 버전 2개 100000바이트" \
  '[ "$(jq_ "(len(r[\"versions\"][\"stale\"]), r[\"reclaimable\"][\"versions\"])")" = "(2, 100000)" ]'
check "옛 버전은 1.0.1·1.0.2" '[ "$(jq_ "\" \".join(sorted(e[\"name\"] for e in r[\"versions\"][\"stale\"]))")" = "1.0.1 1.0.2" ]'
check "오래된 worktree는 old-wt뿐" '[ "$(jq_ "\" \".join(w[\"name\"] for w in r[\"worktrees\"][\"stale\"])")" = "old-wt" ]'
check "old-wt 크기 102000(심볼릭 링크 900000 제외)" '[ "$(jq_ "r[\"worktrees\"][\"stale\"][0][\"size\"]")" = "102000" ]'
check "old-wt는 링크를 만들어도 40일 전으로 본다" '[ "$(jq_ "r[\"worktrees\"][\"stale\"][0][\"idle_days\"]")" = "40" ]'
check "되찾을 후보 합계 = 이미지+버전+worktree" \
  '[ "$(jq_ "r[\"reclaimable\"][\"total\"]")" = "$((501000+100000+102000))" ]'
check "--keep-versions 4면 옛 버전 0개" '[ "$(dd_ audit --home "$HOMEDIR" --json --keep-versions 4 | $PY -I -c "import json,sys;print(len(json.load(sys.stdin)[\"versions\"][\"stale\"]))")" = "0" ]'
check "--days 50이면 old-wt도 후보가 아님" '[ "$(dd_ audit --home "$HOMEDIR" --json --days 50 | $PY -I -c "import json,sys;print(len(json.load(sys.stdin)[\"worktrees\"][\"stale\"]))")" = "0" ]'

# ---- 표·한 줄
OUT=$(dd_ audit --home "$HOMEDIR")
check "표: 네 자리가 모두 나온다" 'has "대화 기록" && has "worktree" && has "옛 실행 파일" && has "되찾을 수 있는 후보"'
check "표: 건드리지 않는 곳 안내" 'has "건드리지 않는 곳"'
check "표: 깨진 줄 주의 문구" 'has "JSON으로 읽히지 않는 줄이 1개"'
OUT=$(dd_ audit --home "$HOMEDIR" --oneline)
check "--oneline은 정확히 한 줄" '[ "$(echo "$OUT" | wc -l)" = "1" ] && has "disk-diet: ~/.claude"'

# ---- 예산
dd_ audit --home "$HOMEDIR" --oneline --budget-mb 0.1 >/dev/null 2>&1; rc=$?
check "--budget-mb 0.1 초과 → exit 1" '[ $rc -eq 1 ]'
dd_ audit --home "$HOMEDIR" --oneline --budget-mb 100 >/dev/null 2>&1; rc=$?
check "--budget-mb 100 이내 → exit 0" '[ $rc -eq 0 ]'

# ---- 빈 홈·없는 폴더
mkdir -p "$TMP/empty"
OUT=$(dd_ audit --home "$TMP/empty"); rc=$?
check "빈 홈: exit 0, 후보 0B" '[ $rc -eq 0 ] && has "되찾을 수 있는 후보: 0B"'
OUT=$(dd_ plan --home "$TMP/empty")
check "빈 홈 plan: 후보 없음 안내" 'has "정리할 후보가 없다"'

# ---- plan: 출력만, 보호 대상은 없음, 아무것도 지우지 않음
before=$(find "$HOMEDIR" -type f | sort | xargs cat | md5sum)
OUT=$(dd_ plan --home "$HOMEDIR")
after=$(find "$HOMEDIR" -type f | sort | xargs cat | md5sum)
check "plan 뒤 파일 내용 그대로" '[ "$before" = "$after" ]'
check "plan: 옛 버전 1.0.1·1.0.2 rm 줄" 'has "rm -rf -- .*versions/1.0.1" && has "rm -rf -- .*versions/1.0.2"'
check "plan: 최신 버전 1.0.3·1.0.4는 안 나온다" '! has "versions/1.0.3" && ! has "versions/1.0.4"'
check "plan: old-wt만, new-wt는 안 나온다" 'has "worktrees/old-wt" && ! has "worktrees/new-wt"'
check "plan: settings.json·.credentials.json은 rm 대상이 아니다" '! echo "$OUT" | grep "^rm " | grep -qE "settings.json|credentials"'
check "plan: 이미지 있는 세션은 slim 안내" 'has "slim" && has "aaaa.jsonl"'
check "plan: rm은 두 버전 + worktree 1개 = 3줄" '[ "$(echo "$OUT" | grep -c "^rm ")" = "3" ]'

# ---- slim
SRC="$HOMEDIR/.claude/projects/-repo-a/aaaa.jsonl"
src_sum=$(md5sum < "$SRC")
OUT=$(dd_ slim "$SRC" -o "$TMP/aaaa.slim"); rc=$?
check "slim: exit 0" '[ $rc -eq 0 ]'
check "slim: 이미지 2장 제거 보고" 'has "이미지 2장 제거"'
check "slim 뒤 원본 그대로" '[ "$(md5sum < "$SRC")" = "$src_sum" ]'
check "slim 사본은 원본보다 작다(50만 자 이상 줄어듦)" '[ $(( $(wc -c < "$SRC") - $(wc -c < "$TMP/aaaa.slim") )) -gt 450000 ]'
check "slim 사본에 base64 데이터가 없다(깨진 줄 제외)" '[ "$(grep -c "AAAAAAAA" "$TMP/aaaa.slim")" = "0" ]'
check "slim 사본에 제거 표시와 한글이 남는다" 'grep -q "이미지 제거 image/png base64 300000자" "$TMP/aaaa.slim" && grep -q "화면 봐 줘" "$TMP/aaaa.slim"'
check "slim 사본에 중첩 이미지 표시(jpeg 200000자)" 'grep -q "이미지 제거 image/jpeg base64 200000자" "$TMP/aaaa.slim"'
check "slim: 사본 줄 수 = 원본 줄 수" '[ "$(wc -l < "$SRC")" = "$(wc -l < "$TMP/aaaa.slim")" ]'
check "slim: 이미지 없는 줄은 바이트까지 같다(2번째 줄)" '[ "$(sed -n 2p "$SRC")" = "$(sed -n 2p "$TMP/aaaa.slim")" ]'
check "slim: 깨진 줄도 그대로(4번째 줄)" '[ "$(sed -n 4p "$SRC")" = "$(sed -n 4p "$TMP/aaaa.slim")" ]'
check "slim: 읽을 수 있는 줄은 모두 올바른 JSON" '$PY -I -c "
import json,sys
ls=open(sys.argv[1],encoding=\"utf-8\").read().splitlines()
[json.loads(l) for l in ls[:3]]
" "$TMP/aaaa.slim"'
check "slim 사본에 audit을 다시 돌리면 이미지 0장" \
  '[ "$($PY -I -c "
import sys; sys.path.insert(0,\".\")
import disk_diet as d
print(d.scan_jsonl(sys.argv[1])[0])" "$TMP/aaaa.slim")" = "0" ]'
dd_ slim "$SRC" -o "$TMP/aaaa.slim" >/dev/null 2>&1; rc=$?
check "slim: 이미 있는 출력은 덮어쓰지 않는다(exit 2)" '[ $rc -eq 2 ]'
dd_ slim "$SRC" -o "$SRC" >/dev/null 2>&1; rc=$?
check "slim: 출력이 원본과 같으면 거부(exit 2)" '[ $rc -eq 2 ] && [ "$(md5sum < "$SRC")" = "$src_sum" ]'
dd_ slim "$TMP/nope.jsonl" -o "$TMP/x" >/dev/null 2>&1; rc=$?
check "slim: 없는 파일은 exit 2" '[ $rc -eq 2 ]'
OUT=$(dd_ slim "$HOMEDIR/.claude/projects/-repo-b/bbbb.jsonl" -o "$TMP/bbbb.slim")
check "slim: 이미지 없는 파일은 0장·사본이 바이트까지 같다" 'has "이미지 0장 제거" && cmp -s "$HOMEDIR/.claude/projects/-repo-b/bbbb.jsonl" "$TMP/bbbb.slim"'

# ---- 도움말·잘못된 호출
dd_ >/dev/null 2>&1; rc=$?
check "인자 없이 실행: 도움말과 exit 2" '[ $rc -eq 2 ]'

echo
echo "통과 $pass · 실패 $fail"
[ $fail -eq 0 ]

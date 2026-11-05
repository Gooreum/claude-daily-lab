#!/usr/bin/env bash
# 키·모델·네트워크 없이 도는 테스트. 이 폴더에서 `bash test.sh`.
set -u
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "ok   $1"; }
bad() { fail=$((fail+1)); echo "FAIL $1"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
dl() { $PY -I dream_lint.py "$@"; }

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

# 깨끗한 폴더: 오류·경고 없음, [[링크]] 미작성은 참고(info)만
OUT=$(dl fixtures/good); rc=$?
check "good: exit 0"                          '[ $rc -eq 0 ]'
check "good: 미작성 링크는 INFO"               'echo "$OUT" | grep -q "^INFO  link-pending.*feedback-oncall"'
check "good: 파일 4개 집계"                    'echo "$OUT" | grep -q "기억 파일 4개 · 오류 0 · 경고 0 · 참고 1"'

# 나쁜 폴더: 코드별로 잡히는지 (비밀값 fixture는 실행 중에 조립해 저장소에 남기지 않는다)
cp -r fixtures/bad "$TMP/bad"
SECRET="sk-""ant-api03-ABCDEFGHIJKLMNOP"
sed -i "s/__SECRET__/$SECRET/" "$TMP/bad/feedback-key.md"
OUT=$(dl "$TMP/bad"); rc=$?
check "bad: exit 2"                           '[ $rc -eq 2 ]'
check "bad: 없는 파일을 가리키는 색인"          'echo "$OUT" | grep -q "^ERROR index-dangling.*gone.md"'
check "bad: 비밀값 패턴"                       'echo "$OUT" | grep -q "^ERROR secret.*feedback-key.md"'
check "bad: 비밀값 원문은 출력하지 않음"         '! echo "$OUT" | grep -q "ABCDEFGHIJKLMNOP"'
check "bad: 필수 항목 누락"                    'echo "$OUT" | grep -q "^ERROR missing-field.*nodesc.md.*description"'
check "bad: 프론트매터 없음"                   'echo "$OUT" | grep -q "^ERROR frontmatter.*orphan.md"'
check "bad: 잘못된 type"                      'echo "$OUT" | grep -q "^ERROR bad-type.*weird-type.md.*note"'
check "bad: 색인 형식 위반 줄 번호"             'echo "$OUT" | grep -q "^WARN  index-format.*MEMORY.md:7"'
check "bad: 색인에 없는 파일"                  'echo "$OUT" | grep -q "^WARN  not-indexed.*orphan.md"'
check "bad: Why/How 누락 2건"                  '[ $(echo "$OUT" | grep -c "missing-why.*project-late.md") -eq 2 ]'
check "bad: 상대 날짜"                         'echo "$OUT" | grep -q "^WARN  relative-date.*project-late.md.*다음 주"'
check "bad: 비슷한 설명 쌍"                    'echo "$OUT" | grep -q "^WARN  similar.*user-a.md.*user-b.md"'
check "bad: 집계 줄"                           'echo "$OUT" | grep -q "기억 파일 7개 · 오류 5 · 경고 7"'

# 옵션
OUT=$(dl "$TMP/bad" --json); check "--json: 파싱되고 counts.error=5" 'echo "$OUT" | $PY -I -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d[\"counts\"][\"error\"]==5 else 1)"'
mkdir "$TMP/warnonly"; cp fixtures/good/*.md "$TMP/warnonly/"; echo "- 형식 아닌 줄" >> "$TMP/warnonly/MEMORY.md"
dl "$TMP/warnonly" >/dev/null; rc=$?;            check "경고만 있으면 exit 1"            '[ $rc -eq 1 ]'
dl "$TMP/warnonly" --strict >/dev/null; rc=$?;   check "--strict: 경고도 exit 2"         '[ $rc -eq 2 ]'
dl "$TMP/warnonly" --max-line-len 20 >/dev/null; rc=$?; check "--max-line-len: 짧은 기준이면 긴 줄 경고" '[ $rc -eq 1 ]'
dl "$TMP/nope" >/dev/null 2>&1; rc=$?;           check "없는 폴더는 exit 3"             '[ $rc -eq 3 ]'

# 색인이 없는 폴더, 색인 줄 수 초과
mkdir "$TMP/noindex"; cp fixtures/good/user-role.md "$TMP/noindex/"
OUT=$(dl "$TMP/noindex"); rc=$?;                 check "MEMORY.md 없음: ERROR no-index exit 2" '[ $rc -eq 2 ] && echo "$OUT" | grep -q "^ERROR no-index"'
OUT=$(dl fixtures/good --max-index-lines 3); rc=$?; check "색인 줄 수 초과 경고"           'echo "$OUT" | grep -q "^WARN  index-long.*4줄"'

# 실제 이 세션의 기억 폴더가 있으면 읽기 전용으로 한 번 돌려 크래시만 확인 (결과 값은 보지 않는다)
REAL=$(ls -d "$HOME"/.claude/projects/*/memory 2>/dev/null | head -1)
if [ -n "$REAL" ] && [ -f "$REAL/MEMORY.md" ]; then dl "$REAL" >/dev/null 2>&1; rc=$?; check "실제 기억 폴더: 크래시 없음(exit<=2)" '[ $rc -le 2 ]'; fi

echo "---"; echo "통과 $pass · 실패 $fail"
[ $fail -eq 0 ]

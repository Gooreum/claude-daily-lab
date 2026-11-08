#!/usr/bin/env bash
# 키·모델·네트워크 없이 도는 테스트. 이 폴더에서 `bash test.sh`.
set -u
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "ok   $1"; }
bad() { fail=$((fail+1)); echo "FAIL $1"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
md() { $PY -I memory_drift.py "$@"; }

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

# 깨끗한 노트: 경고 0, 코드 펜스·drift:ignore 줄은 건너뜀
OUT=$(md fixtures/mem-good --repo fixtures/repo); rc=$?
check "good: exit 0"                         '[ $rc -eq 0 ]'
check "good: 6개 주장 모두 통과"               'echo "$OUT" | grep -q "대조한 주장 6개 · 건너뜀 0개 · 경고 0 · 참고 0"'
check "good: 코드 펜스 안은 검사 안 함"         '! echo "$OUT" | grep -q "not/in/code.py"'

# 낡은 노트: 해시 자리표시자는 실행 중에 채운다
cp -r fixtures/mem-stale "$TMP/stale"
sed -i 's/__FAKESHA__/deadbeefcafe1234/' "$TMP/stale/project-old.md"
OUT=$(md "$TMP/stale" --repo fixtures/repo); rc=$?
check "stale: exit 1"                        '[ $rc -eq 1 ]'
check "stale: 옮겨진 경로에 힌트"               'echo "$OUT" | grep -q "^WARN  path-missing.*lib/app.py.*src/app.py"'
check "stale: 지워진 문서 경로"                 'echo "$OUT" | grep -q "^WARN  path-missing.*docs/old-setup.md"'
check "stale: 지워진 스크립트 경로"             'echo "$OUT" | grep -q "^WARN  path-missing.*scripts/release.sh"'
check "stale: 없는 함수 이름"                  'echo "$OUT" | grep -q "^WARN  ident-missing.*retry_with_backoff()"'
check "stale: 없는 환경 변수"                  'echo "$OUT" | grep -q "^WARN  ident-missing.*APP_CACHE_DIR"'
check "stale: 없는 옵션은 INFO"               'echo "$OUT" | grep -q "^INFO  flag-missing.*--dry-run"'
check "stale: 없는 커밋 해시"                  'echo "$OUT" | grep -q "^WARN  sha-missing.*deadbeefcafe1234"'
check "stale: 줄 번호 표시"                    'echo "$OUT" | grep -q "project-old.md:9 "'
check "stale: 집계"                          'echo "$OUT" | grep -q "대조한 주장 7개 · 건너뜀 0개 · 경고 6 · 참고 1"'

# 실제 git 저장소: 존재하는 해시는 경고 없이 INFO(derivable)만
G="$TMP/gitrepo"; mkdir -p "$G"; (cd "$G" && git init -q . && echo hi > a.txt && git add a.txt \
  && git -c user.name=t -c user.email=t@t commit -q -m init)
SHA=$(git -C "$G" rev-parse --short HEAD)
mkdir "$TMP/mem-sha"
printf -- '---\nname: x\ndescription: y\nmetadata:\n  type: project\n---\n\n수정은 `%s` 에서 했다. 파일은 `a.txt` 이다.\n' "$SHA" > "$TMP/mem-sha/x.md"
OUT=$(md "$TMP/mem-sha" --repo "$G"); rc=$?
check "sha: 있는 커밋은 경고 아님"              '[ $rc -eq 0 ]'
check "sha: git log로 읽히는 정보라 INFO"       'echo "$OUT" | grep -q "^INFO  sha-derivable"'

# 사건마다 파일: 날짜 이름 6개 + 일반 2개 → event-ledger
mkdir "$TMP/ledger"
for d in 01 02 03 04 05 06; do
  printf -- '---\nname: e%s\ndescription: d\nmetadata:\n  type: project\n---\n\n본문\n' "$d" > "$TMP/ledger/2026-11-$d-battle.md"
done
for n in a b; do printf -- '---\nname: %s\ndescription: d\nmetadata:\n  type: user\n---\n\n본문\n' "$n" > "$TMP/ledger/note-$n.md"; done
OUT=$(md "$TMP/ledger" --repo fixtures/repo); rc=$?
check "ledger: exit 1"                       '[ $rc -eq 1 ]'
check "ledger: 날짜 이름 6/8 감지"             'echo "$OUT" | grep -q "^WARN  event-ledger.*8개 중 6개"'
OUT=$(md "$TMP/ledger" --repo fixtures/repo --max-files 5)
check "count: 상한 초과 경고"                  'echo "$OUT" | grep -q "^WARN  file-count.*8개로 상한 5개"'

# JSON 출력과 입력 오류
OUT=$(md fixtures/mem-good --repo fixtures/repo --json)
check "json: 파싱 가능, 경고 0"                'echo "$OUT" | $PY -I -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d[\"warnings\"]==0 and d[\"checked\"]==6 else 1)"'
md "$TMP/none" --repo fixtures/repo >/dev/null 2>&1; rc=$?
check "input: 없는 기억 폴더 → exit 3"         '[ $rc -eq 3 ]'
md fixtures/mem-good --repo "$TMP/none" >/dev/null 2>&1; rc=$?
check "input: 없는 저장소 → exit 3"           '[ $rc -eq 3 ]'
mkdir "$TMP/empty"; md "$TMP/empty" --repo fixtures/repo >/dev/null 2>&1; rc=$?
check "input: 노트 없는 폴더 → exit 3"         '[ $rc -eq 3 ]'

# 저장소 밖 절대 경로·URL·홈 경로는 건너뜀(거짓 경고 방지)
mkdir "$TMP/skip"
printf -- '---\nname: s\ndescription: d\nmetadata:\n  type: reference\n---\n\n`/etc/hosts.conf` `https://example.com/a.md` `~/notes/x.md` `a_b*.py` `.md` 는 대조 안 함\n' > "$TMP/skip/s.md"
OUT=$(md "$TMP/skip" --repo fixtures/repo); rc=$?
check "skip: 외부 참조는 경고 없음"             '[ $rc -eq 0 ] && echo "$OUT" | grep -q "대조한 주장 0개 · 건너뜀 5개"'

echo "---"; echo "통과 $pass · 실패 $fail"
[ $fail -eq 0 ]

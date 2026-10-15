#!/usr/bin/env bash
# test.sh — review_gate.py 테스트. 키·모델·네트워크 없이 돈다. 이 폴더에서 `bash test.sh`
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
python3 -m unittest discover -s tests -v 2>&1 | tail -40
rc=${PIPESTATUS[0]}
[ "$rc" -eq 0 ] || exit "$rc"

fail() { echo "FAIL: $*"; exit 1; }
expect() { # expect <기대 종료코드> <설명> -- 명령...
  local want="$1" desc="$2"; shift 3
  "$@" >/dev/null 2>&1; local got=$?
  [ "$got" -eq "$want" ] || fail "$desc: 종료 코드 $got (기대 $want)"
  echo "OK: $desc (exit $got)"
}
G="python3 review_gate.py gate --file tests/fixtures"
expect 1 "Important 2개 → 실패" -- $G/important.json
expect 0 "발견 없음 → 통과" -- $G/clean.json
expect 3 "개수 줄 없음 → 판정 없음" -- $G/no_line.json
expect 0 "판정 없음을 --on-no-verdict pass로 허용" -- $G/no_line.json --on-no-verdict pass
expect 3 "진행 중 → 판정 없음" -- $G/in_progress.json
expect 2 "--file 없이 호출 → 사용법 오류" -- python3 review_gate.py gate
expect 2 "없는 파일 → 입력 오류" -- python3 review_gate.py gate --file tests/fixtures/none.json

# stdin 입력 + --json
python3 review_gate.py gate --file - --json < tests/fixtures/rerun.json | grep -q '"verdict": "pass"' || fail "stdin/--json"
echo "OK: stdin + --json"

# 가짜 gh로 --repo 모드 전체 경로(목록 → output.text 비면 단건 조회)를 태운다
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
cat >"$tmp/gh" <<'GH'
#!/usr/bin/env bash
echo "$*" >>"$FAKE_GH_LOG"
case "$*" in
  *"/commits/abc123/check-runs"*) jq -c '.check_runs[] | if .name=="Claude Code Review" then .output.text=null else . end' "$FAKE_GH_FIXTURE" ;;
  *"/check-runs/2") jq -c '.check_runs[] | select(.id==2)' "$FAKE_GH_FIXTURE" ;;
  *) echo "unexpected: $*" >&2; exit 1 ;;
esac
GH
chmod +x "$tmp/gh"
export FAKE_GH_LOG="$tmp/log" FAKE_GH_FIXTURE="$PWD/tests/fixtures/important.json"
PATH="$tmp:$PATH" python3 review_gate.py gate --repo o/r --sha abc123 >"$tmp/out" 2>&1; rc=$?
[ "$rc" -eq 1 ] || { cat "$tmp/out"; fail "가짜 gh 경로 종료 코드 $rc (기대 1)"; }
grep -q 'Important 2' "$tmp/out" || { cat "$tmp/out"; fail "가짜 gh 경로 출력"; }
[ "$(wc -l <"$tmp/log")" -eq 2 ] || { cat "$tmp/log"; fail "gh 호출 횟수(목록 1 + 단건 1)"; }
echo "OK: 가짜 gh로 --repo 경로 (목록 → 단건 조회, Important 2 → exit 1)"
python3 review_gate.py gate --repo o/r --sha abc123 --dry-run | grep -q 'gh api repos/o/r/commits/abc123/check-runs' || fail "--dry-run"
echo "OK: --dry-run은 gh를 부르지 않고 명령만 출력"

# lint: 임시 git 저장소에서 --base 확인
repo="$tmp/repo"; mkdir -p "$repo/services/billing"
git -C "$repo" init -q -b main
git -C "$repo" config user.email t@example.com; git -C "$repo" config user.name t
printf '# R\nReserve Important for broken behavior.\nAt most 5 Nits.\nDo not report generated files.\n' >"$repo/REVIEW.md"
git -C "$repo" add REVIEW.md; git -C "$repo" commit -qm base
python3 review_gate.py lint "$repo" --base main --strict >/dev/null || fail "병합된 깨끗한 REVIEW.md가 실패"
echo "OK: lint — 병합된 REVIEW.md 통과"
printf '# S\nOnly Important bugs, at most 2 nits, skip tests.\n' >"$repo/services/billing/REVIEW.md"
python3 review_gate.py lint "$repo" --base main >"$tmp/lint" 2>&1; rc=$?
[ "$rc" -eq 1 ] && grep -q R030 "$tmp/lint" || { cat "$tmp/lint"; fail "미병합 하위 REVIEW.md를 못 잡음 (exit $rc)"; }
echo "OK: lint — 미병합 services/billing/REVIEW.md → R030 오류 (exit 1)"
echo "ALL OK"

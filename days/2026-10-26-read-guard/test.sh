#!/usr/bin/env bash
# test.sh — read_guard.py 단위 테스트. 키·모델 없이 돈다. 이 폴더에서 `bash test.sh`.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
G="python3 -I read_guard.py"
pass=0; fail=0
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/node_modules/lodash" "$T/src" "$T/proj/.claude"
head -c 70000 /dev/zero | tr '\0' 'a' > "$T/package-lock.json"          # 큰 락 파일
head -c 2000  /dev/zero | tr '\0' 'a' > "$T/small-lock.json"; cp "$T/small-lock.json" "$T/yarn.lock"  # 작은 락 파일
head -c 40000 /dev/zero | tr '\0' 'a' > "$T/node_modules/lodash/lodash.js"
head -c 50000 /dev/zero | tr '\0' 'a' > "$T/app.min.js"
head -c 90000 /dev/zero | tr '\0' 'a' > "$T/app.js.map"
head -c 30000 /dev/zero | tr '\0' 'a' > "$T/src/main.py"                 # 큰 일반 소스는 대상 아님
head -c 3000  /dev/zero > "$T/data.zip"                                  # 작은 바이너리도 차단

mkj() { python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"PreToolUse","tool_name":sys.argv[1],"cwd":sys.argv[2],"tool_input":json.loads(sys.argv[3])}))' "$@"; }
expect() { # $1=label $2=expected_exit $3=stdin [$4=stderr must contain]
  local out rc
  out="$(printf '%s' "$3" | $G 2>&1)"; rc=$?
  if [ "$rc" -eq "$2" ] && { [ -z "${4:-}" ] || [[ "$out" == *"$4"* ]]; }; then
    pass=$((pass+1)); echo "  ✅ $1 (exit=$rc)"
  else
    fail=$((fail+1)); echo "  ❌ $1 (exit=$rc, expected $2) $out"
  fi
}
rd() { mkj Read "$T" "{\"file_path\":\"$1\"$2}"; }
sh() { mkj Bash "$T" "$(python3 -c 'import json,sys; print(json.dumps({"command":sys.argv[1]}))' "$1")"; }

echo "== Read 차단 (exit 2)"
expect "큰 package-lock.json 전체"        2 "$(rd "$T/package-lock.json" '')" "lockfile"
expect "상대 경로 + cwd"                  2 "$(rd "package-lock.json" '')" "70,000 bytes"
expect "node_modules 안 큰 파일"          2 "$(rd "$T/node_modules/lodash/lodash.js" '')" "dependency-or-build-dir"
expect "*.min.js"                         2 "$(rd "$T/app.min.js" '')" "bundle"
expect "*.map"                            2 "$(rd "$T/app.js.map" '')" "bundle"
expect "작은 바이너리(.zip)"              2 "$(rd "$T/data.zip" '')" "binary"
expect "limit이 너무 큼(5000)"            2 "$(rd "$T/package-lock.json" ',"offset":1,"limit":5000')"
expect "offset만 있고 limit 없음"         2 "$(rd "$T/package-lock.json" ',"offset":100')"

echo "== Read 통과 (exit 0)"
expect "부분 읽기 offset=1 limit=3"       0 "$(rd "$T/package-lock.json" ',"offset":1,"limit":3')"
expect "limit=200 경계"                   0 "$(rd "$T/node_modules/lodash/lodash.js" ',"offset":1,"limit":200')"
expect "작은 락 파일"                     0 "$(rd "$T/yarn.lock" '')"
expect "큰 일반 소스(src/main.py)"        0 "$(rd "$T/src/main.py" '')"
expect "없는 파일"                        0 "$(rd "$T/nope/package-lock.json" '')"

echo "== Bash 차단 (exit 2)"
expect "cat package-lock.json"            2 "$(sh "cat package-lock.json")" "lockfile"
expect "cat -n app.min.js"                2 "$(sh "cat -n $T/app.min.js")" "bundle"
expect "less node_modules 파일"           2 "$(sh "less node_modules/lodash/lodash.js")"
expect "&& 뒤의 cat"                      2 "$(sh "cd $T && cat package-lock.json")"
expect "cat 여러 파일 중 하나가 무거움"   2 "$(sh "cat src/main.py package-lock.json")"

echo "== Bash 통과 (exit 0)"
expect "cat | head"                       0 "$(sh "cat package-lock.json | head -20")"
expect "grep -c"                          0 "$(sh "grep -c lodash package-lock.json")"
expect "wc -l"                            0 "$(sh "wc -l package-lock.json")"
expect "head -n 3"                        0 "$(sh "head -n 3 package-lock.json")"
expect "cat 작은 파일"                    0 "$(sh "cat yarn.lock")"
expect "평범한 명령"                      0 "$(sh "npm test -- --watch=false")"
expect "따옴표가 닫히지 않은 명령"        0 "$(sh "echo 'unterminated")"

echo "== 방어 (exit 0)"
expect "다른 도구(Write)"                 0 "$(mkj Write "$T" '{"file_path":"x","content":"y"}')"
expect "깨진 JSON"                        0 "not json"
expect "빈 입력"                          0 ""

echo "== 로그와 --stats"
LOG="$T/guard.jsonl"
printf '%s' "$(rd "$T/package-lock.json" '')" | READ_GUARD_LOG="$LOG" $G 2>/dev/null
printf '%s' "$(rd "$T/package-lock.json" '')" | READ_GUARD_LOG="$LOG" $G 2>/dev/null
printf '%s' "$(rd "$T/app.min.js" '')"        | READ_GUARD_LOG="$LOG" $G 2>/dev/null
printf '%s' "$(rd "$T/yarn.lock" '')"         | READ_GUARD_LOG="$LOG" $G 2>/dev/null   # 통과는 기록하지 않는다
out="$($G --stats "$LOG")"
for want in "차단 3건" "종류 lockfile: 2건" "종류 bundle: 1건" "package-lock.json: 2건"; do
  if [[ "$out" == *"$want"* ]]; then pass=$((pass+1)); echo "  ✅ stats: $want"; else fail=$((fail+1)); echo "  ❌ stats: $want 없음: $out"; fi
done
READ_GUARD_MIN_BYTES=100000 bash -c "printf '%s' '$(rd "$T/package-lock.json" '')' | $G" >/dev/null 2>&1
rc=$?; if [ "$rc" -eq 0 ]; then pass=$((pass+1)); echo "  ✅ READ_GUARD_MIN_BYTES=100000이면 70KB 통과"; else fail=$((fail+1)); echo "  ❌ MIN_BYTES 환경변수 무시 (exit=$rc)"; fi

echo "== --audit"
P="$T/proj"
printf '# 무시\nnode_modules/\n*.min.js\ndist/\n' > "$P/.claudeignore"
out="$($G --audit "$P" --json)"; rc=$?
chk() { if [ "$2" = "$3" ]; then pass=$((pass+1)); echo "  ✅ $1"; else fail=$((fail+1)); echo "  ❌ $1 (got '$2', want '$3')"; fi; }
chk "audit: .claudeignore만 있으면 exit 1" "$rc" "1"
chk "audit: status" "$(printf '%s' "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')" "claudeignore-has-no-effect"
chk "audit: 옮길 규칙 3개" "$(printf '%s' "$out" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["missing_rules"]))')" "3"
chk "audit: 규칙 형식" "$(printf '%s' "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin)["missing_rules"])')" "['Read(./node_modules/**)', 'Read(./**/*.min.js)', 'Read(./dist/**)']"
cat > "$P/.claude/settings.json" <<'J'
{"permissions":{"deny":["Read(./node_modules/**)","Read(./**/*.min.js)","Read(./dist/**)"]},
 "hooks":{"PreToolUse":[{"matcher":"Read|Bash","hooks":[{"type":"command","command":"python3 ${CLAUDE_PROJECT_DIR}/.claude/hooks/read_guard.py"}]}]}}
J
$G --audit "$P" >/dev/null; chk "audit: 규칙·훅이 다 있으면 exit 0" "$?" "0"
rm "$P/.claudeignore"; rm "$P/.claude/settings.json"
$G --audit "$P" >/dev/null; chk "audit: 훅이 없으면 exit 1 (no-guard-hook)" "$?" "1"

echo
echo "== 결과: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]

#!/usr/bin/env bash
# rule-leak 테스트: 키·모델·네트워크 없이 돈다. 이 폴더에서 `bash test.sh`.
# 가짜 비밀값은 실행 중에 이어 붙여 만든다(소스에 키 모양 문자열이 그대로 남지 않게).
cd "$(dirname "$0")" || exit 1
export PYTHONDONTWRITEBYTECODE=1
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
RL="python3 rule_leak.py"
PASS=0; FAIL=0
ok()  { echo "ok   - $1"; PASS=$((PASS+1)); }
bad() { echo "FAIL - $1"; [ -n "${2:-}" ] && echo "       $2"; FAIL=$((FAIL+1)); }
has() { echo "$1" | grep -qF -- "$2"; }
# run <기대 exit> <이름> <인자...> : 출력은 $OUT, exit 는 $RC
run() { local want=$1 name=$2; shift 2; OUT=$($RL "$@" 2>&1); RC=$?
        [ "$RC" = "$want" ] && ok "$name (exit $want)" || bad "$name" "exit $RC (기대 $want): $OUT"; }
verdict() { echo "$OUT" | grep -E "^[A-Z]+ +.*$1" | awk '{print $1}' | head -1; }

PW1="hunter2pw"; PW2="s3cretvalue99"
K1="sk-""ant-api03-ABCDEFGHIJKLMNOPQRST"; K2="AK""IAABCDEFGHIJKLMNOP"; K3="gh""p_abcdefghijklmnopqrstuvwxyz0123456789"
mkp() { mkdir -p "$T/$1/.claude"; git -C "$T/$1" init -q 2>/dev/null; }   # mkp <프로젝트>

# --- 프로젝트 leak: 여러 종류의 비밀 ---
mkp leak
cat > "$T/leak/.claude/settings.local.json" <<J
{"permissions":{"allow":[
 "Bash(PGPASSWORD=$PW1 psql -h db -c 'select 1')",
 "Bash(curl -H \"Authorization: Bearer $PW2\" https://api.example.com/*)",
 "Bash(export ANTHROPIC_KEY=$K1)",
 "Bash(aws s3 ls --profile x # $K2)",
 "Bash(git clone https://me:$PW2@github.com/o/r.git)",
 "Bash(git clone https://me:$K3@github.com/o/r2.git)",
 "Bash(mysql --password=$PW2 -e 'show databases')",
 "Bash(curl -u admin:$PW1 https://x.test/*)",
 "Bash(npm test:*)", "Read(./src/**)"]},
 "env":{"MY_API_KEY":"literal-value-12345","CLAUDE_CODE_MAX_OUTPUT_TOKENS":"64000","DEBUG":"1"}}
J
run 1 "비밀이 든 설정 → exit 1" "$T/leak"
for pair in "inline-env:PGPASSWORD" "bearer:Bearer" "api-key:ANTHROPIC_KEY" "api-key:aws s3" "url-cred:r.git" "api-key:r2.git" "cli-flag:mysql" "curl-user:curl -u" "env-literal:env.MY_API_KEY"; do
  k=${pair%%:*}; w=${pair#*:}
  echo "$OUT" | grep -F "$w" | grep -qF "$k" && ok "$k 탐지 ($w)" || bad "$k 탐지 ($w)" "$OUT"
done
[ "$(verdict leak)" = "LEAK" ] && ok "판정 LEAK" || bad "판정 LEAK" "$OUT"
# 마스킹: 원본 비밀값이 출력 어디에도 없어야 한다
for s in "$PW1" "$PW2" "$K1" "$K2" "$K3" "literal-value-12345"; do
  has "$OUT" "$s" && bad "마스킹 — 원본 노출: ${s:0:6}…" || ok "마스킹 — ${s:0:6}… 노출 안 됨"
done
has "$OUT" "hu***(9자)" && ok "마스킹 형식 앞2글자+***(길이)" || bad "마스킹 형식" "$OUT"
has "$OUT" "npm test" && bad "정상 규칙(npm test)이 걸림" "$OUT" || ok "정상 규칙은 조용"
has "$OUT" "MAX_OUTPUT_TOKENS" && bad "토큰 수 env 오탐" "$OUT" || ok "MAX_OUTPUT_TOKENS 오탐 없음"
has "$OUT" "폐기" && ok "LEAK 출력에 폐기 순서 안내" || bad "폐기 안내 없음"
run 1 "--json 도 exit 1" "$T/leak" --json
echo "$OUT" | python3 -c 'import sys,json; d=json.load(sys.stdin); assert d["counts"]["LEAK"]==1 and len(d["results"][0]["findings"])>=9' \
  && ok "--json 구조(LEAK=1, 탐지 9건 이상)" || bad "--json 구조" "$OUT"
for s in "$PW1" "$K1"; do has "$OUT" "$s" && bad "--json 원본 노출" || ok "--json 마스킹 ${s:0:6}…"; done

# --- 프로젝트 clean: 비밀 없음 + 오탐 후보 ---
mkp clean
cat > "$T/clean/.claude/settings.json" <<'J'
{"permissions":{"allow":[
 "Bash(PGPASSWORD=$PGPASSWORD psql:*)", "Bash(PGPASSWORD=* psql:*)", "Bash(GITHUB_TOKEN=${GITHUB_TOKEN} gh pr list)",
 "Bash(curl -H \"Authorization: Bearer $TOKEN\" https://api.example.com/*)", "Bash(git push origin main)",
 "Bash(NODE_ENV=production node app.js)", "Read(./.env)", "WebFetch(domain:docs.anthropic.com)"],
 "deny":["Read(./.env)","Read(./secrets/**)"]},
 "env":{"API_KEY":"${API_KEY}","MY_TOKEN":"$MY_TOKEN","CLAUDE_CODE_MAX_OUTPUT_TOKENS":"32000"}}
J
run 0 "비밀 없는 설정(변수 참조·와일드카드·placeholder) → exit 0" "$T/clean"
[ "$(verdict clean)" = "OK" ] && ok "판정 OK" || bad "판정 OK" "$OUT"

# --- git 상태 ---
mkp trk
echo '{"permissions":{"allow":["Bash(ls:*)"]}}' > "$T/trk/.claude/settings.local.json"
git -C "$T/trk" add -f .claude/settings.local.json 2>/dev/null
run 1 "비밀 없어도 settings.local.json 이 추적되면 exit 1" "$T/trk"
[ "$(verdict trk)" = "TRACKED" ] && ok "판정 TRACKED" || bad "판정 TRACKED" "$OUT"
has "$OUT" "git rm --cached" && ok "TRACKED 조치 안내" || bad "TRACKED 조치 안내"

mkp unig
echo '{"permissions":{"allow":["Bash(ls:*)"]}}' > "$T/unig/.claude/settings.local.json"
run 0 "추적 안 되고 무시도 안 되면 경고만(exit 0)" "$T/unig"
[ "$(verdict unig)" = "UNIGNORED" ] && ok "판정 UNIGNORED" || bad "판정 UNIGNORED" "$OUT"

mkp ign
echo '{"permissions":{"allow":["Bash(ls:*)"]}}' > "$T/ign/.claude/settings.local.json"
echo ".claude/settings.local.json" > "$T/ign/.gitignore"
run 0 ".gitignore 에 있으면 OK" "$T/ign"
[ "$(verdict ign)" = "OK" ] && ok "판정 OK(무시됨)" || bad "판정 OK(무시됨)" "$OUT"

mkp trkleak
echo "{\"permissions\":{\"allow\":[\"Bash(PGPASSWORD=$PW1 psql)\"]}}" > "$T/trkleak/.claude/settings.json"
git -C "$T/trkleak" add .claude/settings.json 2>/dev/null
run 1 "공유 settings.json 안의 비밀도 LEAK" "$T/trkleak"
has "$OUT" "git 기록에 남아" && ok "추적 중 LEAK 는 기록 잔존 경고" || bad "기록 잔존 경고" "$OUT"

# --- 입력·오류 ---
mkdir -p "$T/broken/.claude"; echo '{ not json' > "$T/broken/.claude/settings.json"
run 1 "깨진 JSON → ERROR, exit 1" "$T/broken"
has "$OUT" "읽기 실패" && ok "ERROR 사유 출력" || bad "ERROR 사유" "$OUT"
mkdir -p "$T/empty"; run 0 "settings 없는 폴더 → exit 0" "$T/empty"
has "$OUT" "파일 0개" && ok "파일 0개로 보고" || bad "파일 0개 보고" "$OUT"
run 2 "없는 경로 → exit 2" "$T/없는경로"
run 0 "파일을 직접 지정" "$T/clean/.claude/settings.json"
run 0 "--quiet 는 OK 줄을 숨긴다" "$T/clean" --quiet
has "$OUT" "OK " && has "$OUT" ".claude" && bad "--quiet 인데 OK 줄 출력" "$OUT" || ok "--quiet OK 줄 숨김"
# --home: HOME 을 가짜로 바꿔 ~/.claude/settings.json 을 읽는지
mkdir -p "$T/home/.claude"; echo "{\"env\":{\"DB_PASSWORD\":\"$PW2\"}}" > "$T/home/.claude/settings.json"
OUT=$(HOME="$T/home" $RL "$T/empty" --home 2>&1); RC=$?
[ "$RC" = 1 ] && has "$OUT" "env.DB_PASSWORD" && ok "--home 이 ~/.claude 를 본다" || bad "--home" "rc=$RC $OUT"
has "$OUT" "$PW2" && bad "--home 원본 노출" || ok "--home 마스킹"

echo "---"
echo "통과 $PASS / 실패 $FAIL"
[ "$FAIL" = 0 ]

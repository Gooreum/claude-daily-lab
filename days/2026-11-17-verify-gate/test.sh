#!/usr/bin/env bash
# verify-gate 테스트: 키·모델·네트워크 없이 돈다. 이 폴더에서 `bash test.sh`.
cd "$(dirname "$0")" || exit 1
export PYTHONDONTWRITEBYTECODE=1
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
VG="python3 verify_gate.py"
PASS=0; FAIL=0
ok()  { echo "ok   - $1"; PASS=$((PASS+1)); }
bad() { echo "FAIL - $1"; [ -n "${2:-}" ] && echo "       $2"; FAIL=$((FAIL+1)); }
has() { echo "$1" | grep -qF -- "$2"; }
expect_rc() { # 이름 기대코드 실제코드
  if [ "$3" = "$2" ]; then ok "$1"; else bad "$1" "종료 코드 $3 (기대 $2)"; fi; }

# 세션 기록 만들기: tr <파일> <이벤트...>  이벤트: slash:이름 skill:이름 edit bash:명령[:err] text:글
tr_make() {
  local f=$1; shift
  python3 - "$f" "$@" <<'PY'
import json, sys
f, evs = sys.argv[1], sys.argv[2:]
out = [{"type": "tools-used", "tools": ["Bash"]}]
i = 0
for e in evs:
    kind, _, arg = e.partition(":")
    i += 1
    if kind == "slash":
        out.append({"type": "user", "message": {"role": "user", "content":
            "<command-message>%s</command-message>\n<command-name>/%s</command-name>" % (arg, arg)}})
    elif kind == "text":
        out.append({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": arg}]}})
    elif kind == "skill":
        out.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t%d" % i, "name": "Skill", "input": {"skill": arg}}]}})
    elif kind == "edit":
        out.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t%d" % i, "name": arg or "Edit", "input": {"file_path": "a.py"}}]}})
    elif kind == "bash":
        cmd, err, _ = arg.partition("|err")
        out.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t%d" % i, "name": "Bash", "input": {"command": cmd}}]}})
        out.append({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t%d" % i, "is_error": bool(err), "content": "x"}]}})
with open(f, "w") as fh:
    fh.write("\n".join(json.dumps(o) for o in out) + "\n")
PY
}
# 훅 호출: hook <모드> <세션> <기록> <명령>  → 종료 코드는 $RC, stderr는 $ERR
hook() {
  local mode=$1 sess=$2 tr=$3 cmd=$4
  local in; in=$(python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","session_id":sys.argv[1],"transcript_path":sys.argv[2],"cwd":sys.argv[5],"tool_input":{"command":sys.argv[3]}}))' "$sess" "$tr" "$cmd" "" "$P")
  ERR=$(echo "$in" | VERIFY_GATE_MODE=$mode $VG hook 2>&1 >/dev/null); RC=$?
}
lastlog() { tail -1 "$P/.claude/verify-gate/log.jsonl"; }
newproj() { P="$T/$1"; mkdir -p "$P"; }

# --- 1. 명령 해석 ---
py_commit() { python3 -c 'import sys,verify_gate as v; sys.exit(0 if v.is_commit_command(sys.argv[1]) else 1)' "$1"; }
for c in 'git commit -m x' 'git -C repo commit -am x' 'cd a && git commit -m "m"' 'FOO=1 git commit' 'bash -c "git commit -m x"' $'git add .\ngit commit -m x' 'git commit -m "$(cat <<'"'"'EOF'"'"'
메시지; git push
EOF
)"'; do
  py_commit "$c"; expect_rc "커밋으로 인식: ${c:0:34}" 0 $?
done
for c in 'git status' 'git log --grep="commit"' 'echo git commit' 'git commit-tree abc' 'git push origin main' 'git add . && git diff'; do
  py_commit "$c"; expect_rc "커밋 아님: $c" 1 $?
done
py_commit 'echo "a; git commit"'; expect_rc "따옴표 안의 ; 뒤 git commit은 커밋 아님" 1 $?

# --- 2. 증거 판정(check) ---
tr_make "$T/none.jsonl" edit text:안녕
out=$($VG check -t "$T/none.jsonl"); rc=$?; expect_rc "증거 없음 → 종료 1" 1 $rc; has "$out" "none" && ok "none 표시" || bad "none 표시" "$out"
tr_make "$T/v1.jsonl" edit slash:verify
out=$($VG check -t "$T/v1.jsonl"); rc=$?; expect_rc "수정 뒤 /verify → verified(0)" 0 $rc; has "$out" "슬래시 /verify" && ok "증거 이름 표시" || bad "증거 이름" "$out"
tr_make "$T/v2.jsonl" edit skill:code-review
$VG check -t "$T/v2.jsonl" >/dev/null; expect_rc "Skill code-review 호출도 증거" 0 $?
tr_make "$T/v3.jsonl" edit skill:my-plugin:verify
$VG check -t "$T/v3.jsonl" >/dev/null; expect_rc "플러그인 접두어(my-plugin:verify)도 증거" 0 $?
tr_make "$T/stale.jsonl" edit slash:verify edit
out=$($VG check -t "$T/stale.jsonl"); rc=$?; expect_rc "검증 뒤 또 수정 → stale(1)" 1 $rc; has "$out" "stale" && ok "stale 표시" || bad "stale 표시" "$out"
tr_make "$T/w.jsonl" edit Write slash:verify edit MultiEdit
$VG check -t "$T/w.jsonl" | grep -q stale && ok "Write·MultiEdit도 수정으로 센다" || bad "Write·MultiEdit 수정 인식"
tr_make "$T/noedit.jsonl" slash:verify
$VG check -t "$T/noedit.jsonl" >/dev/null; expect_rc "수정이 없고 증거만 있으면 verified" 0 $?
tr_make "$T/other.jsonl" edit slash:verify-later skill:reviewer
$VG check -t "$T/other.jsonl" >/dev/null; expect_rc "이름이 비슷한 명령(verify-later)은 증거 아님" 1 $?
printf '{"type":"user"\nnot json\n' > "$T/broken.jsonl"
$VG check -t "$T/broken.jsonl" >/dev/null; expect_rc "깨진 줄이 있어도 죽지 않는다(none→1)" 1 $?
$VG check -t "$T/없는파일.jsonl" >/dev/null 2>&1; expect_rc "기록 파일이 없으면 종료 2" 2 $?

# --- 3. Bash 증거(설정) ---
newproj b; mkdir -p "$P/.claude"
echo '{"bash": ["bash test\\.sh"]}' > "$P/.claude/verify-gate.json"
tr_make "$T/bt.jsonl" edit 'bash:bash test.sh'
$VG check -p "$P" -t "$T/bt.jsonl" >/dev/null; expect_rc "설정한 Bash 명령 성공 → 증거" 0 $?
tr_make "$T/bf.jsonl" edit 'bash:bash test.sh|err'
$VG check -p "$P" -t "$T/bf.jsonl" >/dev/null; expect_rc "그 Bash 명령이 실패(is_error)면 증거 아님" 1 $?
$VG check -t "$T/bt.jsonl" >/dev/null; expect_rc "설정 없으면 Bash 명령은 증거 아님" 1 $?

# --- 3b. 셸로 쓴 변경, heredoc 본문, 명령 단위 매칭 ---
tr_make "$T/s1.jsonl" slash:verify 'bash:echo hi > f.txt'
$VG check -t "$T/s1.jsonl" | grep -q stale && ok "셸 리다이렉트(> f.txt)는 수정으로 센다" || bad "리다이렉트 수정 인식"
tr_make "$T/s2.jsonl" slash:verify 'bash:sed -i s/a/b/ f.txt'
$VG check -t "$T/s2.jsonl" | grep -q stale && ok "sed -i도 수정" || bad "sed -i 수정 인식"
tr_make "$T/s3.jsonl" slash:verify $'bash:cat > t.sh <<\'EOF\'\nhi\nEOF'
$VG check -t "$T/s3.jsonl" | grep -q stale && ok "cat > 파일 <<EOF(heredoc)도 수정" || bad "heredoc 쓰기 인식"
tr_make "$T/s4.jsonl" slash:verify 'bash:python3 -c x 2>&1 | tail -3' 'bash:echo x > /dev/null' 'bash:echo "a > b"' 'bash:git status'
$VG check -t "$T/s4.jsonl" >/dev/null; expect_rc "2>&1 · /dev/null · 따옴표 안의 > · 읽기 명령은 수정이 아니다" 0 $?
echo '{"bash_edits": false}' > "$T/be.json"; mkdir -p "$T/be/.claude"; cp "$T/be.json" "$T/be/.claude/verify-gate.json"
$VG check -p "$T/be" -t "$T/s1.jsonl" >/dev/null; expect_rc "bash_edits=false면 셸 쓰기를 무시한다" 0 $?
echo '{"bash": ["bash test\\.sh"]}' > "$P/.claude/verify-gate.json"
tr_make "$T/h1.jsonl" $'bash:cat > t.sh <<\'EOF\'\nbash test.sh\nEOF'
out=$($VG check -p "$P" -t "$T/h1.jsonl"); has "$out" "none" && ok "heredoc 본문에 적힌 'bash test.sh'는 증거가 아니다(none)" || bad "heredoc 본문이 증거로 잡혔다" "$out"
tr_make "$T/h2.jsonl" edit 'bash:echo bash test.sh'
$VG check -p "$P" -t "$T/h2.jsonl" >/dev/null; expect_rc "echo bash test.sh는 증거가 아니다" 1 $?
tr_make "$T/h3.jsonl" edit 'bash:cd sub && bash test.sh 2>&1 | tail -3'
out=$($VG check -p "$P" -t "$T/h3.jsonl"); rc=$?; expect_rc "cd 뒤 && bash test.sh는 증거" 0 $rc; has "$out" "Bash bash test.sh" && ok "증거로 맞은 명령 조각을 보여 준다" || bad "증거 표시" "$out"
tr_make "$T/h4.jsonl" edit 'bash:FOO=1 bash test.sh'
$VG check -p "$P" -t "$T/h4.jsonl" >/dev/null; expect_rc "환경변수를 앞에 붙인 명령도 증거" 0 $?

# --- 4. 훅: 모드별 동작 ---
newproj m; tr_make "$T/m_none.jsonl" edit; tr_make "$T/m_ok.jsonl" edit slash:verify
hook off s0 "$T/m_none.jsonl" "git commit -m x"
expect_rc "off: 통과" 0 $RC; [ ! -e "$P/.claude/verify-gate/log.jsonl" ] && ok "off: 로그도 안 남긴다" || bad "off: 로그가 생겼다"
hook observe s1 "$T/m_none.jsonl" "git commit -m x"
expect_rc "observe: 검증 없어도 통과" 0 $RC; lastlog | grep -q '"action": "would-block"' && ok "observe: would-block 기록" || bad "observe 기록" "$(lastlog)"
[ -z "$ERR" ] && ok "observe: 화면에 아무것도 안 낸다" || bad "observe가 stderr를 썼다" "$ERR"
hook enforce s2 "$T/m_ok.jsonl" "git commit -m x"
expect_rc "enforce: 검증됨 → 통과" 0 $RC; lastlog | grep -q '"verdict": "verified"' && ok "verified 기록" || bad "verified 기록"
hook enforce s3 "$T/m_none.jsonl" "git commit -m x"
expect_rc "enforce: 검증 없음 → 종료 2(차단)" 2 $RC; has "$ERR" "/verify" && has "$ERR" "Unverified:" && ok "차단 이유와 해결 방법을 알려 준다" || bad "차단 메시지" "$ERR"
lastlog | grep -q '"action": "blocked"' && ok "blocked 기록" || bad "blocked 기록"
hook enforce s4 "$T/m_none.jsonl" "git status"
expect_rc "커밋이 아닌 명령은 건드리지 않는다" 0 $RC
echo '{"tool_name":"Edit","tool_input":{"file_path":"a"}}' | VERIFY_GATE_MODE=enforce $VG hook >/dev/null 2>&1
expect_rc "Bash가 아닌 도구는 건드리지 않는다" 0 $?
echo 'not json' | VERIFY_GATE_MODE=enforce $VG hook >/dev/null 2>&1
expect_rc "입력이 JSON이 아니면 열어 둔다" 0 $?

# --- 5. 두 번 막히면 세 번째는 통과 ---
newproj r; tr_make "$T/r.jsonl" edit
hook enforce sess-r "$T/r.jsonl" "git commit -m a"; r1=$RC
hook enforce sess-r "$T/r.jsonl" "git commit -m b"; r2=$RC
hook enforce sess-r "$T/r.jsonl" "git commit -m c"; r3=$RC
[ "$r1 $r2 $r3" = "2 2 0" ] && ok "같은 세션: 차단, 차단, 통과" || bad "차단 횟수" "$r1 $r2 $r3"
lastlog | grep -q '"action": "released"' && ok "released 기록" || bad "released 기록"
hook enforce other-sess "$T/r.jsonl" "git commit -m d"
expect_rc "다른 세션은 처음부터 다시 센다" 2 $RC
echo '{"mode":"enforce","max_blocks":1}' > "$P/.claude/verify-gate.json"
hook "" cfg1 "$T/r.jsonl" "git commit -m e"; a=$RC
hook "" cfg1 "$T/r.jsonl" "git commit -m f"; b=$RC
[ "$a $b" = "2 0" ] && ok "설정 파일 max_blocks=1·mode=enforce 적용" || bad "설정 파일" "$a $b"

# --- 6. 면제와 stale ---
newproj w; tr_make "$T/w_none.jsonl" edit
hook enforce sw "$T/w_none.jsonl" 'git commit -m "docs: 오타

Unverified: 문서만 고침"'
expect_rc "Unverified: 이유 → 통과" 0 $RC; lastlog | grep -q '"verdict": "waived"' && lastlog | grep -q '문서만 고침' && ok "waived와 이유 기록" || bad "waived 기록" "$(lastlog)"
hook enforce sw2 "$T/w_none.jsonl" 'git commit -m "x [skip-verify: 설정만 바꿈]"'
expect_rc "[skip-verify: 이유] → 통과" 0 $RC
hook enforce sw3 "$T/w_none.jsonl" 'git commit -m "x Unverified:"'
expect_rc "이유가 빈 Unverified:는 면제 아님" 2 $RC
tr_make "$T/w_stale.jsonl" edit slash:verify edit
hook enforce sw4 "$T/w_stale.jsonl" "git commit -m x"
expect_rc "stale도 enforce에서 차단" 2 $RC; has "$ERR" "뒤에 파일이 또 바뀌었다" && ok "stale 이유 문구" || bad "stale 문구" "$ERR"

# --- 7. 열어 두는 경우(훅이 커밋을 못 쓰게 만들지 않는다) ---
newproj u
hook enforce su "$T/없는파일.jsonl" "git commit -m x"
expect_rc "세션 기록이 없으면 통과" 0 $RC; lastlog | grep -q '"verdict": "unknown"' && ok "unknown 기록" || bad "unknown 기록"
echo '{"mode": enforce' > "$P/.claude/verify-gate.json"
hook "" sj "$T/r.jsonl" "git commit -m x"
expect_rc "설정 파일이 깨졌으면 기본(observe)으로 통과" 0 $RC; has "$ERR" "설정 파일을 읽지 못해" && ok "깨진 설정 경고" || bad "경고" "$ERR"
rm "$P/.claude/verify-gate.json"
hook bogus sb "$T/r.jsonl" "git commit -m x"
expect_rc "알 수 없는 mode는 observe로 대체" 0 $RC

# --- 8. report ---
out=$($VG report -p "$T/m"); echo "$out" | head -8
has "$out" "커밋 " && has "$out" "would-block" && ok "report: 건수와 처리 요약" || bad "report 요약" "$out"
$VG report -p "$T/m" --json | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["total"]==3 and d["by_verdict"]["verified"]==1, d' && ok "report --json 집계가 맞다" || bad "report --json"
out=$($VG report -p "$T/none-here"); has "$out" "로그 없음" && ok "로그가 없으면 그렇게 말한다" || bad "로그 없음" "$out"
printf '{"verdict":"none","action":"would-block"}\ngarbage\n' > "$T/m/.claude/verify-gate/log.jsonl"
out=$($VG report -p "$T/m"); has "$out" "읽지 못한 줄 1" && ok "깨진 로그 줄을 세어 알린다" || bad "깨진 로그" "$out"

# --- 9. print-settings ---
$VG print-settings 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); h=d["hooks"]["PreToolUse"][0]; assert h["matcher"]=="Bash" and h["hooks"][0]["command"].endswith("verify_gate.py hook")' \
  && ok "print-settings: 올바른 JSON 훅 등록" || bad "print-settings"

echo; echo "통과 $PASS / 실패 $FAIL"
[ "$FAIL" -eq 0 ]

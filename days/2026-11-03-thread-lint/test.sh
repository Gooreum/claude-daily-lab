#!/usr/bin/env bash
# 키·모델·네트워크 없이 도는 테스트. 이 폴더에서 `bash test.sh`.
set -u
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "ok   $1"; }
bad() { fail=$((fail+1)); echo "FAIL $1"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
tl() { $PY thread_lint.py "$@"; }
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

# 모범 로그
OUT=$(tl fixtures/good.jsonl --stats); rc=$?
check "good: exit 0" '[ $rc -eq 0 ]'
check "good: create 1 / continue 2, 지적 0" 'echo "$OUT" | grep -q "thread 요청 3건 (create 1, continue 2) · error 0 · warn 0"'
check "good: --stats 가 절감 바이트를 보여 줌" 'echo "$OUT" | grep -q "절감"'

# 나쁜 로그: 코드마다 하나씩
OUT=$(tl fixtures/bad.jsonl); rc=$?
has() { echo "$OUT" | grep -q "$1"; }
check "bad: exit 1" '[ $rc -eq 1 ]'
check "TL01 베타 헤더 없음" 'has "error TL01"'
check "TL02 continue 에 system" 'has "error TL02: continue 요청에 system"'
check "TL03 고정 필드(model, betas) 불일치" 'has "thread_fingerprint_mismatch): model, betas"'
check "TL04 thread.type 오류" 'has "error TL04: thread.type"'
check "TL05 이미 이어진 id 재사용" 'has "error TL05"'
check "TL06 5분 초과 경고" 'has "warn  TL06"'
check "TL07 중단점 5개" 'has "error TL07: cache_control 중단점 5개"'
check "TL08 assistant 로 시작하는 continue" 'has "error TL08"'
check "TL09 pause_turn 뒤 새 메시지" 'has "error TL09"'
check "TL10 404 받은 id 재시도" 'has "warn  TL10"'
check "TL11 message_stop 전 continue" 'has "warn  TL11"'
check "요약 줄: error 10 · warn 4" 'has "error 10 · warn 4"'

# --json
OUT=$(tl fixtures/bad.jsonl --json)
check "--json: 파싱 가능하고 findings 14건" 'echo "$OUT" | $PY -c "import json,sys; d=json.load(sys.stdin); assert len(d[\"findings\"])==14 and d[\"stats\"][\"continues\"]==7"'

# MCP 인증 토큰은 바뀌어도 된다 / 다른 값은 안 된다
mk() { # $1=토큰2 $2=서버URL2
cat > "$TMP/mcp.jsonl" <<JL
{"ts":0,"betas":["message-threads-2026-08-12"],"request":{"model":"m","max_tokens":9,"mcp_servers":[{"type":"url","name":"s","url":"https://a.example/mcp","authorization_token":"AAA"}],"messages":[{"role":"user","content":"x"}],"thread":{"type":"create"}},"response":{"id":"msg_1","status":200,"stop_reason":"end_turn"}}
{"ts":5,"betas":["message-threads-2026-08-12"],"request":{"model":"m","max_tokens":1,"mcp_servers":[{"type":"url","name":"s","url":"$2","authorization_token":"$1"}],"messages":[{"role":"user","content":"y"}],"thread":{"type":"continue","previous_message_id":"msg_1"}},"response":{"id":"msg_2","status":200,"stop_reason":"end_turn"}}
JL
}
mk BBB https://a.example/mcp; OUT=$(tl "$TMP/mcp.jsonl"); rc=$?
check "MCP authorization_token 변경, max_tokens 변경은 허용" '[ $rc -eq 0 ]'
mk BBB https://other.example/mcp; OUT=$(tl "$TMP/mcp.jsonl"); rc=$?
check "MCP 서버 URL 변경은 mcp_servers 불일치" '[ $rc -eq 1 ] && has "mcp_servers"'

# --fail-on warn
cat > "$TMP/warn.jsonl" <<'JL'
{"ts":0,"betas":["message-threads-2026-08-12"],"request":{"model":"m","max_tokens":9,"messages":[{"role":"user","content":"x"}],"thread":{"type":"create"}},"response":{"id":"msg_1","status":200,"stop_reason":"end_turn"}}
{"ts":400,"betas":["message-threads-2026-08-12"],"request":{"model":"m","max_tokens":9,"messages":[{"role":"user","content":"y"}],"thread":{"type":"continue","previous_message_id":"msg_1"}},"response":{"id":"msg_2","status":404}}
JL
tl "$TMP/warn.jsonl" >/dev/null; rc=$?
check "경고만 있으면 기본은 exit 0" '[ $rc -eq 0 ]'
tl "$TMP/warn.jsonl" --fail-on warn >/dev/null; rc=$?
check "--fail-on warn 이면 exit 1" '[ $rc -eq 1 ]'

# thread 가 없는 요청은 무시
echo '{"request":{"model":"m","messages":[]},"response":{"id":"msg_x","status":200}}' > "$TMP/plain.jsonl"
OUT=$(tl "$TMP/plain.jsonl"); rc=$?
check "thread 없는 요청은 점검 대상이 아님" '[ $rc -eq 0 ] && has "thread 요청 0건"'

# 입력 오류
echo '{깨짐' > "$TMP/broken.jsonl"
tl "$TMP/broken.jsonl" >/dev/null 2>&1; rc=$?
check "깨진 JSON → exit 2" '[ $rc -eq 2 ]'
tl "$TMP/없는파일.jsonl" >/dev/null 2>&1; rc=$?
check "없는 파일 → exit 2" '[ $rc -eq 2 ]'

echo "---"
echo "통과 $pass / 실패 $fail"
[ $fail -eq 0 ]

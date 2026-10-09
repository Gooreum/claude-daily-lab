#!/usr/bin/env bash
# test.sh — secret-guard.sh 단위 테스트. 이 폴더에서 `bash test.sh`로 실행한다.
# 비밀값처럼 보이는 문자열은 커밋되지 않도록 실행 시점에 조립한다.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
HOOK="./hooks/secret-guard.sh"
pass=0; fail=0

mk() { # $1=tool_name $2=field $3=value → PreToolUse stdin JSON
  python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"PreToolUse","tool_name":sys.argv[1],"tool_input":{sys.argv[2]:sys.argv[3],"file_path":"x.txt"}}))' "$1" "$2" "$3"
}
expect() { # $1=label $2=expected_exit $3=stdin_json [$4=stderr must contain]
  local out rc
  out="$(printf '%s' "$3" | bash "$HOOK" 2>&1)"; rc=$?
  if [ "$rc" -eq "$2" ] && { [ -z "${4:-}" ] || [[ "$out" == *"$4"* ]]; }; then
    pass=$((pass+1)); echo "  ✅ $1 (exit=$rc)"
  else
    fail=$((fail+1)); echo "  ❌ $1 (exit=$rc, expected $2) $out"
  fi
}

AWS="AKIA$(printf 'A%.0s' $(seq 16))"                 # AKIAAAAAAAAAAAAAAAAA
ANT="sk-ant-$(printf 'x%.0s' $(seq 30))"
GH="ghp_$(printf 'b%.0s' $(seq 40))"
PEM="-----BEGIN RSA PRIVATE KEY-----"

echo "== 차단 (exit 2)"
expect "Write: AWS access key"      2 "$(mk Write content "export AWS_ACCESS_KEY_ID=$AWS")" "aws-access-key"
expect "Write: Anthropic API key"   2 "$(mk Write content "ANTHROPIC_API_KEY=$ANT")"       "anthropic-api-key"
expect "Edit: GitHub token"         2 "$(mk Edit new_string "token = '$GH'")"               "github-token"
expect "Bash: private key heredoc"  2 "$(mk Bash command "cat > id_rsa <<K
$PEM
K")" "private-key-block"
expect "Write: generic secret=\"...\"" 2 "$(mk Write content "password = \"Sup3rS3cretPassw0rd!!\"")" "generic-secret-assign"

echo "== 통과 (exit 0)"
expect "Write: placeholder" 0 "$(mk Write content "ANTHROPIC_API_KEY=\${ANTHROPIC_API_KEY}")"
expect "Write: 짧은 값"      0 "$(mk Write content "password = \"short\"")"
expect "Edit: 평범한 코드"   0 "$(mk Edit new_string "const x = fetch(url, { headers })")"
expect "Bash: 평범한 명령"   0 "$(mk Bash command "npm test -- --watch=false")"
expect "Read: 검사 대상 아님" 0 "$(mk Read file_path "/etc/hosts")"
expect "Write: 빈 content"   0 "$(mk Write content "")"

echo "== 훅 실패 (exit 1 → onFailure 적용 대상)"
out="$(printf '%s' "$(mk Write content hello)" | SECRET_GUARD_FAIL=1 bash "$HOOK" 2>&1)"; rc=$?
if [ "$rc" -eq 1 ] && [[ "$out" == *"simulated crash"* ]]; then pass=$((pass+1)); echo "  ✅ 시뮬레이션 크래시 exit=1"; else fail=$((fail+1)); echo "  ❌ 시뮬레이션 크래시 exit=$rc $out"; fi
out="$(printf '%s' "$(mk Write content hello)" | SECRET_GUARD_PATTERNS=/nonexistent bash "$HOOK" 2>&1)"; rc=$?
if [ "$rc" -eq 1 ] && [[ "$out" == *"not found"* ]]; then pass=$((pass+1)); echo "  ✅ patterns 파일 없음 exit=1"; else fail=$((fail+1)); echo "  ❌ patterns 파일 없음 exit=$rc $out"; fi
out="$(printf 'not json' | bash "$HOOK" 2>&1)"; rc=$?
if [ "$rc" -eq 1 ]; then pass=$((pass+1)); echo "  ✅ 잘못된 JSON exit=1"; else fail=$((fail+1)); echo "  ❌ 잘못된 JSON exit=$rc $out"; fi

echo "== 결과: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]

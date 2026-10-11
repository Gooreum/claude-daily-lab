#!/usr/bin/env bash
# e2e.sh — 실제 Claude Code에 MCP 서버로 붙여(--mcp-config) 모델이 이름만으로 비밀값을 쓰고 값은 절대 보지 못하는지 본다.
# Haiku 세션 2회, 1센트 미만. `bash e2e.sh`
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
command -v claude >/dev/null || { echo "claude CLI 없음"; exit 1; }
echo "claude: $(claude --version)"
MODEL="${E2E_MODEL:-claude-haiku-5-5}"
val="e2e-secret-$(date +%s)-Zq9x"            # 이 세션에서만 쓰는 가짜 값
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/mcp.json" <<JSON
{"mcpServers":{"secret-envoy":{"command":"python3","args":["$PWD/secret_envoy.py","serve","--backend","env","--names","DEMO_TOKEN","--audit","$tmp/audit.jsonl"]}}}
JSON
pass=0; fail=0
run() { (cd "$tmp" && DEMO_TOKEN="$val" claude -p "$1" --model "$MODEL" --mcp-config "$tmp/mcp.json" --strict-mcp-config \
  --allowedTools "mcp__secret-envoy__list_secrets,mcp__secret-envoy__secret_fingerprint,mcp__secret-envoy__run_with_secrets" \
  --max-turns 6 --output-format json 2>&1 < /dev/null); }

echo "== 1) 이름만으로 명령 실행: 값의 글자 수를 세어 보고하게 한다"
out="$(run "Using the secret-envoy MCP tools only: list the secrets, then run the bash command: printf %s \"\$DEMO_TOKEN\" | wc -c   with secret DEMO_TOKEN, and reply with just the number it printed.")"
res="$(printf '%s' "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); print(str(d.get('result','')).strip()[:80].replace(chr(10),' '), '|', d.get('num_turns'), 'turns')" 2>/dev/null)"
echo "   | $res"
[[ "$res" == *"${#val}"* ]] && { pass=$((pass+1)); echo "  ✅ 자식 프로세스는 값을 봤다 (길이 ${#val})"; } || { fail=$((fail+1)); echo "  ❌ 길이 불일치"; printf '%s\n' "$out" | head -3; }
[[ "$out" != *"$val"* ]] && { pass=$((pass+1)); echo "  ✅ 세션 결과 JSON 어디에도 값이 없다"; } || { fail=$((fail+1)); echo "  ❌ 값이 샜다"; }

echo "== 2) 값을 찍어 보라고 시켜도 리댁션된 것만 돌아온다"
out="$(run "Using secret-envoy run_with_secrets with secret DEMO_TOKEN, run exactly: echo \"\$DEMO_TOKEN\"   and reply with exactly what stdout contained.")"
res="$(printf '%s' "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); print(str(d.get('result','')).strip()[:120].replace(chr(10),' '))" 2>/dev/null)"
echo "   | $res"
[[ "$out" == *"[REDACTED:DEMO_TOKEN]"* ]] && [[ "$out" != *"$val"* ]] && { pass=$((pass+1)); echo "  ✅ [REDACTED:DEMO_TOKEN]만 보였다"; } || { fail=$((fail+1)); echo "  ❌"; }

echo "== 3) 감사 로그에는 이름·명령·종료코드만"
cat "$tmp/audit.jsonl" 2>/dev/null | sed 's/^/   | /' | head -3
[ -s "$tmp/audit.jsonl" ] && ! grep -q "$val" "$tmp/audit.jsonl" && { pass=$((pass+1)); echo "  ✅ 값 없음"; } || { fail=$((fail+1)); echo "  ❌"; }
echo "== 결과: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]

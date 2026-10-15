#!/usr/bin/env bash
# e2e.sh — 실제 Claude Code(>= 2.1.300)가 내보내는 OTel 로그·지표를 otel-tap이 받아 요약하는지 본다.
# 수신기를 띄우고 `claude -p`를 한 번 부른다(Haiku, 도구 없음 — 토큰 소량). 종료 코드 3 = 로그인 안 됨.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
command -v claude >/dev/null || { echo "claude CLI 없음"; exit 1; }
echo "claude: $(claude --version)"
if claude -p "ok" --model claude-haiku-5-5 --max-turns 1 --tools "" --output-format text </dev/null 2>&1 | grep -qi "not logged in"; then
  echo "claude에 로그인되어 있지 않다. e2e 미실행(exit 3)"; exit 3
fi
tmp="$(mktemp -d)"; trap 'kill "${pid:-0}" 2>/dev/null; rm -rf "$tmp"' EXIT
python3 otel_tap.py serve --port 0 --port-file "$tmp/port" --out "$tmp/tap.jsonl" >"$tmp/serve.log" 2>&1 &
pid=$!
for _ in $(seq 1 50); do [ -s "$tmp/port" ] && break; sleep 0.1; done
port="$(cat "$tmp/port")"
# env 출력에서 포트만 바꿔 그대로 적용한다 (짧은 세션이라 내보내기 주기를 1초로 줄인다)
eval "$(python3 otel_tap.py env --port "$port")"
export OTEL_LOGS_EXPORT_INTERVAL=1000 OTEL_METRIC_EXPORT_INTERVAL=1000
claude -p "Reply with the single word: pong" --model claude-haiku-5-5 --effort low --max-turns 3 --tools "" --output-format text </dev/null
sleep 3  # 종료 시 flush가 안 되는 경우를 대비해 주기 한 번을 더 기다린다
echo "--- 수신 결과"
wc -l <"$tmp/tap.jsonl" 2>/dev/null || { echo "수신된 기록 없음"; exit 1; }
python3 otel_tap.py report "$tmp/tap.jsonl"
grep -q '"name": "api_request"' "$tmp/tap.jsonl" && echo "PASS: api_request 이벤트 수신" || { echo "FAIL: api_request 없음"; exit 1; }

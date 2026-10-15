#!/usr/bin/env bash
# test.sh — otel_tap.py 테스트. 키·모델 없이 돈다. 이 폴더에서 `bash test.sh`
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
python3 -m unittest discover -s tests -v 2>&1 | tail -60
rc=${PIPESTATUS[0]}
[ "$rc" -eq 0 ] || exit "$rc"

# 실제 서버 프로세스를 띄우고 curl로 OTLP JSON을 쏜 뒤 요약까지 본다 (--port 0 + --port-file)
tmp="$(mktemp -d)"; trap 'kill "${pid:-0}" 2>/dev/null; rm -rf "$tmp"' EXIT
python3 otel_tap.py serve --port 0 --port-file "$tmp/port" --out "$tmp/tap.jsonl" >"$tmp/serve.log" 2>&1 &
pid=$!
for _ in $(seq 1 50); do [ -s "$tmp/port" ] && break; sleep 0.1; done
[ -s "$tmp/port" ] || { echo "FAIL: 서버가 뜨지 않음"; cat "$tmp/serve.log"; exit 1; }
port="$(cat "$tmp/port")"
for pair in logs:logs spans:traces metrics:metrics; do
  code="$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' --data-binary "@tests/fixtures/${pair%%:*}.json" "http://127.0.0.1:$port/v1/${pair##*:}")"
  [ "$code" = 200 ] || { echo "FAIL: /v1/${pair##*:} → $code"; exit 1; }
done
code="$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/x-protobuf' --data-binary x "http://127.0.0.1:$port/v1/logs")"
[ "$code" = 415 ] || { echo "FAIL: protobuf가 415가 아님 ($code)"; exit 1; }
report="$(python3 otel_tap.py report "$tmp/tap.jsonl")"
echo "$report" | grep -q '4회 · 비용 \$0.0855' || { echo "FAIL: 요약 불일치"; echo "$report"; exit 1; }
grep -q 'SECRET PROMPT TEXT' "$tmp/tap.jsonl" && { echo "FAIL: 프롬프트가 저장됨"; exit 1; }
echo "OK: 서버 프로세스 스모크 (포트 $port, 25건 수신, 요약 일치, 프롬프트 미저장)"

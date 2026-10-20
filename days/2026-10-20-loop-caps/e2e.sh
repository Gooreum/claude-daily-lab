#!/usr/bin/env bash
# 실제 claude CLI로 한 번 돌려 보는 e2e. 로그인된 claude가 필요하다 (CI에서는 돌리지 않는다).
set -u
cd "$(dirname "$0")"
command -v claude >/dev/null || { echo "claude CLI 없음 — 건너뜀"; exit 0; }
LOG=$(mktemp)
python3 loop_caps.py --max-calls 2 --max-failures 2 --max-hours 0.1 --log "$LOG" -- \
  claude -p "Reply with the single word OK." --model claude-haiku-5-5 --effort low \
  --max-turns 3 --tools "" --output-format json
rc=$?
echo "exit=$rc"; cat "$LOG"; rm -f "$LOG"

#!/usr/bin/env bash
# 실제 서버 검증: `claude mcp serve`(Claude Code가 자기 도구를 MCP로 내놓는 stdio 서버)를 probe로 검사한다.
# 모델 호출은 없지만 claude CLI가 필요해서 CI의 test.sh와 분리했다. 이 폴더에서 `bash e2e.sh`.
set -u
cd "$(dirname "$0")"
command -v claude >/dev/null 2>&1 || { echo "claude CLI 없음 — e2e 건너뜀"; exit 0; }
OUT=$(python3 mcp_probe.py --timeout 20 -- claude mcp serve); rc=$?
echo "$OUT"
echo "exit=$rc"
# error가 없으면 통과. warn은 기록만 한다 (서버 쪽 사정이라 우리가 고칠 수 없음)
[ $rc -eq 0 ]

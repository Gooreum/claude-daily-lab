#!/usr/bin/env bash
# 실제 내 Claude Code 기록(~/.claude/projects)에 돌려 보는 점검. 모델 호출 없음, 읽기 전용.
# 기록이 없으면(깨끗한 CI 러너 등) 건너뛴다. 인자: cache_break.py에 그대로 넘긴다.
set -u
cd "$(dirname "$0")"
DIR="${CLAUDE_PROJECTS_DIR:-$HOME/.claude/projects}"
N=$(find "$DIR" -name '*.jsonl' 2>/dev/null | wc -l)
[ "$N" -gt 0 ] || { echo "건너뜀: $DIR 에 기록이 없다"; exit 0; }
echo "기록 파일 $N개 — $DIR"
python3 cache_break.py "$DIR" "$@" --threshold 5000 --top 5 || exit 1
python3 cache_break.py "$DIR" --json | python3 -c '
import json, sys
d = json.load(sys.stdin)
share = sum(d["cost_usd"].values())
assert abs(share - d["total_cost_usd"]) < 0.01, "비용 합계 불일치"
assert d["requests"] > 0 and d["total_tokens"] > 0
print("검증: 요청 %d건, 합계 $%.2f, 큰 쓰기(10만+) %d건" % (d["requests"], d["total_cost_usd"], d["big"]["count"]))'

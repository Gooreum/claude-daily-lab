#!/usr/bin/env bash
# 실제 claude -p 로 예측을 대조한다(모델 호출 2회, Haiku 5.5). `claude` CLI·로그인이 있어야 한다. CI는 돌리지 않는다.
# hook-merge가 예측한 합친 결과(deny / allow)가 실제 세션의 Bash 호출 결과와 같은지 본다.
set -u
cd "$(dirname "$0")"
command -v claude >/dev/null || { echo "claude CLI 없음 — e2e 건너뜀"; exit 0; }
PY=${PYTHON:-python3}
fail=0
for case in deny allow; do
  pred=$($PY hook_merge.py run fixtures/e2e_$case.json --command 'echo hooklab-probe' --project-dir . --json | $PY -c 'import json,sys; print(json.load(sys.stdin)["merged"]["print"])')
  out=$(CLAUDE_PROJECT_DIR="$PWD" claude -p "Run exactly this Bash command once and report its output: echo hooklab-probe" \
        --settings fixtures/e2e_$case.json --setting-sources project --model claude-haiku-5-5 --effort low \
        --max-turns 3 --tools Bash --allowedTools 'Bash(echo:*)' --output-format json </dev/null 2>/dev/null)
  # 로그인·API 오류면 판정할 수 없다: 불일치(1)가 아니라 미실행(3)으로 끝낸다
  err=$(echo "$out" | $PY -c 'import json,sys
try:
    d=json.loads(sys.stdin.read()); print(d.get("result","") if d.get("is_error") else "")
except Exception:
    print("출력을 JSON으로 읽지 못함")')
  [ -z "$err" ] || { echo "e2e 미실행(case=$case): $err"; exit 3; }
  # 도구 결과에 출력이 있으면 실행된 것, permission_denials 가 있으면 거절된 것
  denied=$(echo "$out" | $PY -c 'import json,sys
try:
    d=json.loads(sys.stdin.read()); print("deny" if d.get("permission_denials") else "allow")
except Exception as e:
    print("parse-error")')
  echo "case=$case 예측=$pred 실제=$denied"
  [ "$pred" = "$denied" ] || { fail=1; echo "$out" | head -c 600; }
done
[ $fail -eq 0 ] && echo "e2e: 예측과 실제가 같다" || echo "e2e: 불일치"
exit $fail

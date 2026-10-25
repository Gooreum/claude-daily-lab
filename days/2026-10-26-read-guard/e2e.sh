#!/usr/bin/env bash
# e2e.sh — 실제 Claude Code에서 read-guard 훅이 Read를 막는지 확인한다. 모델을 부르므로 토큰을 쓴다. `bash e2e.sh`
# 임시 프로젝트에 70KB package-lock.json을 두고 훅 유무 두 경우에서 같은 요청을 한 뒤 READ_GUARD_LOG와 도구 결과를 본다.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
SRC="$(pwd)"
command -v claude >/dev/null || { echo "claude CLI 없음"; exit 1; }
echo "claude: $(claude --version)"
MODEL="${E2E_MODEL:-claude-haiku-5-5}"
PROMPT='Use the Read tool on package-lock.json with no offset and no limit (read the whole file). Then reply with only the word DONE.'
pass=0; fail=0

mk_proj() { # $1=hook(yes|no)
  local tmp; tmp="$(mktemp -d)"
  python3 - "$tmp/package-lock.json" <<'PY'
import json, sys
deps = {f"node_modules/pkg-{i}": {"version": "1.0.%d" % i, "resolved": "https://registry.npmjs.org/pkg-%d.tgz" % i} for i in range(700)}
json.dump({"name": "demo", "lockfileVersion": 3, "packages": deps}, open(sys.argv[1], "w"), indent=2)
PY
  mkdir -p "$tmp/.claude/hooks"
  if [ "$1" = yes ]; then
    cp "$SRC/read_guard.py" "$tmp/.claude/hooks/"
    cp "$SRC/settings.example.json" "$tmp/.claude/settings.json"
  fi
  echo "$tmp"
}

run_case() { # $1=label $2=hook $3=expect_denies(yes|no)
  local tmp log out got; tmp="$(mk_proj "$2")"; log="$tmp/guard.jsonl"
  echo "== $1 (lock $(wc -c < "$tmp/package-lock.json") bytes)"
  out="$(cd "$tmp" && READ_GUARD_LOG="$log" CLAUDE_PROJECT_DIR="$tmp" claude -p "$PROMPT" --model "$MODEL" --effort low --max-turns 4 --allowedTools Read --output-format text 2>&1 </dev/null | tail -6)"
  printf '%s\n' "$out" | sed 's/^/   | /'
  if [[ "$out" == *"Not logged in"* ]]; then echo "  ⏭ 로그인 없음 — e2e 건너뜀(exit 3). 로그인 후 다시 실행"; rm -rf "$tmp"; exit 3; fi
  if [ -s "$log" ] && grep -q '"decision": "deny"' "$log"; then got=yes; else got=no; fi
  if [ "$got" = "$3" ]; then pass=$((pass+1)); echo "  ✅ 훅 차단 기록=$got (기대 $3)"; else fail=$((fail+1)); echo "  ❌ 훅 차단 기록=$got (기대 $3)"; fi
  rm -rf "$tmp"
}

run_case "1) 훅 설치 → 전체 읽기 거부 기록" yes yes
run_case "2) 훅 없음 → 기록 없음" no no

echo "== 결과: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]

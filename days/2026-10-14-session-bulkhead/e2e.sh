#!/usr/bin/env bash
# e2e.sh — 실제 Claude Code(>= 2.1.295)에서 session-bulkhead가 명령을 막고, 막은 이유가 모델에게 전달되는지 본다.
# 임시 git 저장소에 훅을 설치하고, "다른 세션이 이 작업 트리를 쓰는 중"인 장부를 미리 만들어 둔 뒤 `claude -p`에게
# `git checkout -b feature-x`를 시킨다. 두 번 호출하므로 토큰을 소모한다.
#   1) 다른 세션 있음 → 브랜치가 만들어지면 안 된다 (+ 응답에 worktree 안내가 비치는지 출력)
#   2) 다른 세션 없음 → 브랜치가 만들어져야 한다
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
SRC="$(pwd)"
command -v claude >/dev/null || { echo "claude CLI 없음"; exit 1; }
echo "claude: $(claude --version)"
if claude -p "ok" --model claude-haiku-5-5 --max-turns 1 --tools "" --output-format text </dev/null 2>&1 | grep -qi "not logged in"; then
  echo "claude에 로그인되어 있지 않다. e2e 미실행(exit 3)"; exit 3
fi
MODEL="${E2E_MODEL:-claude-haiku-5-5}"
PROMPT='Run this exact shell command with the Bash tool: git checkout -b feature-x . If it is refused, say in one sentence what the refusal told you to do instead. Do not ask questions.'
pass=0; fail=0

run_case() { # $1=label $2=other session yes|no $3=expect_branch yes|no
  local tmp; tmp="$(mktemp -d)"
  ( cd "$tmp" && git init -q repo && cd repo && git -c user.name=t -c user.email=t@t commit -q --allow-empty -m init )
  mkdir -p "$tmp/repo/.claude/hooks" "$tmp/state"
  cp "$SRC/hooks/session_bulkhead.py" "$tmp/repo/.claude/hooks/"
  sed "s#\$HOME/.claude/hooks#$tmp/repo/.claude/hooks#g" "$SRC/settings.example.json" > "$tmp/repo/.claude/settings.json"
  if [ "$2" = yes ]; then
    python3 - "$tmp" <<'PY'
import json, sys, time
t = sys.argv[1]
json.dump({"sid": "other-session-9999", "cwd": f"{t}/repo", "toplevel": f"{t}/repo", "ts": time.time(), "ports": {}, "heavy_ts": 0},
          open(f"{t}/state/other-session-9999.json", "w"))
PY
  fi
  echo "== $1"
  local out
  out="$(cd "$tmp/repo" && SESSION_BULKHEAD_STATE="$tmp/state" claude -p "$PROMPT" --model "$MODEL" \
         --permission-mode acceptEdits --allowedTools Bash --max-turns 4 --output-format text </dev/null 2>&1 | tail -6)"
  printf '%s\n' "$out" | sed 's/^/   | /'
  local got=no; git -C "$tmp/repo" rev-parse --verify -q feature-x >/dev/null && got=yes
  if [ "$got" = "$3" ]; then pass=$((pass+1)); echo "  ✅ 브랜치 feature-x=$got (기대 $3)"; else fail=$((fail+1)); echo "  ❌ 브랜치 feature-x=$got (기대 $3)"; fi
  if [ "$2" = yes ]; then
    printf '%s' "$out" | grep -qiE 'worktree|bulkhead|다른 세션|another session' \
      && echo "  ℹ 응답에 차단 이유(worktree/다른 세션)가 비친다 = stderr가 모델에게 전달됨" \
      || echo "  ℹ 응답에서 차단 이유를 못 찾음(모델이 요약을 생략했을 수 있음)"
  fi
  rm -rf "$tmp"
}

run_case "1) 다른 세션이 같은 작업 트리 사용 → git checkout 차단" yes no
run_case "2) 혼자 → git checkout 통과"                             no  yes
echo; echo "통과 $pass / 실패 $fail"
[ "$fail" -eq 0 ]

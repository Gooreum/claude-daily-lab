#!/usr/bin/env bash
# 실제 claude로 "exit 1 훅은 막지 못하고 exit 2 훅은 막는다"를 확인한다. 로그인이 없으면 건너뛴다(exit 0).
set -u
cd "$(dirname "$0")"
command -v claude >/dev/null || { echo "SKIP claude CLI 없음"; exit 0; }
probe=$(cd /tmp && claude -p "say ok" --model claude-haiku-5-5 --effort low --max-turns 3 --tools "" --output-format json 2>&1)
echo "$probe" | grep -q '"is_error":false' || { echo "SKIP 로그인 없음 (claude -p 가 응답하지 못함)"; exit 0; }

W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
run_case() { # $1=훅 스크립트 $2=표식 파일
  mkdir -p "$W/$2/.claude"; cp "fixtures/$1" "$W/$2/hook.py"
  cat > "$W/$2/.claude/settings.json" <<JSON
{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":"python3 $W/$2/hook.py"}]}]}}
JSON
  (cd "$W/$2" && mkdir -p build && claude -p "Run exactly this shell command and nothing else: rm -rf build" \
     --model claude-haiku-5-5 --effort low --max-turns 3 --allowedTools Bash --output-format json >/dev/null 2>&1)
  [ -d "$W/$2/build" ] && echo kept || echo removed
}
r1=$(run_case bad_exit1.py bad); r2=$(run_case good_exit2.py good)
echo "exit 1 훅: build 폴더 $r1 (removed여야 '막지 못함' 확인)"
echo "exit 2 훅: build 폴더 $r2 (kept여야 '막음' 확인)"
[ "$r1" = removed ] && [ "$r2" = kept ]

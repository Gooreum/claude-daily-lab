#!/usr/bin/env bash
# e2e.sh — 실제 Claude Code로 훅 묶음을 임시 프로젝트에 설치하고 세 가지를 본다 (Haiku, 짧은 세션 3회, 1센트 미만). `bash e2e.sh`
#  1) 파괴적 명령(git push --force)은 PreToolUse 훅이 막는다  2) 안전한 명령(git status)은 통과한다  3) 파일을 쓰면 PostToolUse 포맷 훅이 돈다
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
command -v claude >/dev/null || { echo "claude CLI 없음"; exit 1; }
echo "claude: $(claude --version)"
MODEL="${E2E_MODEL:-claude-haiku-5-5}"
pass=0; fail=0
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
bash install.sh "$tmp" >/dev/null
(cd "$tmp" && git init -q && git commit -q --allow-empty -m init)   # 테스트용 빈 저장소 (원격 없음)
mkdir -p "$tmp/bin"; printf '#!/usr/bin/env bash\necho "ruff $*" >> "%s/format-calls"\n' "$tmp" > "$tmp/bin/ruff"; chmod +x "$tmp/bin/ruff"
run() { (cd "$tmp" && PATH="$tmp/bin:$PATH" CLAUDE_PROJECT_DIR="$tmp" claude -p "$1" --model "$MODEL" --permission-mode acceptEdits --allowedTools "Bash(git *)" --max-turns 4 --output-format text 2>&1 < /dev/null); }

echo "== 1) git push --force → danger-guard가 막는다"
out="$(run 'Run exactly this bash command and then tell me in one line whether it ran or was blocked, quoting any hook message: git push --force origin main')"
printf '%s\n' "$out" | tail -3 | sed 's/^/   | /'
[[ "$out" == *"danger-guard"* || "$out" == *"BLOCKED"* || "$out" == *"blocked"* ]] && { pass=$((pass+1)); echo "  ✅ 차단 메시지가 모델에게 전달됨"; } || { fail=$((fail+1)); echo "  ❌ 차단 흔적 없음"; }

echo "== 2) git status → 통과"
out="$(run 'Run exactly this bash command and reply with its first line of output: git status')"
printf '%s\n' "$out" | tail -2 | sed 's/^/   | /'
[[ "$out" == *"On branch"* || "$out" == *"branch"* ]] && [[ "$out" != *"danger-guard"* ]] && { pass=$((pass+1)); echo "  ✅ 안전한 명령은 그대로"; } || { fail=$((fail+1)); echo "  ❌"; }

echo "== 3) Write a.py → auto-format 훅이 (가짜) ruff를 부른다"
out="$(run 'Use the Write tool to create a.py in the current directory containing exactly: x=1 . Then reply with the single word done.')"
printf '%s\n' "$out" | tail -1 | sed 's/^/   | /'
# macOS는 /var → /private/var로 실경로가 바뀌므로 파일 이름으로만 본다
if [ -f "$tmp/a.py" ] && grep -q "format -q .*/a.py" "$tmp/format-calls" 2>/dev/null; then pass=$((pass+1)); echo "  ✅ PostToolUse → ruff format a.py"; else fail=$((fail+1)); echo "  ❌ a.py=$([ -f "$tmp/a.py" ] && echo yes || echo no) calls=$(cat "$tmp/format-calls" 2>/dev/null)"; fi

echo "== 결과: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]

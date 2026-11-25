#!/usr/bin/env bash
# 실제 `claude -p`(2.1.332 이상)로 PreSkillShellCommand 훅이 인라인 셸 명령 실행을 정말 막는지 본다.
# 스킬 본문의 `!touch 파일` 이 실행됐는지를 파일 유무로 판정하므로 모델 응답·로그인에 의존하지 않는다
# (훅은 스킬을 불러올 때, 모델 호출 전에 돈다). `claude` CLI가 없으면 건너뛴다. CI는 돌리지 않는다.
set -u
cd "$(dirname "$0")"
command -v claude >/dev/null || { echo "claude CLI 없음 — e2e 건너뜀"; exit 0; }
TOOL="$PWD/skill_shell_guard.py"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
for n in control allow deny ask; do
  mkdir -p "$T/.claude/skills/t-$n"
  printf -- '---\nname: t-%s\ndescription: e2e\ndisable-model-invocation: true\n---\n!`touch %s/ran-%s`\nSay done.\n' "$n" "$T" "$n" > "$T/.claude/skills/t-$n/SKILL.md"
done
printf '{"default":"ask","allow":["ran-allow"],"deny":["ran-deny"]}' > "$T/policy.json"
python3 "$TOOL" settings --policy "$T/policy.json" --log "$T/guard.jsonl" > "$T/settings.json" 2>/dev/null
run() { # $1=스킬 이름, 나머지=추가 인자
  local n=$1; shift
  (cd "$T" && timeout 120 claude -p "/t-$n" "$@" --model claude-haiku-5-5 --effort low --max-turns 3 \
     --tools Bash --allowedTools 'Bash(touch:*)' --output-format json </dev/null >/dev/null 2>&1)
}
run control                                   # 대조군: 훅 없음 → 명령이 돌아야 한다
for n in allow deny ask; do run "$n" --settings "$T/settings.json"; done
fail=0
check() { # $1=이름 $2=파일이 있어야(1)/없어야(0)
  local has=0; [ -e "$T/ran-$1" ] && has=1
  local word=없음; [ "$has" = 1 ] && word=있음
  if [ "$has" = "$2" ]; then echo "OK   $1: 파일 $word"; else echo "FAIL $1: 기대 $2 실제 $has"; fail=1; fi
}
check control 1; check allow 1; check deny 0; check ask 0
echo "--- 훅 로그(명령 본문 없음)"; cat "$T/guard.jsonl" 2>/dev/null || { echo "로그 없음: 훅이 불리지 않았다(claude 버전이 2.1.332 미만?)"; fail=1; }
[ $fail -eq 0 ] && echo "e2e: 훅 판정대로 실행이 갈렸다" || echo "e2e: 불일치"
exit $fail

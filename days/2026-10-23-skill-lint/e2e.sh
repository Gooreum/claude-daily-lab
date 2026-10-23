#!/usr/bin/env bash
# skill-lint e2e (모델 호출, 로그인된 claude CLI 필요). test.sh와 달리 CI에서는 돌리지 않는다.
# 확인할 것: F02(따옴표 없는 description 안의 ': ')로 린터가 "필드 전부 무시"라고 한 스킬이
# 실제 Claude Code 스킬 목록에서 어떻게 보이는지. 정상 스킬(ok-skill)은 보여야 한다.
# 종료 코드: 0 = 린터 주장과 실제가 일치, 1 = 불일치, 3 = claude 없음·로그인 안 됨(건너뜀)
set -u
cd "$(dirname "$0")"
command -v claude >/dev/null 2>&1 || { echo "SKIP: claude CLI 없음"; exit 3; }
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/.claude/skills/yaml-colon" "$T/.claude/skills/ok-skill"
cp fixtures/yamlcolon/yaml-colon/SKILL.md "$T/.claude/skills/yaml-colon/SKILL.md"
printf -- '---\nname: ok-skill\ndescription: Formats commit messages. Use when the user asks for a commit message.\n---\nbody\n' > "$T/.claude/skills/ok-skill/SKILL.md"
python3 skill_lint.py "$T" --json | python3 -c 'import json,sys; d=json.load(sys.stdin); assert any(f["rule"]=="F02" for f in d["findings"]) and not any(f["skill"].endswith("ok-skill") and f["level"]!="info" for f in d["findings"])' \
  && echo "린터: yaml-colon은 F02, ok-skill은 깨끗" || { echo "린터 결과가 기대와 다름"; exit 1; }
OUT=$(cd "$T" && claude -p "Reply with ONLY the exact descriptions of the skills you can see in your skill listing for the names 'yaml-colon' and 'ok-skill', formatted as 'name=<description or MISSING>', one per line." \
  --model claude-haiku-5-5 --effort low --max-turns 3 --output-format json </dev/null 2>/dev/null)
RES=$(printf '%s' "$OUT" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(("ERR " if d.get("is_error") else "") + d.get("result",""))' 2>/dev/null)
echo "$RES"
case "$RES" in ERR*Not\ logged*) echo "SKIP: claude 로그인 안 됨"; exit 3;; ERR*) echo "claude 호출 실패"; exit 1;; esac
echo "$RES" | grep -qi 'ok-skill=.*commit' || { echo "✗ 정상 스킬이 목록에 없다"; exit 1; }
if echo "$RES" | grep -qi 'yaml-colon=.*commit'; then echo "✗ 린터는 필드가 무시된다고 했지만 description이 보인다"; exit 1; fi
echo "✓ 린터 주장과 실제가 일치: yaml-colon의 description은 목록에 없다"

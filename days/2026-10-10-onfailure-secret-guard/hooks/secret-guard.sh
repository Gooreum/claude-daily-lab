#!/usr/bin/env bash
# secret-guard.sh — Claude Code PreToolUse 훅.
# Write/Edit/Bash 입력에서 비밀값 패턴을 찾으면 exit 2로 차단한다.
# settings.json에서 onFailure: "block"과 함께 쓰면, 이 스크립트가 없거나 죽어도 fail-closed가 된다.
#
# 종료 코드: 0 = 통과(판단 없음), 2 = 차단(stderr가 Claude에게 보이는 이유), 그 외 = 훅 실패(onFailure 적용)
set -u

# 데모용: onFailure 동작을 재현하기 위해 일부러 죽는다.
if [ "${SECRET_GUARD_FAIL:-}" = "1" ]; then
  echo "secret-guard: simulated crash" >&2
  exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATTERNS="${SECRET_GUARD_PATTERNS:-$HERE/patterns.txt}"
[ -r "$PATTERNS" ] || { echo "secret-guard: patterns file not found: $PATTERNS" >&2; exit 1; }

input="$(cat)"

# tool_name별로 검사할 텍스트를 뽑는다. JSON 파싱은 python3에 맡긴다.
read -r tool_name < <(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_name",""))') || exit 1
text="$(printf '%s' "$input" | python3 -c '
import json, sys
d = json.load(sys.stdin)
t = d.get("tool_name", "")
i = d.get("tool_input") or {}
if t == "Write":
    print(i.get("content", ""))
elif t == "Edit":
    print(i.get("new_string", ""))
elif t == "Bash":
    print(i.get("command", ""))
')" || exit 1

[ -n "$text" ] || exit 0

hits=""
while IFS=$'\t' read -r name regex; do
  [ -z "$name" ] && continue
  case "$name" in \#*) continue ;; esac
  if printf '%s\n' "$text" | grep -Eiq -- "$regex"; then
    hits="${hits}${hits:+, }${name}"
  fi
done < "$PATTERNS"

if [ -n "$hits" ]; then
  echo "secret-guard: ${tool_name} 입력에서 비밀값 패턴 발견 [${hits}]. 값을 환경변수나 .env(커밋 제외)로 옮기고 코드에는 placeholder를 쓰세요." >&2
  exit 2
fi
exit 0

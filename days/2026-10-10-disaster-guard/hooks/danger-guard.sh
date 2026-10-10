#!/usr/bin/env bash
# danger-guard.sh — PreToolUse(Bash) 훅. 파괴적인 명령을 규칙(rules.txt)으로 잡아 exit 2로 차단한다.
# stdin: Claude Code 훅 JSON. 명령이 아니거나 JSON이 깨지면 exit 1 → 설정의 onFailure:"block"이 fail-closed로 막는다.
set -u
RULES="${DANGER_GUARD_RULES:-$(dirname "${BASH_SOURCE[0]}")/rules.txt}"
input="$(cat)"
cmd="$(printf '%s' "$input" | python3 -c 'import json,sys
d=json.load(sys.stdin)
if d.get("tool_name")!="Bash": print("\x00skip"); sys.exit(0)
print(d.get("tool_input",{}).get("command",""))' 2>/dev/null)" || { echo "danger-guard: hook input is not JSON" >&2; exit 1; }
[ "$cmd" = $'\x00skip' ] && exit 0
[ -r "$RULES" ] || { echo "danger-guard: rules file missing: $RULES" >&2; exit 1; }
# 줄바꿈·연속 공백을 하나로 접어 한 줄로 검사한다 (heredoc 안의 문장도 본다)
flat="$(printf '%s' "$cmd" | tr '\n\t' '  ' | tr -s ' ')"
while IFS=$'\t' read -r name why flags re; do
  [ -z "$name" ] || [ "${name:0:1}" = "#" ] && continue
  ci="-i"; [[ ",$flags," == *",cs,"* ]] && ci=""
  if printf '%s' "$flat" | grep -Eq $ci -- "$re"; then
    # nowhere: WHERE 절이 있으면 전체 삭제·갱신이 아니다
    if [[ ",$flags," == *",nowhere,"* ]] && printf '%s' "$flat" | grep -Eiq '\bwhere\b'; then continue; fi
    echo "danger-guard: BLOCKED [$name] $why. Command: ${flat:0:160}" >&2
    exit 2
  fi
done < "$RULES"
exit 0

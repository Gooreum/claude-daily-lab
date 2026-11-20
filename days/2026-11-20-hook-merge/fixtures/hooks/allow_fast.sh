#!/usr/bin/env bash
cat >/dev/null
sleep 0
case "allow" in
  deny2) echo "allow-fast" >&2; exit 2;;
  silent) exit 0;;
  crash) exit 1;;
  junk) echo "hello"; exit 0;;
  old-approve) echo '{"decision":"approve","reason":"old"}'; exit 0;;
  *) printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"%s","permissionDecisionReason":"%s"}}\n' "allow" "allow-fast"; exit 0;;
esac

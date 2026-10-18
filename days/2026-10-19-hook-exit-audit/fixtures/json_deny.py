#!/usr/bin/env python3
import json, re, sys

try:
    cmd = json.load(sys.stdin)["tool_input"]["command"]
except Exception:
    cmd = "rm -rf (입력 오류)"
if re.search(r"rm -rf|git push .*(--force|-f\b)|git reset --hard|DROP TABLE|\| *sh\b", cmd):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": "위험한 명령"}}))
sys.exit(0)

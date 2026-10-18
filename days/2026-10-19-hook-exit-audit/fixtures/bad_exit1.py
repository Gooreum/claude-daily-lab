#!/usr/bin/env python3
import json, re, sys

data = json.load(sys.stdin)
cmd = data.get("tool_input", {}).get("command", "")
if re.search(r"rm -rf|git push .*(--force|-f\b)|git reset --hard", cmd):
    print("BLOCKED: 위험한 명령", file=sys.stderr)
    sys.exit(1)

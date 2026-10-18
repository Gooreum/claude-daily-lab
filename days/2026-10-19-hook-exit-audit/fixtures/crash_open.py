#!/usr/bin/env python3
import json, re, sys

data = json.load(sys.stdin)
cmd = data["tool_input"]["command"]
if re.search(r"rm -rf|git push .*(--force|-f\b)|git reset --hard|DROP TABLE|\| *sh\b", cmd):
    print("차단: 위험한 명령", file=sys.stderr)
    sys.exit(2)
sys.exit(0)

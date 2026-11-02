#!/usr/bin/env python3
# 모범 Stop 훅: 어떤 입력에도 exit 0, stop_hook_active면 조용히 끝, 아니면 한 번 block.
import json, sys
try:
    d = json.load(sys.stdin)
    if not isinstance(d, dict): raise ValueError
except Exception:
    sys.exit(0)
if d.get("stop_hook_active"):
    sys.exit(0)
print(json.dumps({"decision": "block", "reason": "배운 점을 한 줄 적고 끝내라"}))

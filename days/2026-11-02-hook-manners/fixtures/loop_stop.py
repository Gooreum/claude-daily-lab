#!/usr/bin/env python3
# 나쁜 Stop 훅: 재진입 표시를 안 읽고 항상 막는다.
import json, sys
try: json.load(sys.stdin)
except Exception: pass
print(json.dumps({"decision": "block", "reason": "다시 해라"}))

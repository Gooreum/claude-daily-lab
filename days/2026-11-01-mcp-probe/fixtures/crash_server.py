#!/usr/bin/env python3
"""깨진 JSON 한 줄에 예외로 죽는 서버 (P11)."""
import json, sys
for line in sys.stdin:
    msg = json.loads(line)  # 깨진 줄에서 JSONDecodeError → 종료
    if "id" not in msg:
        continue
    r = {"initialize": {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "crash"}},
         "tools/list": {"tools": []}, "ping": {}}.get(msg["method"])
    if r is None:
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "nf"}}), flush=True)
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": r}), flush=True)

#!/usr/bin/env python3
"""id를 문자열로 바꿔 돌려주는 서버 (P10)."""
import json, sys
for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg:
        continue
    m = msg["method"]
    res = {"initialize": {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "s"}},
           "tools/list": {"tools": []}, "ping": {}}.get(m)
    out = {"jsonrpc": "2.0", "id": str(msg["id"])}
    if res is None:
        out["error"] = {"code": -32601, "message": "nf"}
    else:
        out["result"] = res
    print(json.dumps(out), flush=True)

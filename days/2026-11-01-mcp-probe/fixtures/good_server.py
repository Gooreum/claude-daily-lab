#!/usr/bin/env python3
"""명세를 지키는 최소 MCP 서버 (probe의 정상 기준). 도구 하나: echo(text)."""
import json, sys

TOOLS = [{"name": "echo", "description": "echo text",
          "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}]

def reply(rid, result=None, error=None):
    m = {"jsonrpc": "2.0", "id": rid}
    m["error" if error else "result"] = error or result
    print(json.dumps(m), flush=True)

for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        reply(None, error={"code": -32700, "message": "parse error"})
        continue
    if not isinstance(msg, dict) or "id" not in msg:
        continue  # 알림에는 답하지 않는다
    rid, method, p = msg["id"], msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        reply(rid, {"protocolVersion": p.get("protocolVersion", "2025-06-18"),
                    "capabilities": {"tools": {}}, "serverInfo": {"name": "good", "version": "1"}})
    elif method == "ping":
        reply(rid, {})
    elif method == "tools/list":
        reply(rid, {"tools": TOOLS})
    elif method == "tools/call":
        if p.get("name") != "echo":
            reply(rid, error={"code": -32602, "message": "unknown tool"})
        elif "text" not in (p.get("arguments") or {}):
            reply(rid, {"content": [{"type": "text", "text": "text is required"}], "isError": True})
        else:
            reply(rid, {"content": [{"type": "text", "text": p["arguments"]["text"]}]})
    else:
        reply(rid, error={"code": -32601, "message": "method not found"})

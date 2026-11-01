#!/usr/bin/env python3
"""흔한 실수를 일부러 모은 서버: stdout 로그, 알림 응답, 모르는 도구를 isError로, 필수 인자 무시,
모르는 메서드에 성공 응답, 종료하지 않음."""
import json, sys

def reply(rid, result):
    print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}), flush=True)

print("bad_server 시작!")  # P02: stdout 오염
for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    method, rid = msg.get("method"), msg.get("id")
    if rid is None:
        print(json.dumps({"jsonrpc": "2.0", "id": None, "result": {}}), flush=True)  # P03: 알림에 응답
        continue
    if method == "initialize":
        reply(rid, {"protocolVersion": "2025-06-18"})  # P01: capabilities·serverInfo 없음
    elif method == "ping":
        reply(rid, {"pong": True})  # P04: 빈 객체 아님
    elif method == "tools/list":
        reply(rid, {"tools": [{"name": "echo", "inputSchema": {"type": "string", "required": ["text"]}},  # P05
                              {"description": "이름 없음", "inputSchema": {"type": "object"}}]})
    elif method == "tools/call":
        if (msg.get("params") or {}).get("name") != "echo":
            reply(rid, {"isError": True, "content": [{"type": "text", "text": "unknown tool"}]})  # P07 warn
        else:
            reply(rid, {"content": [{"type": "text", "text": "ok"}]})  # P08: 필수 인자 무시
    else:
        reply(rid, {})  # P06: 모르는 메서드에 성공
# P12: EOF 뒤에도 안 끝난다
import time
time.sleep(60)

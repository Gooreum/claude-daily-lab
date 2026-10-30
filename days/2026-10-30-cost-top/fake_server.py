#!/usr/bin/env python3
"""test.sh용 가짜 분석 API. 127.0.0.1에서만 열리고, 요청을 로그 파일에 JSON 줄로 남긴다.
모드(경로 접두사): /ok = 2쪽 페이지네이션, /err401 = 401, /loop = has_more가 영원히 true.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

LOG = sys.argv[2]


def row(day, model, amount, lst):
    return {"starting_at": f"2026-10-{day:02d}T00:00:00Z", "ending_at": f"2026-10-{day + 1:02d}T00:00:00Z",
            "group": {"model": model}, "cost": {"currency": "USD", "amount": amount, "list_amount": lst, "requests": None}}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query, keep_blank_values=True)
        with open(LOG, "a") as f:
            f.write(json.dumps({"path": u.path, "query": u.query, "key": self.headers.get("x-api-key"),
                                "beta": self.headers.get("anthropic-beta"), "ver": self.headers.get("anthropic-version")}) + "\n")
        mode = u.path.split("/")[1]
        if mode == "err401":
            return self.reply(401, {"error": {"type": "authentication_error", "message": "invalid x-api-key"}})
        if mode == "loop":
            return self.reply(200, {"data": [], "has_more": True, "next_page": "page_x", "data_refreshed_at": None})
        if "page" not in q:
            return self.reply(200, {"data": [row(20, "claude-opus-5-5", "10000.000000", "12500.000000")], "has_more": True,
                                    "next_page": "page_SECOND", "data_refreshed_at": "2026-10-25T00:00:00Z"})
        if q["page"] == ["page_SECOND"]:
            return self.reply(200, {"data": [row(21, "claude-opus-5-5", "5050.000000", "5050.000000"),
                                             row(21, "claude-sonnet-5-5", "250.000000", "250.000000")],
                                    "has_more": False, "next_page": None, "data_refreshed_at": "2026-10-25T00:00:00Z"})
        return self.reply(400, {"error": "bad page"})


if __name__ == "__main__":
    srv = HTTPServer(("127.0.0.1", int(sys.argv[1])), H)
    srv.serve_forever()

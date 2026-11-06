#!/usr/bin/env python3
"""test.sh 전용 모의 Admin API. 요청을 REQLOG에 한 줄씩 기록한다. 포트는 PORTFILE에 쓴다."""
import json, os, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

USERS = {
    "alice@x.test": "user_alice", "bob@x.test": "user_bob", "dan@x.test": "user_dan", "erin@x.test": "user_erin",
}
AMBIG = {"frank@x.test": ["user_f1", "user_f2"]}
LOG = os.environ["REQLOG"]
CALLS = {}
LOCK = threading.Lock()


def err(h, code, etype, msg, ec=None, extra=None):
    body = {"type": "error", "error": {"type": etype, "message": msg}}
    if ec:
        body["error"]["details"] = {"error_code": ec}
    h.send_response(code)
    h.send_header("content-type", "application/json")
    for k, v in (extra or {}).items():
        h.send_header(k, v)
    h.end_headers()
    h.wfile.write(json.dumps(body).encode())


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _handle(self):
        u = urlparse(self.path)
        key = self.headers.get("x-api-key", "")
        beta = self.headers.get("anthropic-beta", "")
        with LOCK, open(LOG, "a") as f:
            f.write("%s %s key=%s beta=%s ver=%s\n" % (self.command, self.path, key, beta, self.headers.get("anthropic-version")))
        if key not in ("key-good", "key-noscope", "key-notenrolled"):
            return err(self, 401, "authentication_error", "invalid x-api-key")
        if self.command == "GET" and u.path == "/v1/organizations/users":
            em = parse_qs(u.query).get("email", [""])[0].lower()
            data = []
            base = em.split("+")[0] + "@" + em.split("@")[-1] if "+" in em else em
            if base in USERS:
                data = [{"id": USERS[base], "email": base, "role": "user"}]
            if em in AMBIG:
                data = [{"id": i, "email": em, "role": "user"} for i in AMBIG[em]]
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"data": data, "has_more": False}).encode())
            return
        if self.command == "POST" and u.path.startswith("/v1/organizations/users/") and u.path.endswith("/sign_out"):
            uid = u.path.split("/")[4]
            if beta != "admin-user-sign-out-2026-10-08":
                return err(self, 400, "invalid_request_error", "missing beta header admin-user-sign-out-2026-10-08")
            if not uid.startswith("user_"):
                return err(self, 400, "invalid_request_error", "bad id")
            if key == "key-noscope":
                return err(self, 403, "permission_error", "missing write:members")
            if key == "key-notenrolled":
                return err(self, 400, "invalid_request_error", "not enrolled", "organization_not_enrolled_in_beta")
            with LOCK:
                CALLS[uid] = CALLS.get(uid, 0) + 1
                n = CALLS[uid]
            if uid == "user_bob":
                return err(self, 400, "invalid_request_error", "primary owner", "cannot_sign_out_primary_owner")
            if uid == "user_dan" and n == 1:
                return err(self, 429, "rate_limit_error", "slow down", extra={"retry-after": "0"})
            if uid == "user_erin":
                return err(self, 503, "api_error", "unavailable")
            if uid == "user_ghost":
                return err(self, 404, "not_found_error", "no such member")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")
            return
        err(self, 404, "not_found_error", "no route")

    do_GET = do_POST = _handle


srv = HTTPServer(("127.0.0.1", 0), H)
open(os.environ["PORTFILE"], "w").write(str(srv.server_address[1]))
srv.serve_forever()

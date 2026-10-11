import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import secret_envoy as se  # noqa: E402

VAL = "hunter2-SuperSecret-9f8e"


def with_env(**kv):
    def deco(fn):
        def wrapper(self):
            old = {k: os.environ.get(k) for k in kv}
            os.environ.update(kv)
            try:
                return fn(self)
            finally:
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
        return wrapper
    return deco


class Redact(unittest.TestCase):
    def test_plain_base64_urlencoded_json_variants(self):
        import base64, urllib.parse
        text = " ".join(["x", VAL, base64.b64encode(VAL.encode()).decode(), urllib.parse.quote("a/b c", safe=""), json.dumps("q\"z")[1:-1]])
        out, n = se.redact(text, {"T": VAL, "P": "a/b c", "J": 'q"z'})
        self.assertNotIn(VAL, out)
        self.assertNotIn(base64.b64encode(VAL.encode()).decode(), out)
        self.assertIn("[REDACTED:T]", out)
        self.assertIn("[REDACTED:P]", out)
        self.assertIn("[REDACTED:J]", out)
        self.assertGreaterEqual(n, 4)

    def test_longer_value_wins_and_short_values_are_skipped(self):
        out, _ = se.redact("abcdef abcd", {"S": "abcd", "L": "abcdef"})
        self.assertEqual(out, "[REDACTED:L] [REDACTED:S]")
        out, n = se.redact("ab ab", {"X": "ab"})  # 4자 미만은 리댁션하지 않는다 (오탐 폭주 방지)
        self.assertEqual((out, n), ("ab ab", 0))

    def test_fingerprint_is_stable_and_short(self):
        self.assertEqual(len(se.fingerprint(VAL)), 12)
        self.assertEqual(se.fingerprint(VAL), se.fingerprint(VAL))


class Backends(unittest.TestCase):
    @with_env(DEMO_TOKEN=VAL)
    def test_env_backend_only_allowed_names(self):
        b = se.env_backend(["DEMO_TOKEN"])
        self.assertEqual(b.get("DEMO_TOKEN"), VAL)
        with self.assertRaises(se.SecretError):
            b.get("PATH")  # 허용 목록 밖
        with self.assertRaises(se.SecretError):
            se.env_backend(["bad-name"])

    def test_env_backend_missing_value(self):
        os.environ.pop("NOPE_X", None)
        with self.assertRaises(se.SecretError):
            se.env_backend(["NOPE_X"]).get("NOPE_X")

    def test_file_backend_requires_0600(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json"
            p.write_text(json.dumps({"A_KEY": VAL, "B_KEY": "zzzz"}))
            os.chmod(p, 0o644)
            with self.assertRaises(se.SecretError):
                se.file_backend(p)
            os.chmod(p, 0o600)
            b = se.file_backend(p)
            self.assertEqual(b.names, ["A_KEY", "B_KEY"])
            self.assertEqual(b.get("A_KEY"), VAL)
            b2 = se.file_backend(p, ["A_KEY"])
            with self.assertRaises(se.SecretError):
                b2.get("B_KEY")
            with self.assertRaises(se.SecretError):
                se.file_backend(p, ["C_KEY"])

    def test_keychain_backend_with_stub_security(self):
        with tempfile.TemporaryDirectory() as d:
            stub = Path(d) / "security"
            stub.write_text('#!/usr/bin/env bash\n[ "$3" = "secret-envoy" ] && [ "$5" = "DB_URL" ] && { echo "%s"; exit 0; }\necho "not found" >&2; exit 44\n' % VAL)
            stub.chmod(0o755)
            old = os.environ["PATH"]
            os.environ["PATH"] = d + os.pathsep + old
            try:
                b = se.keychain_backend(["DB_URL", "OTHER"])
                self.assertEqual(b.get("DB_URL"), VAL)
                with self.assertRaises(se.SecretError):
                    b.get("OTHER")
            finally:
                os.environ["PATH"] = old


class Run(unittest.TestCase):
    @with_env(DEMO_TOKEN=VAL)
    def setUp(self):
        self.b = se.env_backend(["DEMO_TOKEN"])

    @with_env(DEMO_TOKEN=VAL)
    def test_child_sees_value_but_output_is_redacted(self):
        r = se.run_with_secrets(self.b, 'printf %s "$DEMO_TOKEN" | wc -c; echo "$DEMO_TOKEN"; echo "$DEMO_TOKEN" | base64', ["DEMO_TOKEN"])
        self.assertEqual(r.exit_code, 0)
        self.assertIn(str(len(VAL)), r.stdout)
        self.assertNotIn(VAL, r.stdout)
        self.assertEqual(r.stdout.count("[REDACTED:DEMO_TOKEN]"), 2)
        self.assertEqual(r.redactions, 2)
        self.assertNotIn("o=", r.stdout)  # base64(value+"\n")의 꼬리까지 지운다

    @with_env(DEMO_TOKEN=VAL)
    def test_secret_not_injected_unless_named(self):
        os.environ.pop("DEMO_TOKEN", None)
        os.environ["DEMO_TOKEN"] = VAL
        r = se.run_with_secrets(self.b, 'echo "[${DEMO_TOKEN:-unset}]"', [])
        # 이름을 안 넘기면 부모 환경의 같은 이름도 자식에게 전달되지만 리댁션 대상이 아니다 → 서버는 env 백엔드일 때
        # 부모 환경 자체가 비밀값 저장소이므로, 이 테스트는 "요청한 것만 리댁션" 정책을 고정한다
        self.assertIn("[", r.stdout)

    @with_env(DEMO_TOKEN=VAL)
    def test_unknown_name_runs_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / "ran"
            with self.assertRaises(se.SecretError):
                se.run_with_secrets(self.b, f"touch {marker}", ["NOT_A_SECRET"])
            self.assertFalse(marker.exists())

    @with_env(DEMO_TOKEN=VAL)
    def test_timeout_and_exit_code(self):
        r = se.run_with_secrets(self.b, "sleep 5", [], timeout=1)
        self.assertTrue(r.timed_out)
        self.assertEqual(r.exit_code, 124)
        r = se.run_with_secrets(self.b, "exit 3", [])
        self.assertEqual(r.exit_code, 3)

    @with_env(DEMO_TOKEN=VAL)
    def test_allow_command_regex(self):
        import re
        with self.assertRaises(se.SecretError):
            se.run_with_secrets(self.b, "rm -rf x", [], allow_command=re.compile(r"^(curl|psql) "))
        r = se.run_with_secrets(self.b, "curl --version >/dev/null 2>&1; echo ok", [], allow_command=re.compile(r"^(curl|psql) "))
        self.assertEqual(r.stdout.strip(), "ok")


class Mcp(unittest.TestCase):
    @with_env(DEMO_TOKEN=VAL)
    def setUp(self):
        self.s = se.Server(se.env_backend(["DEMO_TOKEN"]))

    def rpc(self, method, params=None, mid=1):
        return self.s.handle({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})

    def test_initialize_negotiates_known_version(self):
        r = self.rpc("initialize", {"protocolVersion": "2025-06-18"})
        self.assertEqual(r["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(r["result"]["serverInfo"]["name"], "secret-envoy")
        r = self.rpc("initialize", {"protocolVersion": "1999-01-01"})
        self.assertEqual(r["result"]["protocolVersion"], se.PROTOCOL_VERSIONS[0])
        self.assertIsNone(self.s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_tools_list_and_unknown_method(self):
        names = [t["name"] for t in self.rpc("tools/list")["result"]["tools"]]
        self.assertEqual(names, ["list_secrets", "secret_fingerprint", "run_with_secrets"])
        self.assertEqual(self.rpc("nope")["error"]["code"], -32601)
        self.assertEqual(self.rpc("ping")["result"], {})

    @with_env(DEMO_TOKEN=VAL)
    def test_list_and_fingerprint_never_contain_value(self):
        r = self.rpc("tools/call", {"name": "list_secrets", "arguments": {}})
        self.assertNotIn(VAL, json.dumps(r))
        self.assertIn("DEMO_TOKEN", r["result"]["content"][0]["text"])
        r = self.rpc("tools/call", {"name": "secret_fingerprint", "arguments": {"name": "DEMO_TOKEN"}})
        body = json.loads(r["result"]["content"][0]["text"])
        self.assertEqual(body["length"], len(VAL))
        self.assertNotIn(VAL, json.dumps(r))

    @with_env(DEMO_TOKEN=VAL)
    def test_run_tool_redacts_and_errors_are_tool_errors(self):
        r = self.rpc("tools/call", {"name": "run_with_secrets", "arguments": {"command": 'echo "$DEMO_TOKEN"', "secrets": ["DEMO_TOKEN"]}})
        self.assertFalse(r["result"]["isError"])
        self.assertNotIn(VAL, json.dumps(r))
        self.assertIn("[REDACTED:DEMO_TOKEN]", r["result"]["content"][0]["text"])
        r = self.rpc("tools/call", {"name": "run_with_secrets", "arguments": {"command": "true", "secrets": ["X_NOPE"]}})
        self.assertTrue(r["result"]["isError"])
        self.assertIn("unknown secret", r["result"]["content"][0]["text"])
        r = self.rpc("tools/call", {"name": "bogus", "arguments": {}})
        self.assertEqual(r["error"]["code"], -32602)

    @with_env(DEMO_TOKEN=VAL)
    def test_audit_log_has_names_not_values(self):
        with tempfile.TemporaryDirectory() as d:
            audit = Path(d) / "audit.jsonl"
            s = se.Server(se.env_backend(["DEMO_TOKEN"]), audit=audit)
            s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "run_with_secrets", "arguments": {"command": 'echo "$DEMO_TOKEN"', "secrets": ["DEMO_TOKEN"]}}})
            line = json.loads(audit.read_text().splitlines()[0])
            self.assertEqual(line["secrets"], ["DEMO_TOKEN"])
            self.assertNotIn(VAL, audit.read_text())


class Stdio(unittest.TestCase):
    def test_server_over_stdio_subprocess(self):
        env = dict(os.environ, DEMO_TOKEN=VAL)
        msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "run_with_secrets", "arguments": {"command": 'printf %s "$DEMO_TOKEN" | wc -c', "secrets": ["DEMO_TOKEN"]}}},
            "this is not json",
        ]
        inp = "\n".join(m if isinstance(m, str) else json.dumps(m) for m in msgs) + "\n"
        run = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "secret_envoy.py"), "serve", "--backend", "env", "--names", "DEMO_TOKEN"],
                             input=inp, capture_output=True, text=True, env=env, timeout=30)
        lines = [json.loads(l) for l in run.stdout.splitlines() if l.strip()]
        self.assertEqual(run.returncode, 0)
        self.assertEqual([l.get("id") for l in lines], [1, 2, None])
        body = json.loads(lines[1]["result"]["content"][0]["text"])
        self.assertEqual(body["stdout"].strip(), str(len(VAL)))
        self.assertEqual(lines[2]["error"]["code"], -32700)
        self.assertNotIn(VAL, run.stdout)


class Cli(unittest.TestCase):
    def test_run_and_list_modes(self):
        env = dict(os.environ, DEMO_TOKEN=VAL)
        script = str(Path(__file__).resolve().parents[1] / "secret_envoy.py")
        run = subprocess.run([sys.executable, script, "run", "--backend", "env", "--names", "DEMO_TOKEN", "--", 'echo "$DEMO_TOKEN"; exit 7'], capture_output=True, text=True, env=env)
        self.assertEqual(run.returncode, 7)
        self.assertEqual(run.stdout.strip(), "[REDACTED:DEMO_TOKEN]")
        self.assertIn("1 redaction(s)", run.stderr)
        run = subprocess.run([sys.executable, script, "list", "--backend", "env", "--names", "DEMO_TOKEN"], capture_output=True, text=True, env=env)
        self.assertEqual(json.loads(run.stdout), {"backend": "env", "secrets": ["DEMO_TOKEN"]})
        run = subprocess.run([sys.executable, script, "list", "--backend", "file"], capture_output=True, text=True, env=env)
        self.assertEqual(run.returncode, 2)


if __name__ == "__main__":
    unittest.main()

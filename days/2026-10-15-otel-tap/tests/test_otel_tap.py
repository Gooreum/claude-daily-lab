import gzip
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import otel_tap as ot  # noqa: E402

FIX = os.path.join(HERE, "fixtures")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


def all_records():
    out = []
    for n in ("logs.json", "spans.json", "metrics.json"):
        out += [ot.redact(r) for r in ot.parse_payload(fixture(n))]
    return out


class ParseTest(unittest.TestCase):
    def test_any_value_types(self):
        self.assertEqual(ot.any_value({"intValue": "42"}), 42)
        self.assertEqual(ot.any_value({"boolValue": False}), False)
        self.assertEqual(ot.any_value({"doubleValue": 1.5}), 1.5)
        self.assertEqual(ot.any_value({"arrayValue": {"values": [{"stringValue": "a"}, {"intValue": "1"}]}}), ["a", 1])
        self.assertEqual(ot.any_value({"kvlistValue": {"values": [{"key": "k", "value": {"stringValue": "v"}}]}}), {"k": "v"})
        self.assertIsNone(ot.any_value({}))

    def test_event_name_prefix_removed(self):
        names = {r["name"] for r in ot.parse_logs(fixture("logs.json"))}
        self.assertEqual(names, {"user_prompt", "api_request", "tool_decision", "tool_result", "api_error"})

    def test_event_name_falls_back_to_body(self):
        p = {"resourceLogs": [{"scopeLogs": [{"logRecords": [{"body": {"stringValue": "claude_code.auth"}, "attributes": []}]}]}]}
        self.assertEqual(ot.parse_logs(p)[0]["name"], "auth")

    def test_span_duration_and_parent(self):
        spans = ot.parse_spans(fixture("spans.json"))
        self.assertEqual(len(spans), 4)
        self.assertEqual(spans[0]["dur_ms"], 9000.0)
        self.assertIsNone(spans[0]["parent"])
        self.assertEqual(spans[1]["parent"], "0000000000000001")

    def test_metric_temporality(self):
        ms = ot.parse_metrics(fixture("metrics.json"))
        by = {(m["name"], m["temporality"]) for m in ms}
        self.assertIn(("token.usage", "delta"), by)
        self.assertIn(("session.count", "cumulative"), by)

    def test_bad_timestamp_is_none(self):
        self.assertIsNone(ot.ts_iso("abc"))
        self.assertIsNone(ot.ts_iso(None))


class RedactTest(unittest.TestCase):
    def test_sensitive_removed_by_default(self):
        recs = [ot.redact(r) for r in ot.parse_logs(fixture("logs.json"))]
        blob = json.dumps(recs)
        for needle in ("SECRET PROMPT TEXT", "dev@example.com", "ls -la"):
            self.assertNotIn(needle, blob)

    def test_keep_content(self):
        recs = [ot.redact(r, keep_content=True) for r in ot.parse_logs(fixture("logs.json"))]
        self.assertIn("SECRET PROMPT TEXT", json.dumps(recs))

    def test_long_strings_truncated(self):
        r = ot.redact({"attrs": {"error": "x" * 1000}})
        self.assertEqual(len(r["attrs"]["error"]), ot.MAX_STR + 1)


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.rep = ot.build_report(all_records())

    def test_api_totals(self):
        a = self.rep["api"]
        self.assertEqual(a["requests"], 4)
        self.assertAlmostEqual(a["cost_usd"], 0.0855, places=6)  # cost_usd_micros 1500 → 0.0015 포함
        self.assertEqual((a["input"], a["output"], a["cache_read"], a["cache_creation"]), (2600, 1950, 33000, 18500))
        self.assertEqual(a["cache_hit"], round(33000 / (2600 + 33000 + 18500), 3))

    def test_models_and_sources(self):
        self.assertEqual(self.rep["models"]["claude-sonnet-5-5"]["requests"], 3)
        self.assertEqual(self.rep["models"]["claude-haiku-5-5"]["cache_hit"], 0.0)
        self.assertEqual(self.rep["query_sources"]["subagent"]["requests"], 1)

    def test_tools(self):
        bash = self.rep["tools"]["Bash"]
        self.assertEqual((bash["calls"], bash["failures"], bash["max_ms"]), (2, 1, 4300))
        self.assertEqual(self.rep["tools"]["Read"]["failures"], 0)

    def test_errors_decisions_prompts(self):
        self.assertEqual(self.rep["api_errors"], {"529": 1})
        self.assertEqual(self.rep["tool_decisions"], {"accept/config": 1})
        self.assertEqual(self.rep["prompts"]["count"], 2)
        self.assertEqual(self.rep["prompts"]["top_cost"][0]["prompt_id"], "p1")
        self.assertEqual(self.rep["prompts"]["top_cost"][0]["tools"], 3)
        self.assertEqual(self.rep["sessions"], 1)

    def test_spans(self):
        llm = self.rep["spans"]["llm_request"]
        self.assertEqual((llm["count"], llm["avg_ttft_ms"]), (2, 550))

    def test_metrics_delta_sum_and_cumulative_latest(self):
        m = self.rep["metrics"]
        self.assertEqual(m["token.usage[output]"], 1900)
        self.assertAlmostEqual(m["cost.usage"], 0.084)
        self.assertEqual(m["session.count"], 1)  # 누적값은 마지막 것만

    def test_render_has_sections(self):
        text = ot.render(self.rep)
        for h in ("## API 호출", "## 도구", "## API 오류", "## 스팬", "## 지표", "캐시 적중률 61.0%"):
            self.assertIn(h, text)

    def test_empty_report(self):
        rep = ot.build_report([])
        self.assertEqual(rep["records"], 0)
        self.assertIn("받은 기록이 없다", ot.render(rep))

    def test_numbers_sent_as_strings(self):
        """실제 Claude Code 2.1.300은 로그 속성 숫자를 문자열로 보낸다(prompt_length: '2'). 숫자일 때와 같은 합계여야 한다."""
        a = ot.build_report([ot.redact(r) for r in ot.parse_logs(fixture("logs_strings.json"))])
        b = ot.build_report([ot.redact(r) for r in ot.parse_logs(fixture("logs.json"))])
        self.assertEqual(a["api"], b["api"])
        self.assertEqual(a["tools"], b["tools"])
        self.assertEqual(a["api_errors"], {"529": 1})
        self.assertGreater(a["api"]["input"], 0)

    def test_error_without_status_code_groups_by_message(self):
        recs = [{"kind": "event", "ts": None, "name": "api_error", "attrs": {"error": "Could not resolve authentication method.\nExpected"}}] * 2
        self.assertEqual(ot.build_report(recs)["api_errors"], {"Could not resolve authentication method.Expected": 2})

    def test_event_names_listed(self):
        self.assertEqual(self.rep["event_names"]["api_request"], 4)
        self.assertIn("## 이벤트 종류", ot.render(self.rep))

    def test_failed_success_forms(self):
        recs = [{"kind": "event", "ts": None, "name": "tool_result", "attrs": {"tool_name": "X", "success": ok, "duration_ms": 1}} for ok in (True, "true", False, "false")]
        self.assertEqual(ot.build_report(recs)["tools"]["X"]["failures"], 2)


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out = os.path.join(self.tmp, "tap.jsonl")
        self.sink = ot.Sink(self.out)
        self.srv = ot.make_server(self.sink, "127.0.0.1", 0)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def post(self, path, data, ctype="application/json", headers=None):
        req = urllib.request.Request(self.base + path, data=data, headers={"Content-Type": ctype, **(headers or {})}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def lines(self):
        if not os.path.exists(self.out):
            return []
        with open(self.out) as f:
            return f.read().splitlines()

    def test_logs_roundtrip(self):
        code, _ = self.post("/v1/logs", json.dumps(fixture("logs.json")).encode())
        self.assertEqual(code, 200)
        self.assertEqual(len(self.lines()), 12)
        with open(self.out) as f:
            self.assertNotIn("SECRET PROMPT TEXT", f.read())

    def test_all_signals(self):
        for path, name in (("/v1/logs", "logs.json"), ("/v1/traces", "spans.json"), ("/v1/metrics", "metrics.json")):
            self.assertEqual(self.post(path, json.dumps(fixture(name)).encode())[0], 200)
        self.assertEqual(ot.build_report(ot.load(self.out))["records"], 25)

    def test_gzip_body(self):
        body = gzip.compress(json.dumps(fixture("spans.json")).encode())
        self.assertEqual(self.post("/v1/traces", body, headers={"Content-Encoding": "gzip"})[0], 200)
        self.assertEqual(len(self.lines()), 4)

    def test_protobuf_rejected_with_hint(self):
        code, body = self.post("/v1/logs", b"\x0a\x00", ctype="application/x-protobuf")
        self.assertEqual(code, 415)
        self.assertIn("http/json", body)
        self.assertEqual(self.lines(), [])

    def test_bad_inputs(self):
        self.assertEqual(self.post("/v1/logs", b"not json")[0], 400)
        self.assertEqual(self.post("/v1/logs", b"[1,2]")[0], 400)
        self.assertEqual(self.post("/v1/logs", b"garbage", headers={"Content-Encoding": "gzip"})[0], 400)
        self.assertEqual(self.post("/v1/other", b"{}")[0], 404)
        self.assertEqual(self.lines(), [])

    def test_empty_payload_ok(self):
        self.assertEqual(self.post("/v1/logs", b"{}")[0], 200)
        self.assertEqual(self.lines(), [])

    def test_healthz(self):
        with urllib.request.urlopen(self.base + "/healthz", timeout=5) as r:
            self.assertEqual(r.read(), b"ok")

    def test_concurrent_posts_do_not_interleave(self):
        payload = json.dumps(fixture("logs.json")).encode()
        ts = [threading.Thread(target=self.post, args=("/v1/logs", payload)) for _ in range(8)]
        [t.start() for t in ts]; [t.join() for t in ts]
        lines = self.lines()
        self.assertEqual(len(lines), 96)
        [json.loads(x) for x in lines]


class CliTest(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = ot.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_env(self):
        code, out, _ = self.run_cli("env", "--port", "4999")
        self.assertEqual(code, 0)
        self.assertIn("CLAUDE_CODE_ENABLE_TELEMETRY=1", out)
        self.assertIn("OTEL_EXPORTER_OTLP_PROTOCOL=http/json", out)
        self.assertIn("http://127.0.0.1:4999", out)
        self.assertNotIn("TRACES", out)
        self.assertIn("OTEL_TRACES_EXPORTER=otlp", self.run_cli("env", "--traces")[1])

    def test_serve_refuses_remote_bind(self):
        code, _, err = self.run_cli("serve", "--host", "0.0.0.0")
        self.assertEqual(code, 2)
        self.assertIn("루프백", err)

    def test_ingest_and_report_json(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "t.jsonl")
            code, msg, _ = self.run_cli("ingest", *[os.path.join(FIX, n) for n in ("logs.json", "spans.json", "metrics.json")], "--out", out)
            self.assertEqual(code, 0)
            self.assertIn("25건", msg)
            code, js, _ = self.run_cli("report", out, "--json")
            self.assertEqual(json.loads(js)["api"]["requests"], 4)

    def test_error_paths(self):
        self.assertEqual(self.run_cli("report", "/nonexistent/x.jsonl")[0], 2)
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "bad.json")
            with open(bad, "w") as f:
                f.write("{oops")
            self.assertEqual(self.run_cli("ingest", bad, "--out", os.path.join(d, "o.jsonl"))[0], 2)

    def test_load_skips_corrupt_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.jsonl")
            with open(p, "w") as f:
                f.write('{"kind":"event","name":"auth","attrs":{}}\n{broken\n\n')
            err = io.StringIO()
            with redirect_stderr(err):
                recs = ot.load(p)
            self.assertEqual(len(recs), 1)
            self.assertIn("건너뜀", err.getvalue())


if __name__ == "__main__":
    unittest.main()

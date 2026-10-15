#!/usr/bin/env python3
"""otel-tap — Claude Code가 내보내는 OpenTelemetry(OTLP/HTTP JSON)를 로컬에서 받아 JSONL로 쌓고 요약한다.

  otel_tap.py env                         # 켜야 할 환경변수를 출력
  otel_tap.py serve [--out tap.jsonl]     # 127.0.0.1:4318에서 수신 (Ctrl-C로 종료)
  otel_tap.py ingest payload.json ...     # 저장해 둔 OTLP JSON 페이로드를 JSONL에 추가
  otel_tap.py report tap.jsonl [--json]   # 비용·토큰·캐시·도구·오류 요약

표준 라이브러리만 쓴다. 프롬프트·응답·도구 입력·계정 식별자는 기본으로 지우고 저장한다(--keep-content로 해제).
"""
import argparse
import datetime as dt
import gzip
import http.server
import json
import sys
import threading

MAX_BODY = 10 * 1024 * 1024
MAX_STR = 300
SENSITIVE = {
    "prompt", "prompt_text", "response", "tool_parameters", "tool_input", "tool_content",
    "user.email", "user.account_uuid", "user.account_id", "user.id",
}
SIGNALS = {"/v1/logs": "resourceLogs", "/v1/traces": "resourceSpans", "/v1/metrics": "resourceMetrics"}


# ── OTLP JSON 파싱 ──────────────────────────────────────────────────────────

def any_value(v):
    if not isinstance(v, dict):
        return v
    for k in ("stringValue", "boolValue", "doubleValue"):
        if k in v:
            return v[k]
    if "intValue" in v:  # proto3 JSON은 int64를 문자열로 낸다
        try:
            return int(v["intValue"])
        except (TypeError, ValueError):
            return v["intValue"]
    if "arrayValue" in v:
        return [any_value(x) for x in v["arrayValue"].get("values", [])]
    if "kvlistValue" in v:
        return attrs(v["kvlistValue"].get("values", []))
    return None


def attrs(lst):
    return {a.get("key"): any_value(a.get("value")) for a in (lst or []) if a.get("key")}


def ts_iso(nano):
    try:
        return dt.datetime.fromtimestamp(int(nano) / 1e9, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse_logs(payload):
    out = []
    for rl in payload.get("resourceLogs", []):
        res = attrs(rl.get("resource", {}).get("attributes"))
        for sl in rl.get("scopeLogs", []):
            for lr in sl.get("logRecords", []):
                a = attrs(lr.get("attributes"))
                name = a.pop("event.name", None) or any_value(lr.get("body")) or "unknown"
                name = str(name).removeprefix("claude_code.")
                out.append({"kind": "event", "ts": ts_iso(lr.get("timeUnixNano")), "name": name,
                            "attrs": {**({"service.version": res["service.version"]} if "service.version" in res else {}), **a}})
    return out


def parse_spans(payload):
    out = []
    for rs in payload.get("resourceSpans", []):
        for ss in rs.get("scopeSpans", []):
            for sp in ss.get("spans", []):
                s, e = _num(sp.get("startTimeUnixNano")), _num(sp.get("endTimeUnixNano"))
                out.append({"kind": "span", "ts": ts_iso(sp.get("startTimeUnixNano")),
                            "name": str(sp.get("name", "")).removeprefix("claude_code."),
                            "trace": sp.get("traceId"), "span": sp.get("spanId"), "parent": sp.get("parentSpanId") or None,
                            "dur_ms": round((e - s) / 1e6, 1) if s is not None and e is not None else None,
                            "attrs": attrs(sp.get("attributes"))})
    return out


def parse_metrics(payload):
    out = []
    for rm in payload.get("resourceMetrics", []):
        for sm in rm.get("scopeMetrics", []):
            for m in sm.get("metrics", []):
                body = m.get("sum") or m.get("gauge") or {}
                kind = "sum" if "sum" in m else "gauge"
                temporality = {1: "delta", 2: "cumulative"}.get(body.get("aggregationTemporality"), "gauge" if kind == "gauge" else "delta")
                for dp in body.get("dataPoints", []):
                    val = dp.get("asDouble", dp.get("asInt"))
                    out.append({"kind": "metric", "ts": ts_iso(dp.get("timeUnixNano")),
                                "name": str(m.get("name", "")).removeprefix("claude_code."), "unit": m.get("unit", ""),
                                "temporality": temporality, "value": _num(val), "attrs": attrs(dp.get("attributes"))})
    return out


def parse_payload(payload):
    """어떤 신호의 페이로드든 레코드 목록으로 바꾼다."""
    return parse_logs(payload) + parse_spans(payload) + parse_metrics(payload)


def redact(rec, keep_content=False):
    a = rec.get("attrs", {})
    if not keep_content:
        a = {k: v for k, v in a.items() if k not in SENSITIVE}
    rec["attrs"] = {k: (v[:MAX_STR] + "…" if isinstance(v, str) and len(v) > MAX_STR else v) for k, v in a.items()}
    return rec


# ── 수신기 ──────────────────────────────────────────────────────────────────

class Sink:
    def __init__(self, path, keep_content=False):
        self.path, self.keep_content, self.lock, self.count = path, keep_content, threading.Lock(), 0

    def write(self, records):
        if not records:
            return 0
        lines = "".join(json.dumps(redact(r, self.keep_content), ensure_ascii=False) + "\n" for r in records)
        with self.lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(lines)
            self.count += len(records)
        return len(records)


def make_server(sink, host="127.0.0.1", port=4318):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _reply(self, code, body, ctype="application/json"):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/healthz":
                return self._reply(200, "ok", "text/plain")
            self._reply(404, "not found", "text/plain")

        def do_POST(self):
            key = SIGNALS.get(self.path.split("?")[0])
            if not key:
                return self._reply(404, '{"error":"unknown path"}')
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
            if ctype != "application/json":
                return self._reply(415, json.dumps({"error": "otel-tap은 JSON만 받는다. OTEL_EXPORTER_OTLP_PROTOCOL=http/json 으로 바꿔라 (받은 형식: %s)" % ctype}))
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._reply(400, '{"error":"bad content-length"}')
            if n > MAX_BODY:
                return self._reply(413, '{"error":"body too large"}')
            raw = self.rfile.read(n)
            try:
                if self.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                    if len(raw) > MAX_BODY * 4:
                        return self._reply(413, '{"error":"body too large"}')
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise ValueError("object expected")
                recs = {"resourceLogs": parse_logs, "resourceSpans": parse_spans, "resourceMetrics": parse_metrics}[key](payload)
            except (OSError, EOFError, ValueError) as e:
                return self._reply(400, json.dumps({"error": f"parse failed: {e}"}))
            sink.write(recs)
            self._reply(200, "{}")

    http.server.ThreadingHTTPServer.daemon_threads = True
    return http.server.ThreadingHTTPServer((host, port), Handler)


# ── 요약 ────────────────────────────────────────────────────────────────────

def load(path):
    recs = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"경고: {path}:{i} JSON이 아니라서 건너뜀", file=sys.stderr)
    return recs


def _f(x):
    """숫자로 읽는다. 실제 Claude Code는 로그 속성의 숫자를 문자열('2')로 보내기도 한다."""
    if isinstance(x, bool):
        return 0
    if isinstance(x, (int, float)):
        return x
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0


def _cost(a):
    if a.get("cost_usd") not in (None, ""):
        return float(_f(a["cost_usd"]))
    return _f(a.get("cost_usd_micros")) / 1e6


def _hit(read, inp, create):
    tot = read + inp + create
    return round(read / tot, 3) if tot else None


def _truthy(v):
    return v is True or str(v).lower() == "true"


def build_report(recs):
    events = [r for r in recs if r["kind"] == "event"]
    spans = [r for r in recs if r["kind"] == "span"]
    metrics = [r for r in recs if r["kind"] == "metric"]
    times = sorted(t for t in (r.get("ts") for r in recs) if t)
    rep = {"records": len(recs), "from": times[0] if times else None, "to": times[-1] if times else None}

    api = [e for e in events if e["name"] == "api_request"]
    tot = {"requests": len(api), "cost_usd": 0.0, "input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
    models, sources, prompts = {}, {}, {}
    sessions = set()
    for e in events:
        a = e["attrs"]
        if a.get("session.id"):
            sessions.add(a["session.id"])
    for e in api:
        a = e["attrs"]
        c, i, o, cr, cc = _cost(a), _f(a.get("input_tokens")), _f(a.get("output_tokens")), _f(a.get("cache_read_tokens")), _f(a.get("cache_creation_tokens"))
        tot["cost_usd"] += c; tot["input"] += i; tot["output"] += o; tot["cache_read"] += cr; tot["cache_creation"] += cc
        m = models.setdefault(a.get("model", "?"), {"requests": 0, "cost_usd": 0.0, "input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "dur": 0.0})
        m["requests"] += 1; m["cost_usd"] += c; m["input"] += i; m["output"] += o; m["cache_read"] += cr; m["cache_creation"] += cc; m["dur"] += _f(a.get("duration_ms"))
        s = sources.setdefault(a.get("query_source", "?"), {"requests": 0, "cost_usd": 0.0})
        s["requests"] += 1; s["cost_usd"] += c
        pid = a.get("prompt.id")
        if pid:
            p = prompts.setdefault(pid, {"prompt_id": pid, "requests": 0, "cost_usd": 0.0, "tools": 0, "output": 0})
            p["requests"] += 1; p["cost_usd"] += c; p["output"] += o
    tot["cache_hit"] = _hit(tot["cache_read"], tot["input"], tot["cache_creation"])
    for m in models.values():
        m["cache_hit"] = _hit(m["cache_read"], m["input"], m["cache_creation"])
        m["avg_ms"] = round(m.pop("dur") / m["requests"]) if m["requests"] else 0
    rep["api"] = tot
    rep["models"] = models
    rep["query_sources"] = sources

    tools = {}
    for e in events:
        if e["name"] != "tool_result":
            continue
        a = e["attrs"]
        t = tools.setdefault(a.get("tool_name", "?"), {"calls": 0, "failures": 0, "total_ms": 0.0, "max_ms": 0.0})
        t["calls"] += 1
        t["failures"] += 0 if _truthy(a.get("success")) else 1
        d = _f(a.get("duration_ms"))
        t["total_ms"] += d; t["max_ms"] = max(t["max_ms"], d)
        if a.get("prompt.id") in prompts:
            prompts[a["prompt.id"]]["tools"] += 1
    for t in tools.values():
        t["avg_ms"] = round(t["total_ms"] / t["calls"])
    rep["tools"] = tools

    errs = {}
    for e in events:
        if e["name"] == "api_error":
            a = e["attrs"]
            k = str(a["status_code"]) if a.get("status_code") not in (None, "") else "".join(str(a.get("error", "?"))[:70].split("\n"))
            errs[k] = errs.get(k, 0) + 1
    rep["api_errors"] = errs
    decisions = {}
    for e in events:
        if e["name"] == "tool_decision":
            k = f'{e["attrs"].get("decision", "?")}/{e["attrs"].get("source", "?")}'
            decisions[k] = decisions.get(k, 0) + 1
    rep["tool_decisions"] = decisions
    rep["prompts"] = {"count": len({e["attrs"].get("prompt.id") for e in events if e["name"] == "user_prompt"} - {None}),
                      "top_cost": sorted(prompts.values(), key=lambda p: -p["cost_usd"])[:5]}
    rep["sessions"] = len(sessions)
    names = {}
    for e in events:
        names[e["name"]] = names.get(e["name"], 0) + 1
    rep["event_names"] = dict(sorted(names.items(), key=lambda kv: -kv[1]))

    sp = {}
    for s in spans:
        x = sp.setdefault(s["name"], {"count": 0, "total_ms": 0.0, "max_ms": 0.0, "ttft": []})
        d = s.get("dur_ms") or 0
        x["count"] += 1; x["total_ms"] += d; x["max_ms"] = max(x["max_ms"], d)
        if s["attrs"].get("ttft_ms") not in (None, ""):
            x["ttft"].append(_f(s["attrs"]["ttft_ms"]))
    for x in sp.values():
        x["avg_ms"] = round(x["total_ms"] / x["count"], 1)
        x["avg_ttft_ms"] = round(sum(x["ttft"]) / len(x["ttft"])) if x["ttft"] else None
        del x["ttft"]
    rep["spans"] = sp

    series = {}  # 누적 지표는 시리즈별 마지막 값, 델타는 합
    for m in metrics:
        key = (m["name"], json.dumps(m["attrs"], sort_keys=True))
        if m["value"] is None:
            continue
        if m["temporality"] == "cumulative":
            if key not in series or (m.get("ts") or "") >= (series[key][1] or ""):
                series[key] = (m["value"], m.get("ts"))
        else:
            series[key] = (series.get(key, (0, None))[0] + m["value"], m.get("ts"))
    mt = {}
    for (name, ak), (val, _) in series.items():
        a = json.loads(ak)
        label = name + (f'[{a["type"]}]' if name in ("token.usage", "lines_of_code.count") and "type" in a else "")
        mt[label] = round(mt.get(label, 0) + val, 6)
    rep["metrics"] = dict(sorted(mt.items()))
    return rep


def _usd(x):
    return f"${x:.4f}"


def _pct(x):
    return "-" if x is None else f"{x * 100:.1f}%"


def render(rep):
    L = ["# otel-tap 요약", ""]
    L.append(f"- 기록 {rep['records']}건 · 세션 {rep['sessions']}개 · 프롬프트 {rep['prompts']['count']}개 · {rep['from'] or '?'} ~ {rep['to'] or '?'}")
    a = rep["api"]
    if a["requests"]:
        L += ["", "## API 호출", "",
              f"- {a['requests']}회 · 비용 {_usd(a['cost_usd'])} · 입력 {a['input']:,} · 출력 {a['output']:,} · 캐시 읽기 {a['cache_read']:,} · 캐시 생성 {a['cache_creation']:,} · **캐시 적중률 {_pct(a['cache_hit'])}**",
              "", "| 모델 | 호출 | 비용 | 입력 | 출력 | 캐시 적중 | 평균 ms |", "|---|---|---|---|---|---|---|"]
        for k, m in sorted(rep["models"].items(), key=lambda kv: -kv[1]["cost_usd"]):
            L.append(f"| {k} | {m['requests']} | {_usd(m['cost_usd'])} | {m['input']:,} | {m['output']:,} | {_pct(m['cache_hit'])} | {m['avg_ms']:,} |")
        L += ["", "| 호출 출처 | 호출 | 비용 |", "|---|---|---|"]
        for k, s in sorted(rep["query_sources"].items(), key=lambda kv: -kv[1]["cost_usd"]):
            L.append(f"| {k} | {s['requests']} | {_usd(s['cost_usd'])} |")
    if rep["prompts"]["top_cost"]:
        L += ["", "## 비싼 프롬프트 상위", "", "| prompt.id | 호출 | 도구 | 출력 토큰 | 비용 |", "|---|---|---|---|---|"]
        for p in rep["prompts"]["top_cost"]:
            L.append(f"| {p['prompt_id']} | {p['requests']} | {p['tools']} | {p['output']:,} | {_usd(p['cost_usd'])} |")
    if rep["event_names"]:
        L += ["", "## 이벤트 종류", "", "- " + " · ".join(f"{k} {v}" for k, v in rep["event_names"].items())]
    if rep["tools"]:
        L += ["", "## 도구", "", "| 도구 | 호출 | 실패 | 평균 ms | 최대 ms |", "|---|---|---|---|---|"]
        for k, t in sorted(rep["tools"].items(), key=lambda kv: -kv[1]["total_ms"]):
            L.append(f"| {k} | {t['calls']} | {t['failures']} | {t['avg_ms']:,} | {int(t['max_ms']):,} |")
    if rep["api_errors"]:
        L += ["", "## API 오류", "", "- " + " · ".join(f"{'HTTP ' + k if k.isdigit() else k}: {v}회" for k, v in sorted(rep["api_errors"].items()))]
    if rep["tool_decisions"]:
        L += ["", "## 도구 승인 결정", "", "- " + " · ".join(f"{k} {v}" for k, v in sorted(rep["tool_decisions"].items()))]
    if rep["spans"]:
        L += ["", "## 스팬", "", "| 이름 | 개수 | 평균 ms | 최대 ms | 평균 TTFT ms |", "|---|---|---|---|---|"]
        for k, x in sorted(rep["spans"].items(), key=lambda kv: -kv[1]["total_ms"]):
            L.append(f"| {k} | {x['count']} | {x['avg_ms']:,} | {int(x['max_ms']):,} | {x['avg_ttft_ms'] if x['avg_ttft_ms'] is not None else '-'} |")
    if rep["metrics"]:
        L += ["", "## 지표", ""] + [f"- {k}: {v:g}" for k, v in rep["metrics"].items()]
    if rep["records"] == 0:
        L += ["", "받은 기록이 없다. `otel_tap.py env`의 환경변수를 켜고 Claude Code를 실행했는지 확인하라."]
    return "\n".join(L) + "\n"


# ── CLI ─────────────────────────────────────────────────────────────────────

def env_block(host, port, traces):
    ep = f"http://{host}:{port}"
    lines = ["export CLAUDE_CODE_ENABLE_TELEMETRY=1", "export OTEL_METRICS_EXPORTER=otlp", "export OTEL_LOGS_EXPORTER=otlp",
             "export OTEL_EXPORTER_OTLP_PROTOCOL=http/json", f"export OTEL_EXPORTER_OTLP_ENDPOINT={ep}",
             "export OTEL_METRIC_EXPORT_INTERVAL=10000", "export OTEL_LOGS_EXPORT_INTERVAL=2000"]
    if traces:
        lines += ["# 실험: 트레이스(베타). 문서 예시는 http/protobuf라 JSON 수신이 되는지는 확인되지 않았다",
                  "export CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1", "export OTEL_TRACES_EXPORTER=otlp",
                  "export OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/json", f"export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT={ep}/v1/traces"]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("env", help="켜야 할 환경변수 출력")
    e.add_argument("--host", default="127.0.0.1"); e.add_argument("--port", type=int, default=4318)
    e.add_argument("--traces", action="store_true", help="트레이스 변수도 출력(실험)")
    s = sub.add_parser("serve", help="OTLP/HTTP JSON 수신 서버")
    s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=4318)
    s.add_argument("--out", default="otel-tap.jsonl"); s.add_argument("--port-file", help="실제 포트를 이 파일에 쓴다(--port 0일 때 유용)")
    s.add_argument("--keep-content", action="store_true", help="프롬프트·응답·도구 입력·계정 식별자를 지우지 않는다")
    s.add_argument("--allow-remote", action="store_true", help="127.0.0.1이 아닌 주소에 바인드 허용")
    i = sub.add_parser("ingest", help="OTLP JSON 페이로드 파일을 JSONL에 추가")
    i.add_argument("files", nargs="+"); i.add_argument("--out", default="otel-tap.jsonl"); i.add_argument("--keep-content", action="store_true")
    r = sub.add_parser("report", help="JSONL 요약")
    r.add_argument("file"); r.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "env":
        sys.stdout.write(env_block(args.host, args.port, args.traces))
        return 0
    if args.cmd == "ingest":
        sink = Sink(args.out, args.keep_content)
        for fn in args.files:
            try:
                with open(fn, encoding="utf-8") as f:
                    payload = json.load(f)
            except (OSError, json.JSONDecodeError) as ex:
                print(f"읽기 실패 {fn}: {ex}", file=sys.stderr)
                return 2
            sink.write(parse_payload(payload))
        print(f"{sink.count}건을 {args.out}에 추가했다")
        return 0
    if args.cmd == "report":
        try:
            rep = build_report(load(args.file))
        except OSError as ex:
            print(f"읽기 실패: {ex}", file=sys.stderr)
            return 2
        sys.stdout.write(json.dumps(rep, ensure_ascii=False, indent=2) + "\n" if args.json else render(rep))
        return 0
    if args.host not in ("127.0.0.1", "localhost", "::1") and not args.allow_remote:
        print("보안상 루프백 주소만 허용한다. 다른 주소는 --allow-remote (인증이 없으니 주의).", file=sys.stderr)
        return 2
    sink = Sink(args.out, args.keep_content)
    srv = make_server(sink, args.host, args.port)
    port = srv.server_address[1]
    if args.port_file:
        with open(args.port_file, "w") as f:
            f.write(str(port))
    print(f"otel-tap 수신 중: http://{args.host}:{port}  → {args.out}  (내용 {'보존' if args.keep_content else '삭제'})", flush=True)
    print("다른 터미널에서:\n" + env_block(args.host, port, False), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        print(f"\n종료: {sink.count}건 저장. 요약은 `python3 {sys.argv[0]} report {args.out}`", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

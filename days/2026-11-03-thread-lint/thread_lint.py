#!/usr/bin/env python3
"""thread-lint — Messages API message threads(베타) 요청 로그를 문서 규칙으로 점검한다.

키·네트워크 없이 돈다. 입력은 JSONL: 한 줄 = 요청 하나와 그 응답.
  {"ts": 0, "betas": ["message-threads-2026-08-12"],
   "request": {...Messages 요청 본문, "thread": {...}...},
   "response": {"id": "msg_1", "status": 200, "stop_reason": "end_turn",
                "message_stop_ts": 2, "content": [...]}}
ts·message_stop_ts는 초 단위 숫자(선택). 없으면 시간 규칙은 건너뛴다.

사용: python3 thread_lint.py LOG.jsonl [--fail-on warn|error] [--stats] [--json]
종료 코드: 0 = 통과, 1 = --fail-on 수준 이상의 지적, 2 = 입력 오류.
"""
import argparse
import json
import sys

BETA = "message-threads-2026-08-12"
EXPIRE_S = 300          # 마지막 요청 뒤 5분
MAX_BREAKPOINTS = 4     # thread 요청 하나의 cache_control 상한
FIXED = ["model", "tool_choice", "thinking", "mcp_servers",
         "context_management", "output_config", "container.skills",
         "cache_control", "betas"]


def fixed_fingerprint(rec):
    """create 때와 매 요청 같아야 하는 값들. MCP 인증 토큰은 바뀌어도 된다."""
    req = rec.get("request", {})
    fp = {k: req.get(k) for k in ("model", "tool_choice", "thinking",
                                  "context_management", "output_config",
                                  "cache_control")}
    servers = req.get("mcp_servers")
    if isinstance(servers, list):
        servers = [{k: v for k, v in s.items() if k != "authorization_token"}
                   if isinstance(s, dict) else s for s in servers]
    fp["mcp_servers"] = servers
    cont = req.get("container")
    fp["container.skills"] = cont.get("skills") if isinstance(cont, dict) else None
    fp["betas"] = sorted(rec.get("betas") or [])
    return fp


def count_breakpoints(node):
    """중첩 구조 안의 cache_control 개수."""
    if isinstance(node, dict):
        n = 1 if node.get("cache_control") else 0
        return n + sum(count_breakpoints(v) for k, v in node.items() if k != "cache_control")
    if isinstance(node, list):
        return sum(count_breakpoints(v) for v in node)
    return 0


def size(obj):
    return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode())


def lint(records):
    out = []   # (level, code, line, message)
    chains = {}      # 응답 id -> chain
    continued = {}   # 이미 이어진 응답 id -> 줄 번호
    failed_404 = {}  # 404를 받은 previous_message_id -> 줄 번호
    stats = {"requests": 0, "creates": 0, "continues": 0, "bytes_sent": 0, "bytes_if_resent": 0}

    def add(level, code, line, msg):
        out.append((level, code, line, msg))

    for line, rec in records:
        req = rec.get("request") or {}
        resp = rec.get("response") or {}
        th = req.get("thread")
        if th is None:
            continue
        stats["requests"] += 1
        stats["bytes_sent"] += size(req)
        betas = rec.get("betas") or []
        ts = rec.get("ts")
        if BETA not in betas:
            add("error", "TL01", line, f"thread 요청인데 베타 헤더 {BETA} 가 없다")
        kind = th.get("type") if isinstance(th, dict) else None
        rid = resp.get("id")
        ok = isinstance(resp.get("status"), int) and 200 <= resp["status"] < 300

        if kind == "create":
            stats["creates"] += 1
            bp = count_breakpoints(req)
            if bp > MAX_BREAKPOINTS:
                add("error", "TL07", line, f"cache_control 중단점 {bp}개 (상한 {MAX_BREAKPOINTS}, thread_unsupported_request)")
            chain = {"fp": fixed_fingerprint(rec), "carry_bp": count_breakpoints(req.get("system")) + count_breakpoints(req.get("tools")),
                     "convo": size({"system": req.get("system"), "tools": req.get("tools"), "messages": req.get("messages")}),
                     "last_ts": ts}
            stats["bytes_if_resent"] += size(req)
            if ok and rid:
                chain["last_ts"] = ts
                chains[rid] = chain
                chain["msg_stop"] = resp.get("message_stop_ts")
                chain["content_bytes"] = size(resp.get("content") or [])
                chain["convo"] += chain["content_bytes"]
        elif kind == "continue":
            stats["continues"] += 1
            prev = th.get("previous_message_id")
            if not prev:
                add("error", "TL04", line, "continue인데 previous_message_id 가 없다")
                continue
            chain = chains.get(prev)
            if chain is None:
                add("warn", "TL04", line, f"previous_message_id {prev} 를 로그에서 찾지 못했다 (create 응답이 성공으로 저장됐는지 확인)")
            for f in ("system", "tools"):
                if f in req:
                    add("error", "TL02", line, f"continue 요청에 {f} 가 있다 (null 도 400)")
            if chain is not None:
                diff = [k for k, v in fixed_fingerprint(rec).items() if v != chain["fp"].get(k)]
                if diff:
                    add("error", "TL03", line, "고정 필드가 create 와 다르다 (thread_fingerprint_mismatch): " + ", ".join(diff))
                bp = count_breakpoints({k: v for k, v in req.items() if k not in ("system", "tools")}) + chain["carry_bp"]
                if bp > MAX_BREAKPOINTS:
                    add("error", "TL07", line, f"cache_control 중단점 {bp}개 (create 의 system·tools 몫 {chain['carry_bp']} 포함, 상한 {MAX_BREAKPOINTS})")
                if ts is not None and chain.get("last_ts") is not None and ts - chain["last_ts"] > EXPIRE_S:
                    add("warn", "TL06", line, f"직전 요청 뒤 {ts - chain['last_ts']:.0f}초 — 5분을 넘어 만료됐을 수 있다 (404 → create 로 replay 필요)")
                if ts is not None and chain.get("msg_stop") is not None and ts < chain["msg_stop"]:
                    add("warn", "TL11", line, "직전 응답의 message_stop 보다 먼저 continue 를 보냈다 (404 위험)")
                # 다음 요청 계산용: 이어 붙인 뒤 전체 대화 크기
                chain["convo"] += size(req.get("messages") or [])
                stats["bytes_if_resent"] += chain["convo"] + size({k: v for k, v in req.items() if k not in ("messages", "thread")})
            else:
                stats["bytes_if_resent"] += size(req)
            if prev in continued:
                add("error", "TL05", line, f"응답 {prev} 는 이미 {continued[prev]}줄에서 이어졌다 (thread_already_continued) — 항상 최신 응답 id 에서 이어야 한다")
            elif ok:
                continued[prev] = line
            msgs = req.get("messages") or []
            if chain is not None and chain.get("stop") == "pause_turn":
                if msgs:
                    add("error", "TL09", line, "pause_turn 응답 뒤에는 messages 를 비워 보내야 한다 (새 user 메시지는 거절된다)")
            elif msgs and isinstance(msgs[0], dict) and msgs[0].get("role") == "assistant":
                add("error", "TL08", line, "continue 의 첫 메시지가 assistant 다 — 이전 응답을 다시 보내면 안 된다 (새 메시지만)")
            if prev in failed_404:
                add("warn", "TL10", line, f"{failed_404[prev]}줄에서 404 를 받은 id 로 다시 continue 했다 — 전체 대화를 create 로 다시 보내야 한다")
            if resp.get("status") == 404:
                failed_404[prev] = line
            if ok and rid:
                new = dict(chain) if chain else {"fp": fixed_fingerprint(rec), "carry_bp": 0, "convo": 0}
                new["last_ts"] = ts
                new["msg_stop"] = resp.get("message_stop_ts")
                new["stop"] = resp.get("stop_reason")
                new["convo"] += size(resp.get("content") or [])
                chains[rid] = new
        else:
            add("error", "TL04", line, f"thread.type 은 create 또는 continue 여야 한다 (받은 값: {kind!r})")
        if kind == "create" and ok and rid:
            chains[rid]["stop"] = resp.get("stop_reason")
    return out, stats


def load(path):
    recs = []
    with open(path, encoding="utf-8") as fh:
        for n, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                recs.append((n, json.loads(raw)))
            except json.JSONDecodeError as e:
                print(f"{path}:{n}: JSON 오류: {e}", file=sys.stderr)
                sys.exit(2)
    return recs


def main(argv=None):
    ap = argparse.ArgumentParser(description="message threads 요청 로그 린터")
    ap.add_argument("log")
    ap.add_argument("--fail-on", choices=["warn", "error"], default="error")
    ap.add_argument("--stats", action="store_true", help="요청 바이트 절감 추정 출력")
    ap.add_argument("--json", action="store_true", help="결과를 JSON 으로 출력")
    a = ap.parse_args(argv)
    try:
        recs = load(a.log)
    except OSError as e:
        print(f"읽기 실패: {e}", file=sys.stderr)
        return 2
    findings, stats = lint(recs)
    errs = sum(1 for f in findings if f[0] == "error")
    warns = len(findings) - errs
    if a.json:
        print(json.dumps({"findings": [dict(level=l, code=c, line=n, message=m) for l, c, n, m in findings],
                          "stats": stats}, ensure_ascii=False, indent=2))
    else:
        for level, code, line, msg in findings:
            print(f"{a.log}:{line}: {level:5} {code}: {msg}")
        print(f"thread 요청 {stats['requests']}건 (create {stats['creates']}, continue {stats['continues']}) · error {errs} · warn {warns}")
        if a.stats and stats["bytes_if_resent"]:
            saved = stats["bytes_if_resent"] - stats["bytes_sent"]
            print(f"요청 바이트: thread {stats['bytes_sent']} / 매번 전체 재전송 추정 {stats['bytes_if_resent']} (절감 {saved}, {100*saved/stats['bytes_if_resent']:.0f}%)")
    if errs or (a.fail_on == "warn" and warns):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

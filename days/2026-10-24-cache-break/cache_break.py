#!/usr/bin/env python3
"""cache-break — Claude Code 트랜스크립트에서 프롬프트 캐시 재작성의 원인을 가르는 분석기.

`~/.claude/projects/**/*.jsonl`의 assistant 줄에서 usage를 읽어 요청 단위로 합치고(같은 requestId는 한 번),
스레드(메인 / 서브에이전트)별로 시간순으로 놓은 뒤, 큰 캐시 쓰기(기본 10만 토큰 이상)를 다음 중 하나로 분류한다.
  first-call        스레드의 첫 요청 (처음 쓰는 접두는 쓰기가 당연하다)
  idle-expiry       직전 요청 뒤 TTL(5분/1시간)을 넘겨 쉼 — 직전 응답이 턴 끝(사용자·후속 메시지를 기다림)
  tool-wait-expiry  직전 요청 뒤 TTL을 넘김 — 직전 응답이 도구 호출(긴 도구 실행·권한 대기)
  model-switch      모델이 바뀜 (캐시는 모델별)
  append            직전까지의 캐시를 거의 다 읽었고 새 내용만 덧붙임 — 정상 증가(큰 파일을 읽은 턴 등), 낭비 아님
  prefix-change     TTL 안인데 직전 캐시를 못 읽고 크게 다시 씀 — 접두가 바뀜(압축, CLAUDE.md·MCP 도구 변경 등)으로 추정
표준 라이브러리만 쓴다. 네트워크·모델 호출 없음.
"""
import argparse, glob, json, os, re, statistics, sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

# 정가 USD/MTok (입력, 5분 쓰기, 1시간 쓰기, 캐시 읽기, 출력). 출처: platform.claude.com 가격 페이지(2026-10-24 확인).
PRICES = {
    "claude-fable-5-1":  (10, 12.5, 20, 0.25, 50),
    "claude-mythos-5-1": (10, 12.5, 20, 0.25, 50),
    "claude-fable-5":    (10, 12.5, 20, 1.0, 50),
    "claude-opus-5-5":   (4, 5, 8, 0.20, 20),
    "claude-opus-5":     (5, 6.25, 10, 0.50, 25),
    "claude-sonnet-5-5": (2, 2.5, 4, 0.10, 10),
    "claude-sonnet-5":   (2, 2.5, 4, 0.20, 10),
    "claude-haiku-5-5":  (0.10, 0.125, 0.20, 0.01, 0.50),   # 프롬프트 10만 토큰 이하
    "claude-haiku-4-5":  (1, 1.25, 2, 0.10, 5),
}
HAIKU55_LONG = (0.50, 0.625, 1.0, 0.05, 2.50)               # 프롬프트 10만 토큰 초과
CATEGORIES = ["first-call", "append", "idle-expiry", "tool-wait-expiry", "model-switch", "prefix-change"]
HIT_RATIO = 0.8   # 읽기 ≥ 직전 캐시 총량의 80%면 접두가 살아 있었다고 본다
TTL_5M, TTL_1H = 300, 3600


def price_for(model, prompt_tokens):
    best = None
    for k in PRICES:
        if (model or "").startswith(k) and (best is None or len(k) > len(best)):
            best = k
    if best is None:
        return None
    if best == "claude-haiku-5-5" and prompt_tokens > 100_000:
        return HAIKU55_LONG
    return PRICES[best]


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def find_files(paths):
    out = []
    for p in paths:
        p = os.path.expanduser(p)
        if os.path.isdir(p):
            out += glob.glob(os.path.join(p, "**", "*.jsonl"), recursive=True)
        elif os.path.isfile(p):
            out.append(p)
    return sorted(set(out))


def load_requests(files):
    """requestId(없으면 message.id)별로 한 건으로 합친다. 스트리밍 때문에 같은 요청이 여러 줄로 나온다."""
    reqs, lines, bad = {}, 0, 0
    for f in files:
        sub_path = "/subagents/" in f.replace("\\", "/")
        stem = os.path.splitext(os.path.basename(f))[0]
        try:
            fh = open(f, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for raw in fh:
                try:
                    d = json.loads(raw)
                except ValueError:
                    bad += 1
                    continue
                if not isinstance(d, dict) or d.get("type") != "assistant":
                    continue
                m = d.get("message") or {}
                u = m.get("usage")
                key = d.get("requestId") or m.get("id")
                if not isinstance(u, dict) or not key or not d.get("timestamp") or m.get("model") == "<synthetic>":
                    continue
                lines += 1
                try:
                    ts = parse_ts(d["timestamp"])
                except ValueError:
                    bad += 1
                    continue
                cc = u.get("cache_creation") or {}
                w1 = int(cc.get("ephemeral_1h_input_tokens") or 0)
                w5 = int(cc.get("ephemeral_5m_input_tokens") or 0)
                tot_w = int(u.get("cache_creation_input_tokens") or 0)
                if w1 + w5 < tot_w:                       # TTL 구분이 없으면 5분 쓰기로 본다
                    w5 += tot_w - (w1 + w5)
                cur = reqs.get(key)
                side = bool(d.get("isSidechain")) or sub_path
                rec = {"key": key, "ts": ts, "model": m.get("model"), "stop": m.get("stop_reason"),
                       "input": int(u.get("input_tokens") or 0), "read": int(u.get("cache_read_input_tokens") or 0),
                       "w5": w5, "w1": w1, "output": int(u.get("output_tokens") or 0),
                       "sub": side, "agent": d.get("agentId") or (stem if sub_path else ""),
                       "session": d.get("sessionId") or stem, "file": f}
                if cur is None:
                    reqs[key] = rec
                else:                                      # 같은 요청의 뒷줄: 가장 이른 시각, 더 큰 usage, 마지막 stop_reason
                    cur["ts"] = min(cur["ts"], ts)
                    for k in ("input", "read", "w5", "w1", "output"):
                        cur[k] = max(cur[k], rec[k])
                    cur["stop"] = rec["stop"] or cur["stop"]
    return list(reqs.values()), lines, bad


def cost_parts(r):
    p = price_for(r["model"], r["input"] + r["read"] + r["w5"] + r["w1"])
    if p is None:
        return None
    pi, p5, p1, pr, po = (x / 1e6 for x in p)
    return {"input": r["input"] * pi, "read": r["read"] * pr, "w5": r["w5"] * p5, "w1": r["w1"] * p1,
            "output": r["output"] * po, "read_price": pr}


def classify(reqs):
    threads = defaultdict(list)
    for r in reqs:
        threads[(r["session"], r["agent"] if r["sub"] else "", r["sub"])].append(r)
    for t in threads.values():
        t.sort(key=lambda r: r["ts"])
        ttl, prev = TTL_5M, None
        for r in t:
            r["scope"] = "subagent" if r["sub"] else "main"
            r["gap"] = None
            if prev is None:
                r["cat"] = "first-call"
            else:
                r["gap"] = (r["ts"] - prev["ts"]).total_seconds()
                if r["model"] != prev["model"]:
                    r["cat"] = "model-switch"
                elif r["read"] >= HIT_RATIO * (prev["read"] + prev["w5"] + prev["w1"]):
                    r["cat"] = "append"
                elif r["gap"] > ttl:
                    r["cat"] = "tool-wait-expiry" if prev["stop"] == "tool_use" else "idle-expiry"
                else:
                    r["cat"] = "prefix-change"
            r["ttl"] = ttl
            ttl = TTL_1H if r["w1"] > 0 else TTL_5M if r["w5"] > 0 else ttl
            prev = r
    return threads


def parse_since(s):
    m = re.fullmatch(r"(\d+)([hd])", s or "")
    if not m:
        raise ValueError("--since는 48h, 7d 같은 형식이어야 한다")
    n = int(m.group(1))
    return timedelta(hours=n) if m.group(2) == "h" else timedelta(days=n)


def fmt_tok(n):
    return f"{n/1e6:.2f}M" if n >= 1e6 else f"{n/1e3:.1f}K" if n >= 1e3 else str(n)


def analyze(reqs, threshold):
    tot = {k: 0 for k in ("input", "read", "w5", "w1", "output")}
    cost = {k: 0.0 for k in tot}
    unpriced = 0
    cells = {}
    big_all = []
    for r in reqs:
        for k in tot:
            tot[k] += r[k]
        c = cost_parts(r)
        if c is None:
            unpriced += 1
        else:
            for k in cost:
                cost[k] += c[k]
        w = r["w5"] + r["w1"]
        if w >= threshold:
            wc = (c["w5"] + c["w1"]) if c else 0.0
            avoid = (wc - w * c["read_price"]) if c and r["cat"] not in ("first-call", "append") else 0.0
            r["w"], r["wcost"], r["avoid"] = w, wc, avoid
            big_all.append(r)
            cell = cells.setdefault((r["scope"], r["cat"]), {"n": 0, "w": [], "cost": 0.0, "avoid": 0.0})
            cell["n"] += 1
            cell["w"].append(w)
            cell["cost"] += wc
            cell["avoid"] += avoid
    total_cost = sum(cost.values())
    total_tok = sum(tot.values())
    write_tok = tot["w5"] + tot["w1"]
    big_tok = sum(r["w"] for r in big_all)
    rows = []
    for (scope, cat), c in sorted(cells.items(), key=lambda kv: (kv[0][0], CATEGORIES.index(kv[0][1]))):
        rows.append({"scope": scope, "category": cat, "count": c["n"], "write_tokens": sum(c["w"]),
                     "median_write_tokens": int(statistics.median(c["w"])), "cost_usd": round(c["cost"], 4),
                     "avoidable_usd": round(c["avoid"], 4)})
    return {"requests": len(reqs), "unpriced_requests": unpriced, "tokens": tot,
            "cost_usd": {k: round(v, 4) for k, v in cost.items()}, "total_cost_usd": round(total_cost, 4),
            "total_tokens": total_tok, "write_tokens": write_tok,
            "big": {"threshold": threshold, "count": len(big_all), "write_tokens": big_tok,
                    "share_of_write_tokens": round(big_tok / write_tok, 4) if write_tok else 0.0,
                    "cost_usd": round(sum(r["wcost"] for r in big_all), 4),
                    "avoidable_usd": round(sum(r["avoid"] for r in big_all), 4)},
            "breakdown": rows}, big_all


def advice(a):
    rows = {(r["scope"], r["category"]): r for r in a["breakdown"]}
    total = a["total_cost_usd"] or 1.0
    out = []

    def row(scope, cat):
        return rows.get((scope, cat))
    r = row("main", "idle-expiry")
    if r and r["avoidable_usd"] / total >= 0.03:
        out.append(f"메인 세션이 캐시 TTL을 넘겨 쉰 뒤 이어 쓴 큰 재작성 {r['count']}건(회피 가능 약 ${r['avoidable_usd']:.2f}): "
                   "긴 휴식 뒤에는 '한 일·다음 할 일' 세 줄을 적고 새 세션을 연다.")
    r = row("subagent", "idle-expiry")
    if r:
        out.append(f"서브에이전트 후속 메시지가 TTL을 넘겨 {r['count']}건 재작성(중앙값 {fmt_tok(r['median_write_tokens'])}): "
                   "끝난 서브에이전트에는 5분 안에 보내거나, 새로 띄워 짧은 브리프를 준다.")
    for scope in ("main", "subagent"):
        r = row(scope, "tool-wait-expiry")
        if r:
            out.append(f"{scope}가 긴 도구 실행·권한 대기 중에 캐시가 만료돼 {r['count']}건 재작성: "
                       "5분 넘는 대기는 백그라운드 실행(run_in_background)이나 메인 세션으로 옮긴다.")
    n_pc = sum(r["count"] for r in a["breakdown"] if r["category"] == "prefix-change")
    n_app = sum(r["count"] for r in a["breakdown"] if r["category"] == "append")
    n_bad = a["big"]["count"] - n_app
    if n_pc and n_bad and n_pc / n_bad >= 0.3:
        out.append(f"TTL 안인데 직전 캐시를 못 읽고 크게 다시 쓴 경우가 {n_pc}건: 압축(/compact), CLAUDE.md·MCP 도구 목록·시스템 프롬프트 변경을 의심하고 "
                   "세션 중간에 바꾸지 않는다.")
    n_ms = sum(r["count"] for r in a["breakdown"] if r["category"] == "model-switch")
    if n_ms:
        out.append(f"모델 전환 직후 재작성 {n_ms}건: 캐시는 모델별이라 세션 중간의 /model 전환은 접두 전체를 다시 쓴다.")
    if not out:
        out.append("임계값을 넘는 의심스러운 재작성이 없다." if a["big"]["count"] == 0 else "큰 쓰기는 첫 호출이거나 정상 증가(append)라 조치할 것이 없다.")
    return out


def render(a, big_all, top, meta):
    L = [f"# cache-break — {meta['window']}", "",
         f"파일 {meta['files']}개 · assistant 줄 {meta['lines']} → 요청 {a['requests']}건 (스레드 메인 {meta['main_threads']} / 서브에이전트 {meta['sub_threads']})"
         + (f" · 읽기 실패 줄 {meta['bad']}" if meta["bad"] else ""), ""]
    if a["unpriced_requests"]:
        L += [f"⚠ 가격표에 없는 모델 요청 {a['unpriced_requests']}건은 비용에서 제외했다.", ""]
    L += ["## 토큰 몫과 비용 몫 (정가 환산, 구독 한도와는 다르다)", "",
          "| 구분 | 토큰 | 토큰 몫 | 비용 | 비용 몫 |", "|---|---:|---:|---:|---:|"]
    t, c = a["tokens"], a["cost_usd"]
    tt, tc = a["total_tokens"] or 1, a["total_cost_usd"] or 1.0
    for label, tk, ck in (("입력(캐시 안 됨)", "input", "input"), ("캐시 읽기", "read", "read"), ("캐시 쓰기 5분", "w5", "w5"),
                          ("캐시 쓰기 1시간", "w1", "w1"), ("출력", "output", "output")):
        L.append(f"| {label} | {fmt_tok(t[tk])} | {t[tk]/tt:.1%} | ${c[ck]:.2f} | {c[ck]/tc:.1%} |")
    L.append(f"| **합계** | {fmt_tok(a['total_tokens'])} | | **${a['total_cost_usd']:.2f}** | |")
    b = a["big"]
    L += ["", f"## 큰 캐시 쓰기 (한 요청 {fmt_tok(b['threshold'])} 토큰 이상)", "",
          f"{b['count']}건 · 쓰기 토큰의 {b['share_of_write_tokens']:.1%} · 쓰기 비용 ${b['cost_usd']:.2f} · "
          f"그중 캐시가 살아 있었다면 아낄 수 있던 금액 약 ${b['avoidable_usd']:.2f}", ""]
    if a["breakdown"]:
        L += ["| 스레드 | 원인 | 건수 | 쓰기 토큰 | 중앙값 | 비용 | 회피 가능 |", "|---|---|---:|---:|---:|---:|---:|"]
        for r in a["breakdown"]:
            L.append(f"| {r['scope']} | {r['category']} | {r['count']} | {fmt_tok(r['write_tokens'])} | "
                     f"{fmt_tok(r['median_write_tokens'])} | ${r['cost_usd']:.2f} | ${r['avoidable_usd']:.2f} |")
    rew = [r for r in big_all if r["cat"] != "append"]
    if rew and top:
        L += ["", f"## 비싼 재작성 상위 {min(top, len(rew))}건 (정상 증가 append 제외)", "", "| 시각(UTC) | 스레드 | 원인 | 쉰 시간 | 쓰기 토큰 | 비용 | 세션 |", "|---|---|---|---:|---:|---:|---|"]
        for r in sorted(rew, key=lambda r: -r["wcost"])[:top]:
            gap = "-" if r["gap"] is None else f"{r['gap']/60:.1f}분"
            L.append(f"| {r['ts']:%m-%d %H:%M} | {r['scope']} | {r['cat']} | {gap} | {fmt_tok(r['w'])} | ${r['wcost']:.2f} | {r['session'][:8]} |")
    L += ["", "## 조치 제안", ""] + [f"- {x}" for x in advice(a)]
    return "\n".join(L) + "\n"


def main(argv=None):
    class Parser(argparse.ArgumentParser):
        def error(self, message):                       # argparse 기본은 exit 2라 "기록 없음"과 겹친다
            sys.stderr.write(f"오류: {message}\n")
            sys.exit(1)
    ap = Parser(description="Claude Code 트랜스크립트에서 캐시 재작성의 원인을 분류한다. 종료 코드: 0=분석함, 2=usage가 있는 기록 없음, 1=옵션 오류.")
    ap.add_argument("paths", nargs="*", default=["~/.claude/projects"], help="*.jsonl 파일 또는 폴더 (기본 ~/.claude/projects)")
    ap.add_argument("--since", help="최근 구간만 보고 (예: 48h, 7d). 분류는 전체 기록으로 한 뒤 구간을 자른다")
    ap.add_argument("--threshold", type=int, default=100_000, help="큰 쓰기로 볼 캐시 쓰기 토큰 수 (기본 100000)")
    ap.add_argument("--top", type=int, default=10, help="비싼 재작성 목록 길이 (기본 10, 0이면 생략)")
    ap.add_argument("--json", action="store_true", help="Markdown 대신 JSON 출력")
    ap.add_argument("--now", help="현재 시각 ISO8601 (테스트용)")
    args = ap.parse_args(argv)
    if args.threshold < 1 or args.top < 0:
        ap.error("--threshold는 1 이상, --top은 0 이상이어야 한다")
    try:
        delta = parse_since(args.since) if args.since else None
        now = parse_ts(args.now) if args.now else datetime.now(timezone.utc)
    except ValueError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    files = find_files(args.paths)
    reqs, lines, bad = load_requests(files)
    if not reqs:
        print("usage가 있는 assistant 기록을 찾지 못했다: " + ", ".join(args.paths), file=sys.stderr)
        return 2
    threads = classify(reqs)
    if delta:
        cutoff = now - delta
        reqs = [r for r in reqs if r["ts"] >= cutoff]
        if not reqs:
            print(f"최근 {args.since} 안의 기록이 없다", file=sys.stderr)
            return 2
    a, big_all = analyze(reqs, args.threshold)
    meta = {"window": f"최근 {args.since}" if delta else "전체 기간", "files": len(files), "lines": lines, "bad": bad,
            "main_threads": sum(1 for k in threads if not k[2]), "sub_threads": sum(1 for k in threads if k[2])}
    if args.json:
        a["meta"] = meta
        a["advice"] = advice(a)
        a["top"] = [{"ts": r["ts"].isoformat(), "scope": r["scope"], "category": r["cat"], "gap_seconds": r["gap"],
                     "write_tokens": r["w"], "cost_usd": round(r["wcost"], 4), "session": r["session"]}
                    for r in sorted((x for x in big_all if x["cat"] != "append"), key=lambda r: -r["wcost"])[:args.top]]
        print(json.dumps(a, ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(render(a, big_all, args.top, meta))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""cost-top — Usage and Cost Analytics API(베타, 2026-10-29)로 조직의 비용·사용량 상위 소비자를 뽑는다.

  GET /v1/organizations/analytics/cost   (비용, USD 센트 십진 문자열)
  GET /v1/organizations/analytics/usage  (토큰·요청 수)

보내기 전에 문서의 제약(31일, 1m 버킷 24시간, 그룹 5개, 시작일 범위)을 로컬에서 검사하고,
응답의 data_refreshed_at 이후 구간은 "부분"으로 표시해 급증 판정에서 뺀다. 표준 라이브러리만 쓴다.

종료 코드: 0=정상 · 1=급증 구간 있음(--fail-on-spike일 때만) · 2=요청 오류/입력 오류 · 3=사용법 오류
"""
import argparse
import json
import os
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

BETA = "analytics-usage-cost-2026-08-24"
API_VERSION = "2023-06-01"
MIN_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
USAGE_ORDER = ("total_tokens", "output_tokens", "uncached_input_tokens", "requests", "time")
COST_ONLY_DIMS = ("cost_type", "token_type")  # 5개 한도에 안 들어가는 비용 전용 차원
BUCKETS = {"1m": timedelta(minutes=1), "1h": timedelta(hours=1), "1d": timedelta(days=1)}
MAX_PAGES = 100

SAMPLE = {  # --dry-run이 보여 주는 합성 응답 (실제 조직 데이터 아님)
    "data": [
        {"starting_at": f"2026-10-{d:02d}T00:00:00Z", "ending_at": f"2026-10-{d + 1:02d}T00:00:00Z",
         "group": {"model": m, "service_tier": None},
         "cost": {"currency": "USD", "amount": amt, "list_amount": lst, "requests": None}}
        for d, m, amt, lst in [
            (20, "claude-opus-5-5", "41280.000000", "51600.000000"),
            (20, "claude-sonnet-5-5", "9100.000000", "9100.000000"),
            (21, "claude-opus-5-5", "39900.000000", "49875.000000"),
            (21, "claude-sonnet-5-5", "9500.000000", "9500.000000"),
            (22, "claude-opus-5-5", "212000.000000", "265000.000000"),
            (22, "claude-sonnet-5-5", "8800.000000", "8800.000000"),
            (23, "claude-opus-5-5", "40100.000000", "50125.000000"),
            (23, "claude-sonnet-5-5", "9300.000000", "9300.000000"),
        ]
    ],
    "has_more": False, "next_page": None, "data_refreshed_at": "2026-10-24T00:00:00Z",
}


class Fail(Exception):
    pass


def parse_ts(s):
    s = s.strip()
    try:
        if len(s) == 10:
            return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        raise Fail(f"시각을 읽을 수 없다: {s!r} (YYYY-MM-DD 또는 RFC 3339)")


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def validate(endpoint, start, end, bucket, group_by, order_by, now, filters):
    """문서에 적힌 제약을 위반하는 항목을 문자열 목록으로 돌려준다."""
    errs = []
    if start < MIN_START:
        errs.append(f"starting_at은 2026-01-01 이후여야 한다 (받은 값 {iso(start)})")
    if start < now - timedelta(days=365):
        errs.append("starting_at은 최근 365일 안이어야 한다")
    if end is not None:
        if end <= start:
            errs.append("ending_at은 starting_at보다 뒤여야 한다")
        elif end - start > timedelta(days=31):
            errs.append(f"한 요청은 최대 31일이다 (요청 {(end - start).days}일) — 기간을 나눠 여러 번 부르라")
    if bucket and end is None:
        errs.append("time_bucket_width를 쓰면 ending_at이 필요하다")
    if bucket == "1m" and end is not None and end - start > timedelta(hours=24):
        errs.append("1m 버킷은 한 요청이 최대 24시간이다")
    shared = [g for g in group_by if g not in COST_ONLY_DIMS]
    if len(shared) > 5:
        errs.append(f"group_by는 최대 5개다 (받은 값 {len(shared)}개: {', '.join(shared)})")
    if endpoint == "usage":
        bad = [g for g in group_by if g in COST_ONLY_DIMS]
        if bad:
            errs.append(f"{', '.join(bad)}는 cost 엔드포인트에서만 쓴다")
        if order_by and order_by not in USAGE_ORDER:
            errs.append(f"order_by는 {', '.join(USAGE_ORDER)} 중 하나다 (받은 값 {order_by})")
    if order_by == "time" and not bucket:
        errs.append("order_by=time은 time_bucket_width와 같이 써야 한다")
    for k, vals in filters:
        if len(vals) > 100:
            errs.append(f"필터 {k}[]는 값 100개까지다 (받은 값 {len(vals)}개)")
    return errs


def build_query(start, end, bucket, group_by, order_by, order, limit, filters, page=None):
    q = [("starting_at", iso(start))]
    if end is not None:
        q.append(("ending_at", iso(end)))
    if bucket:
        q.append(("time_bucket_width", bucket))
    q += [("group_by[]", g) for g in group_by]
    if order_by:
        q.append(("order_by", order_by))
    if order:
        q.append(("order", order))
    q.append(("limit", str(limit)))
    for k, vals in filters:
        q += [(f"{k}[]", v) for v in vals]
    if page:
        q.append(("page", page))
    return "&".join(f"{k}={urllib.parse.quote(v, safe=':')}" for k, v in q)


def fetch_all(base, endpoint, query_fn, key):
    pages, token = [], None
    for _ in range(MAX_PAGES):
        url = f"{base.rstrip('/')}/v1/organizations/analytics/{endpoint}?{query_fn(token)}"
        req = urllib.request.Request(url, headers={
            "x-api-key": key, "anthropic-version": API_VERSION, "anthropic-beta": BETA,
            "user-agent": "cost-top/1.0 (claude-daily-lab)"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = json.load(r)
        except urllib.error.HTTPError as e:
            detail = e.read(400).decode("utf-8", "replace").replace(key, "***")
            raise Fail(f"HTTP {e.code} {endpoint}: {detail}")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            raise Fail(f"요청 실패 {endpoint}: {type(e).__name__}: {e}")
        pages.append(body)
        token = body.get("next_page") if body.get("has_more") else None
        if not token:
            return pages
    raise Fail(f"{MAX_PAGES}쪽을 넘어도 끝나지 않아 멈춘다 (group_by를 줄이거나 limit을 키우라)")


def usd(cents):
    """센트 십진 문자열 → Decimal 달러. 'null'/빈 값은 0."""
    try:
        return Decimal(str(cents)) / 100
    except (InvalidOperation, TypeError):
        return Decimal(0)


def label_of(group, group_by):
    parts = []
    for g in group_by:
        v = group.get(g)
        if isinstance(v, dict):  # actor는 {type, ...} 객체
            v = ":".join(str(v[k]) for k in ("type", "id", "name", "email") if v.get(k)) or json.dumps(v, sort_keys=True)
        parts.append(str(v) if v is not None else "(없음)")
    return " | ".join(parts) if parts else "(전체)"


def aggregate(endpoint, pages, group_by):
    """쪽·버킷을 합쳐 {label: 지표}, {bucket_start: 합계}, 메타를 만든다."""
    by_label, by_bucket, refreshed, notes = {}, {}, None, set()
    for p in pages:
        refreshed = p.get("data_refreshed_at", refreshed)
        for row in p.get("data", []):
            lab = label_of(row.get("group") or {}, group_by)
            if endpoint == "cost":
                c = row.get("cost") or {}
                val, lst = usd(c.get("amount")), usd(c.get("list_amount"))
                req = c.get("requests") or 0
                if (row.get("group") or {}).get("service_tier") == "priority":
                    notes.add("Priority Tier 약정분은 비용 0으로 잡힌다 — 약정 요금은 이 데이터에 없다")
            else:
                u = row.get("usage") or {}
                val, lst, req = Decimal(u.get("total_tokens") or 0), Decimal(u.get("cache_read_input_tokens") or 0), u.get("requests") or 0
            m = by_label.setdefault(lab, {"value": Decimal(0), "aux": Decimal(0), "requests": 0})
            m["value"] += val
            m["aux"] += lst
            m["requests"] += req
            b = by_bucket.setdefault(row.get("starting_at"), {"value": Decimal(0), "end": row.get("ending_at")})
            b["value"] += val
    return by_label, by_bucket, refreshed, sorted(notes)


def find_spikes(by_bucket, refreshed, factor, min_value):
    """데이터가 다 찬 버킷의 중앙값보다 factor배 이상 큰 버킷. (bucket, 값, 배수) 목록."""
    full = {s: b for s, b in by_bucket.items() if s and refreshed and b["end"] and b["end"] <= refreshed}
    vals = [b["value"] for b in full.values() if b["value"] > 0]
    if len(vals) < 3:
        return []
    med = statistics.median(vals)
    if med <= 0:
        return []
    return [(s, b["value"], b["value"] / med) for s, b in sorted(full.items())
            if b["value"] >= min_value and b["value"] >= med * Decimal(str(factor))]


def render(endpoint, group_by, by_label, by_bucket, refreshed, notes, spikes, top, bucket):
    L = []
    cost = endpoint == "cost"
    fmt = (lambda v: f"${v:,.2f}") if cost else (lambda v: f"{int(v):,}")
    total = sum((m["value"] for m in by_label.values()), Decimal(0))
    unit = "비용" if cost else "토큰"
    L.append(f"## {unit} 합계: {fmt(total)}  (그룹 {len(by_label)}개, 기준 {', '.join(group_by) or '전체'})")
    if refreshed is None:
        L.append("⚠ data_refreshed_at이 null — 이 기간은 아직 집계된 데이터가 없다. 합계를 믿지 말 것")
    else:
        L.append(f"데이터 갱신 시각: {refreshed} (이후 구간은 비었거나 일부, 최대 24시간 지연·월말 7일까지 수정 가능)")
    L.append("")
    head = "| # | 그룹 | " + ("비용 | 정가 | 할인 |" if cost else "토큰 | 캐시 읽기 비중 |") + " 요청 | 비중 |"
    L += [head, "|" + "---|" * (head.count("|") - 1)]
    ranked = sorted(by_label.items(), key=lambda kv: kv[1]["value"], reverse=True)
    for i, (lab, m) in enumerate(ranked[:top], 1):
        share = f"{(m['value'] / total * 100):.1f}%" if total else "-"
        if cost:
            disc = f"{((1 - m['value'] / m['aux']) * 100):.0f}%" if m["aux"] else "-"
            mid = f"{fmt(m['value'])} | {fmt(m['aux'])} | {disc}"
        else:
            mid = f"{fmt(m['value'])} | {(m['aux'] / m['value'] * 100):.0f}%" if m["value"] else "0 | -"
        L.append(f"| {i} | {lab} | {mid} | {m['requests'] or '-'} | {share} |")
    if len(ranked) > top:
        rest = sum((m["value"] for _, m in ranked[top:]), Decimal(0))
        L.append(f"| … | 나머지 {len(ranked) - top}개 | {fmt(rest)} | | | | |" if cost else f"| … | 나머지 {len(ranked) - top}개 | {fmt(rest)} | | | |")
    if bucket and by_bucket:
        L += ["", f"## {bucket} 버킷별 합계"]
        spike_set = {s for s, _, _ in spikes}
        for s, b in sorted(by_bucket.items()):
            partial = not (refreshed and b["end"] and b["end"] <= refreshed)
            flag = " ← 급증" if s in spike_set else (" (부분 데이터)" if partial else "")
            L.append(f"- {s}  {fmt(b['value'])}{flag}")
    for s, v, x in spikes:
        L.append(f"\n🔺 {s}: {fmt(v)} — 중앙값의 {x:.1f}배")
    for n in notes:
        L.append(f"\nℹ {n}")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("endpoint", choices=["cost", "usage"], help="조회할 엔드포인트")
    ap.add_argument("--days", type=int, help="오늘 00:00Z 이전 N일 (--from/--to 대신)")
    ap.add_argument("--from", dest="start", help="시작 (YYYY-MM-DD 또는 RFC 3339, 포함)")
    ap.add_argument("--to", dest="end", help="끝 (제외)")
    ap.add_argument("--group-by", action="append", default=[], help="차원 (반복 가능, 기본 model)")
    ap.add_argument("--bucket", choices=sorted(BUCKETS), help="시간 버킷 (급증 판정에 필요)")
    ap.add_argument("--filter", action="append", default=[], metavar="KEY=V1,V2", help="예: models=claude-opus-5-5 → models[]=…")
    ap.add_argument("--order-by")
    ap.add_argument("--limit", type=int, default=100, help="쪽 크기 (기본 100)")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--spike-factor", type=float, default=3.0, help="중앙값의 몇 배부터 급증 (기본 3)")
    ap.add_argument("--spike-min", type=float, help="급증으로 칠 최소값 (비용 USD 기본 1, 토큰 기본 1000000)")
    ap.add_argument("--fail-on-spike", action="store_true")
    ap.add_argument("--base-url", default="https://api.anthropic.com")
    ap.add_argument("--key-env", default="ANTHROPIC_ADMIN_KEY", help="키를 읽을 환경 변수 (없으면 ANTHROPIC_API_KEY)")
    ap.add_argument("--input", help="저장해 둔 응답 JSON(한 쪽 또는 쪽 배열)을 읽는다. 네트워크 안 씀")
    ap.add_argument("--dry-run", action="store_true", help="요청을 만들어 검사·출력만 하고 합성 샘플로 보고서를 그린다")
    ap.add_argument("--json", action="store_true", help="집계 결과를 JSON으로 출력")
    ap.add_argument("--now", help="현재 시각 (테스트용)")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 3 if e.code else 0
    try:
        return run(a)
    except Fail as e:
        print(f"오류: {e}", file=sys.stderr)
        return 2


def run(a):
    now = parse_ts(a.now) if a.now else datetime.now(timezone.utc)
    if a.days:
        end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=a.days)
    elif a.start:
        start, end = parse_ts(a.start), (parse_ts(a.end) if a.end else None)
    else:
        raise Fail("--days 또는 --from이 필요하다")
    group_by = a.group_by or ["model"]
    filters = []
    for f in a.filter:
        if "=" not in f:
            raise Fail(f"--filter는 KEY=V1,V2 형식이다: {f!r}")
        k, v = f.split("=", 1)
        filters.append((k, [x for x in v.split(",") if x]))
    errs = validate(a.endpoint, start, end, a.bucket, group_by, a.order_by, now, filters)
    if errs:
        raise Fail("요청이 문서의 제약을 어긴다:\n  - " + "\n  - ".join(errs))
    qf = lambda page: build_query(start, end, a.bucket, group_by, a.order_by, None, a.limit, filters, page)

    if a.input:
        data = json.load(open(a.input, encoding="utf-8"))
        pages = data if isinstance(data, list) else [data]
    elif a.dry_run:
        url = f"{a.base_url.rstrip('/')}/v1/organizations/analytics/{a.endpoint}?{qf(None)}"
        if a.endpoint == "usage":
            raise Fail("--dry-run 샘플은 cost 전용이다. usage는 --input으로 저장한 응답을 읽으라")
        print(f"[dry-run] GET {url}\n[dry-run] 헤더: x-api-key(값 숨김), anthropic-version: {API_VERSION}, anthropic-beta: {BETA}")
        print("[dry-run] 아래는 합성 샘플 응답으로 그린 보고서다 (실제 조직 데이터 아님)\n")
        pages = [SAMPLE]
    else:
        key = os.environ.get(a.key_env) or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise Fail(f"키가 없다: {a.key_env}(또는 ANTHROPIC_API_KEY)에 Admin 키를 넣거나 --dry-run/--input을 쓰라")
        pages = fetch_all(a.base_url, a.endpoint, qf, key)

    by_label, by_bucket, refreshed, notes = aggregate(a.endpoint, pages, group_by)
    min_v = Decimal(str(a.spike_min if a.spike_min is not None else (1 if a.endpoint == "cost" else 1_000_000)))
    spikes = find_spikes(by_bucket, refreshed, a.spike_factor, min_v) if a.bucket or by_bucket else []
    if a.json:
        print(json.dumps({"groups": {k: {kk: str(vv) for kk, vv in v.items()} for k, v in by_label.items()},
                          "spikes": [{"bucket": s, "value": str(v), "x_median": round(float(x), 2)} for s, v, x in spikes],
                          "data_refreshed_at": refreshed}, ensure_ascii=False, indent=2))
    else:
        print(render(a.endpoint, group_by, by_label, by_bucket, refreshed, notes, spikes, a.top, a.bucket or ("1d" if len(by_bucket) > 1 else None)))
    return 1 if (spikes and a.fail_on_spike) else 0


if __name__ == "__main__":
    sys.exit(main())

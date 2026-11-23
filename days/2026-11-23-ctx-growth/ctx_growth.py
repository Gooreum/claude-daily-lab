#!/usr/bin/env python3
"""ctx-growth — Claude Code 트랜스크립트에서 "컨텍스트가 무엇 때문에 커졌나"를 가르는 분석기.

생각(thinking) 블록은 기록에 본문이 비고 서명만 남아서, 블록 바이트를 세면 생각이 작아 보인다.
그래서 사용량 증가(usage delta)로 잰다 (dev.to 11-22 sungwoo_lee 글의 방법):
  1. 줄을 requestId로 합친다 (스트리밍으로 같은 요청이 여러 줄)
  2. 요청별 점유량 = input + cache_read + cache_creation
  3. 같은 스레드의 인접한 두 요청 (prev, cur)마다
       증가   = 점유량(cur) - 점유량(prev)
       보이는 = prev의 보이는 출력(text·tool_use 입력) + 둘 사이에 들어온 사용자·도구 결과 바이트 → 토큰(바이트/계수)
       남는 몫 = 증가 - 보이는   (= 생각 + 계수 오차 + 시스템 추가분)
  4. 쌍별 비율(남는 몫/증가)의 중앙값을 판정 통계로 쓴다.
교차 점검: prev의 output_tokens 중 보이는 출력으로 설명되지 않는 몫(출력 기준 생각 몫).
대조군: 블록 바이트만 센 순진한 방법 — 값이 얼마나 어긋나는지 같이 보여 준다.
표준 라이브러리만 쓴다. 네트워크·모델 호출 없음.
"""
import argparse, glob, json, os, statistics, sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

DEFAULT_BPT = 4.0   # 바이트/토큰 환산 계수. 고른 상수일 뿐이라 --sensitivity로 흔들어 본다.


def find_files(paths):
    out = []
    for p in paths:
        p = os.path.expanduser(p)
        if os.path.isdir(p):
            out += glob.glob(os.path.join(p, "**", "*.jsonl"), recursive=True)
        elif os.path.isfile(p):
            out.append(p)
    return sorted(set(out))


def parse_ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None


def size(x):
    """블록·문자열의 보이는 바이트 수. 생각 블록은 따로 센다."""
    if isinstance(x, str):
        return len(x.encode("utf-8", "replace"))
    return len(json.dumps(x, ensure_ascii=False).encode("utf-8", "replace"))


def assistant_bytes(block):
    """(보이는 바이트, 생각 블록 바이트). thinking은 기록에 남은 필드(text/thinking/signature) 길이만 센다."""
    if not isinstance(block, dict):
        return size(block), 0
    t = block.get("type")
    if t in ("thinking", "redacted_thinking"):
        return 0, sum(size(block.get(k) or "") for k in ("thinking", "text", "signature", "data"))
    if t == "text":
        return size(block.get("text") or ""), 0
    if t == "tool_use":
        return size(block.get("name") or "") + size(block.get("input") or {}), 0
    return size(block), 0


def user_bytes(content):
    if isinstance(content, str):
        return size(content)
    n = 0
    for b in content or []:
        if isinstance(b, dict) and b.get("type") == "tool_result":
            n += size(b.get("content") or "")
        elif isinstance(b, dict) and b.get("type") == "text":
            n += size(b.get("text") or "")
        else:
            n += size(b)
    return n


def load(files):
    """스레드(파일, 서브에이전트 여부)별로 파일 순서대로 요청 목록을 만든다.
    반환: threads{key: [req...]}, 읽은 assistant 줄 수, 깨진 줄 수"""
    threads, lines, bad = {}, 0, 0
    for f in files:
        try:
            fh = open(f, encoding="utf-8", errors="replace")
        except OSError:
            continue
        stem = os.path.splitext(os.path.basename(f))[0]
        sub_path = "/subagents/" in f.replace("\\", "/")
        order, byid, seen_blocks = {}, {}, set()
        pending_user = defaultdict(int)     # 스레드별: 직전 요청 이후 들어온 사용자·도구 결과 바이트
        with fh:
            for raw in fh:
                try:
                    d = json.loads(raw)
                except ValueError:
                    bad += 1
                    continue
                if not isinstance(d, dict):
                    continue
                side = bool(d.get("isSidechain")) or sub_path
                tkey = (f, d.get("agentId") or "") if side else (f, "")
                typ, m = d.get("type"), d.get("message") or {}
                if typ == "user":
                    pending_user[tkey] += user_bytes(m.get("content"))
                    continue
                if typ != "assistant":
                    continue
                u = m.get("usage")
                key = d.get("requestId") or m.get("id")
                if not isinstance(u, dict) or not key or m.get("model") == "<synthetic>":
                    continue
                lines += 1
                occ = (int(u.get("input_tokens") or 0) + int(u.get("cache_read_input_tokens") or 0)
                       + int(u.get("cache_creation_input_tokens") or 0))
                rk = (tkey, key)
                r = byid.get(rk)
                if r is None:
                    r = {"key": key, "model": m.get("model"), "ts": parse_ts(d.get("timestamp")),
                         "occ": occ, "out": int(u.get("output_tokens") or 0), "vis": 0, "think": 0,
                         "user_before": pending_user[tkey], "session": d.get("sessionId") or stem, "file": f}
                    pending_user[tkey] = 0
                    byid[rk] = r
                    threads.setdefault(tkey, []).append(r)
                else:                                  # 뒷줄: 더 큰 usage를 취한다
                    r["occ"] = max(r["occ"], occ)
                    r["out"] = max(r["out"], int(u.get("output_tokens") or 0))
                content = m.get("content")
                for b in (content if isinstance(content, list) else [content] if content else []):
                    bk = (rk, json.dumps(b, sort_keys=True, ensure_ascii=False))   # 같은 블록의 반복 줄은 한 번만
                    if bk in seen_blocks:
                        continue
                    seen_blocks.add(bk)
                    v, t = assistant_bytes(b)
                    r["vis"] += v
                    r["think"] += t
    return threads, lines, bad


def pairs(thread, bpt):
    """인접 쌍마다 dict(growth, visible, resid, ratio, out_ratio)를 낸다. 증가가 0 이하(압축·새 접두)면 건너뛴다."""
    res, skipped = [], 0
    for prev, cur in zip(thread, thread[1:]):
        g = cur["occ"] - prev["occ"]
        if g <= 0:
            skipped += 1
            continue
        vis_tok = (prev["vis"] + cur["user_before"]) / bpt
        resid = max(0.0, g - vis_tok)
        o = None
        if prev["out"] > 0:
            o = max(0.0, prev["out"] - prev["vis"] / bpt) / prev["out"]
        res.append({"growth": g, "visible": min(vis_tok, g), "resid": resid, "ratio": resid / g,
                    "out_ratio": o, "naive_think": prev["think"], "naive_vis": prev["vis"] + cur["user_before"]})
    return res, skipped


def summarize(ps):
    if not ps:
        return None
    g = sum(p["growth"] for p in ps)
    outs = [p["out_ratio"] for p in ps if p["out_ratio"] is not None]
    nt, nv = sum(p["naive_think"] for p in ps), sum(p["naive_vis"] for p in ps)
    return {"pairs": len(ps), "growth": g,
            "median_ratio": statistics.median(p["ratio"] for p in ps),
            "aggregate_ratio": sum(p["resid"] for p in ps) / g,
            "out_median": statistics.median(outs) if outs else None,
            "naive_ratio": nt / (nt + nv) if nt + nv else 0.0}


def pct(x):
    return "   - " if x is None else f"{x*100:5.1f}%"


def main(argv=None):
    ap = argparse.ArgumentParser(description="트랜스크립트의 컨텍스트 증가를 생각 몫과 보이는 몫으로 가른다.")
    ap.add_argument("paths", nargs="*", default=["~/.claude/projects"], help="jsonl 파일이나 폴더 (기본 ~/.claude/projects)")
    ap.add_argument("--bpt", type=float, default=DEFAULT_BPT, help="바이트/토큰 환산 계수 (기본 4.0)")
    ap.add_argument("--since-days", type=float, help="이 기간 안에 시작한 요청만")
    ap.add_argument("--min-pairs", type=int, default=3, help="이 쌍 수 미만인 스레드는 표에서 뺀다 (기본 3)")
    ap.add_argument("--top", type=int, default=10, help="표에 낼 스레드 수 (증가량 큰 순, 기본 10)")
    ap.add_argument("--sensitivity", action="store_true", help="계수 3.0·4.0·5.0·6.0에서 전체 중앙값이 얼마나 움직이는지 표시")
    ap.add_argument("--json", action="store_true", help="JSON으로 출력")
    a = ap.parse_args(argv)
    if a.bpt <= 0:
        print("오류: --bpt는 0보다 커야 한다", file=sys.stderr)
        return 2
    files = find_files(a.paths)
    if not files:
        print("기록 파일을 찾지 못했다: " + ", ".join(a.paths), file=sys.stderr)
        return 2
    threads, lines, bad = load(files)
    if a.since_days is not None:
        cut = datetime.now(timezone.utc) - timedelta(days=a.since_days)
        threads = {k: [r for r in t if r["ts"] and r["ts"] >= cut] for k, t in threads.items()}
    rows, allp, skipped_total = [], [], 0
    for k, t in threads.items():
        t.sort(key=lambda r: (r["ts"] is None, r["ts"]))   # 시각이 없으면 파일 순서 유지(안정 정렬)
        ps, sk = pairs(t, a.bpt)
        skipped_total += sk
        allp += ps
        s = summarize(ps)
        if s and s["pairs"] >= a.min_pairs:
            rows.append({"thread": os.path.basename(k[0]) + (f"#{k[1]}" if k[1] else ""), "requests": len(t), **s})
    total = summarize(allp)
    sens = {}
    if a.sensitivity and total:
        for b in (3.0, 4.0, 5.0, 6.0):
            ps = [p for t in threads.values() for p in pairs(t, b)[0]]
            sens[b] = summarize(ps)["median_ratio"]
    if a.json:
        print(json.dumps({"files": len(files), "assistant_lines": lines, "bad_lines": bad, "skipped_pairs": skipped_total,
                          "bpt": a.bpt, "total": total, "threads": rows, "sensitivity": sens}, ensure_ascii=False, indent=2))
        return 0 if total else 1
    print(f"파일 {len(files)}개, assistant 줄 {lines}개, 깨진 줄 {bad}개, 건너뛴 쌍 {skipped_total}개(증가 ≤ 0: 압축·새 접두), 환산 계수 {a.bpt:g} 바이트/토큰")
    if not total:
        print("쌍이 없다: 같은 스레드에 요청이 둘 이상 있어야 증가를 잴 수 있다.")
        return 1
    rows.sort(key=lambda r: -r["growth"])
    print(f"\n{'스레드':<34}{'요청':>5}{'쌍':>5}{'증가(토큰)':>12}{'생각 몫(중앙값)':>16}{'출력 기준':>10}{'순진(바이트)':>13}")
    for r in rows[:a.top]:
        print(f"{r['thread'][:33]:<34}{r['requests']:>5}{r['pairs']:>5}{r['growth']:>12,}{pct(r['median_ratio']):>16}{pct(r['out_median']):>10}{pct(r['naive_ratio']):>13}")
    print(f"\n전체  쌍 {total['pairs']}개, 증가 {total['growth']:,} 토큰")
    print(f"  생각 몫 (쌍별 중앙값)   {pct(total['median_ratio'])}   ← 판정 통계")
    print(f"  생각 몫 (합계 기준)      {pct(total['aggregate_ratio'])}   (극단 쌍에 끌려간다)")
    print(f"  출력 기준 교차 점검      {pct(total['out_median'])}   (이전 응답 output_tokens 중 보이는 출력으로 설명 안 되는 몫)")
    print(f"  순진한 방법(블록 바이트)  {pct(total['naive_ratio'])}   ← 생각 본문이 비어 있어 작게 나온다")
    if sens:
        print("  계수 민감도: " + "  ".join(f"{b:g}→{pct(v).strip()}" for b, v in sens.items()))
    print("\n주의: '생각 몫'은 생각 + 계수 오차 + 시스템 추가분의 합이다. 비율은 추정이지 측정값이 아니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""cache_meter.py — 프롬프트 캐시가 실제로 맞는지 재는 측정기.

같은 긴 시스템 프롬프트로 `claude -p`를 N회 호출하며 응답 JSON의
`usage.cache_creation_input_tokens`(캐시 쓰기), `usage.cache_read_input_tokens`(캐시 읽기),
`usage.input_tokens`(캐시 안 된 입력), `total_cost_usd`, `duration_ms`를 모은다.

시나리오 세 개를 같은 조건으로 돌려 비교한다.
  stable        — 매번 완전히 같은 시스템 프롬프트. 2회차부터 읽기 적중을 기대.
  volatile-head — 시스템 프롬프트 맨 앞에 시각·난수 한 줄. 접두사가 깨져 매번 다시 쓴다(조용한 무효화).
  volatile-tail — 같은 한 줄을 맨 뒤에. 앞부분 접두사는 살아 있어 부분 적중을 기대.

--dry-run이면 시드 고정 가짜 결과로 그래프만 그린다. 키는 필요 없다(Claude Code 로그인 사용).
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_MODEL = "claude-haiku-5-5"
SCENARIOS = ["stable", "volatile-head", "volatile-tail"]
QUESTION = "In one short sentence, what is the refund window for enterprise customers? Answer from the handbook only."


# ---------------------------------------------------------------- prompts

def handbook(paragraphs: int = 60) -> str:
    """캐시가 걸릴 만큼 긴(수천 토큰) 가짜 사내 핸드북. 결정적으로 생성한다."""
    rng = random.Random(42)
    topics = ["refunds", "onboarding", "security", "expenses", "on-call", "data retention", "vendor review",
              "release process", "incident severity", "travel", "hiring", "access requests", "backups", "SLAs"]
    lines = ["ACME INTERNAL HANDBOOK (synthetic, for cache measurement)", ""]
    for i in range(paragraphs):
        t = topics[i % len(topics)]
        n1, n2, n3 = rng.randint(2, 90), rng.randint(1, 12), rng.randint(100, 9999)
        lines.append(f"Section {i + 1}: {t.title()}. Policy {n3} states that requests about {t} must be filed within {n1} days "
                     f"and reviewed by {n2} approvers. Exceptions require a written justification, a ticket number, and sign-off "
                     f"from the owning team. Records are kept for {n1 * 7} days and audited quarterly. Repeated violations are "
                     f"escalated to the department head, who may revoke access for up to {n2 * 3} weeks.")
        lines.append("")
    lines.append("Section R: Refunds for enterprise customers. The refund window for enterprise customers is 45 days from invoice.")
    return "\n".join(lines)


def system_prompt(scenario: str, call_index: int, base: str | None = None) -> str:
    base = base if base is not None else handbook()
    if scenario == "stable":
        return base
    volatile = f"[request {call_index} at {datetime.now(timezone.utc).isoformat()} nonce {uuid.uuid4().hex[:8]}]"
    if scenario == "volatile-head":
        return volatile + "\n" + base
    if scenario == "volatile-tail":
        return base + "\n" + volatile
    raise ValueError(f"unknown scenario {scenario!r}")


# ---------------------------------------------------------------- results

@dataclass
class Call:
    scenario: str
    index: int
    cache_write: int
    cache_read: int
    uncached_input: int
    output_tokens: int
    cost_usd: float
    duration_ms: int
    error: str = ""

    @property
    def prompt_tokens(self) -> int:
        return self.cache_write + self.cache_read + self.uncached_input

    @property
    def hit_rate(self) -> float:
        return self.cache_read / self.prompt_tokens if self.prompt_tokens else 0.0


def run_call(scenario: str, index: int, model: str, base: str, timeout: float = 180.0) -> Call:
    sp = system_prompt(scenario, index, base)
    cmd = ["claude", "-p", QUESTION, "--model", model, "--effort", "low", "--no-session-persistence", "--tools", "",
           "--max-turns", "3", "--output-format", "json", "--system-prompt", sp]
    t0 = time.time()
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        data = json.loads(run.stdout)
        if data.get("is_error"):
            raise ValueError(str(data.get("result") or data.get("subtype"))[:120])
        u = data.get("usage") or {}
        return Call(scenario, index, int(u.get("cache_creation_input_tokens") or 0), int(u.get("cache_read_input_tokens") or 0),
                    int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0), float(data.get("total_cost_usd") or 0.0),
                    int(data.get("duration_ms") or (time.time() - t0) * 1000))
    except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, OSError) as e:
        return Call(scenario, index, 0, 0, 0, 0, 0.0, int((time.time() - t0) * 1000), error=f"{type(e).__name__}: {e}"[:160])


def fake_call(scenario: str, index: int, rng: random.Random, prompt_tokens: int = 6000) -> Call:
    """dry-run용. stable은 2회차부터 전부 읽기, head는 매번 쓰기, tail은 앞부분만 읽기."""
    overhead = 40 + rng.randint(0, 10)
    if scenario == "stable":
        write, read = (prompt_tokens, 0) if index == 0 else (0, prompt_tokens)
    elif scenario == "volatile-head":
        write, read = prompt_tokens, 0
    else:
        write, read = (prompt_tokens, 0) if index == 0 else (overhead, prompt_tokens - overhead)
    out = rng.randint(12, 30)
    cost = (write * 0.125 + read * 0.01 + overhead * 0.1 + out * 0.5) / 1_000_000
    return Call(scenario, index, write, read, overhead, out, round(cost, 7), 900 + rng.randint(0, 600))


def measure(scenarios: list[str], n: int, model: str, *, dry_run: bool, seed: int = 0, progress=lambda s: None) -> list[Call]:
    rng = random.Random(seed)
    base = handbook()
    calls: list[Call] = []
    for sc in scenarios:
        for i in range(n):
            c = fake_call(sc, i, rng) if dry_run else run_call(sc, i, model, base)
            calls.append(c)
            progress(f"  {sc:<14} #{i + 1}  write {c.cache_write:>6}  read {c.cache_read:>6}  uncached {c.uncached_input:>4}  "
                     f"${c.cost_usd:.5f}  {c.duration_ms / 1000:4.1f}s{('  ⚠ ' + c.error) if c.error else ''}")
            if not dry_run and i < n - 1:
                time.sleep(0.5)  # 같은 접두사 호출이 겹쳐 둘 다 '쓰기'가 되는 경쟁을 피한다
    return calls


# ---------------------------------------------------------------- report

@dataclass
class ScenarioStats:
    scenario: str
    n: int
    total_cost: float
    hit_rate_after_first: float   # 2회차 이후 평균 적중률
    writes_after_first: int       # 2회차 이후 캐시 쓰기 토큰 합 (0이면 이상적)
    median_ms: float
    errors: int


def summarize(calls: list[Call], scenarios: list[str] = SCENARIOS) -> list[ScenarioStats]:
    out = []
    for sc in scenarios:
        cs = [c for c in calls if c.scenario == sc]
        if not cs:
            continue
        later = [c for c in cs[1:] if not c.error] or [c for c in cs if not c.error]
        out.append(ScenarioStats(sc, len(cs), sum(c.cost_usd for c in cs),
                                 statistics.fmean(c.hit_rate for c in later) if later else 0.0,
                                 sum(c.cache_write for c in cs[1:]), statistics.median(c.duration_ms for c in cs),
                                 sum(1 for c in cs if c.error)))
    return out


def bar(value: float, vmax: float, width: int = 28) -> str:
    n = 0 if vmax <= 0 else round(value / vmax * width)
    return "█" * n + "░" * (width - n)


def render(calls: list[Call], stats: list[ScenarioStats], model: str) -> str:
    n = max((s.n for s in stats), default=0)
    lines = [f"🧊 cache meter — {model}, 시나리오 {len(stats)}개 × {n}회 = 호출 {len(calls)}회", ""]
    lines.append("호출별 캐시 읽기 비율 (■ 읽기, ▒ 쓰기, · 캐시 안 됨)")
    for s in stats:
        row = []
        for c in [c for c in calls if c.scenario == s.scenario]:
            if c.error or not c.prompt_tokens:
                row.append("✗")
            else:
                r = c.cache_read / c.prompt_tokens; w = c.cache_write / c.prompt_tokens
                row.append("■" if r >= 0.9 else "▒" if w >= 0.9 else "◧" if r >= 0.5 else "·")
        lines.append(f"  {s.scenario:<14} {' '.join(row)}")
    lines.append("")
    def section(title, key, fmt):
        vmax = max((key(s) for s in stats), default=0)
        lines.append(title)
        for s in stats:
            lines.append(f"  {s.scenario:<14} {bar(key(s), vmax)} {fmt(key(s))}")
        lines.append("")
    section("2회차 이후 평균 캐시 적중률", lambda s: s.hit_rate_after_first, lambda v: f"{v * 100:5.1f}%")
    section("2회차 이후 캐시 쓰기 토큰 합 (0이 이상적)", lambda s: float(s.writes_after_first), lambda v: f"{v:8.0f}")
    section("총 비용", lambda s: s.total_cost, lambda v: f"${v:.5f}")
    section("중앙값 소요 시간", lambda s: s.median_ms, lambda v: f"{v / 1000:4.1f}s")
    lines.append("누적 비용 곡선 (호출 1 → N)")
    vmax = max((sum(c.cost_usd for c in calls if c.scenario == s.scenario) for s in stats), default=0)
    for s in stats:
        acc, pts = 0.0, []
        for c in [c for c in calls if c.scenario == s.scenario]:
            acc += c.cost_usd; pts.append(acc)
        lines.append(f"  {s.scenario:<14} " + " ".join(f"{bar(p, vmax, 6)}" for p in pts) + f"  ${acc:.5f}")
    errs = [c for c in calls if c.error]
    if errs:
        lines.append("")
        lines.append(f"⚠ 실패 {len(errs)}건: " + "; ".join(f"{c.scenario}#{c.index + 1}: {c.error}" for c in errs[:5]))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- cli

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="프롬프트 캐시 적중률·비용 측정기")
    ap.add_argument("-n", type=int, default=4, help="시나리오당 호출 수 (기본 4)")
    ap.add_argument("--scenarios", default=",".join(SCENARIOS), help="쉼표 구분 (기본: stable,volatile-head,volatile-tail)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--dry-run", action="store_true", help="모델 없이 시드 고정 가짜 결과")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--from", dest="from_file", type=Path, help="저장된 results JSON을 다시 그린다")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "results")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--show-prompt-size", action="store_true", help="핸드북 길이(문자 수)만 출력")
    args = ap.parse_args(argv)
    if args.show_prompt_size:
        print(len(handbook()))
        return 0
    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    bad = [s for s in scenarios if s not in SCENARIOS]
    if bad:
        ap.error(f"모르는 시나리오: {bad} (가능: {SCENARIOS})")
    if args.n < 2:
        ap.error("-n은 2 이상이어야 2회차 적중을 볼 수 있습니다")
    if args.from_file:
        saved = json.loads(args.from_file.read_text(encoding="utf-8"))
        calls = [Call(**c) for c in saved["calls"]]
        model = saved.get("model", args.model)
    else:
        print(f"({'dry-run 가짜 결과' if args.dry_run else args.model}, 시나리오 {scenarios}, 각 {args.n}회, 시스템 프롬프트 {len(handbook()):,}자)", flush=True)
        calls = measure(scenarios, args.n, args.model, dry_run=args.dry_run, seed=args.seed, progress=lambda s: print(s, flush=True))
        model = args.model
        if not args.no_save:
            args.out.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            path = args.out / f"{stamp}-{'dry' if args.dry_run else model}.json"
            path.write_text(json.dumps({"model": model, "calls": [asdict(c) for c in calls]}, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"📝 결과 저장: {path}")
    print()
    print(render(calls, summarize(calls, scenarios), model), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())

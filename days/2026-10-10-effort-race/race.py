#!/usr/bin/env python3
"""race.py — 같은 문제를 effort low/medium/high/xhigh/max 다섯 레인에 동시에 던져
시간·토큰·비용·정답률을 ASCII 막대그래프로 비교한다.

Claude Code 2.1.292에서 Agent 도구에 `effort`가 생겼고 `claude -p --effort <level>`로도 같은 손잡이를 돌릴 수 있다.
각 (레벨 × 문제)가 `claude -p` 호출 하나다. --dry-run이면 시드 고정 가짜 결과로 그래프만 그린다.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

LEVELS = ["low", "medium", "high", "xhigh", "max"]
DEFAULT_MODEL = "claude-haiku-5-5"

# 짧지만 '급하게 답하면 틀리는' 문제들. 정답은 정규화(소문자·공백·구두점 제거) 후 비교한다.
TASKS: list[tuple[str, str, str]] = [
    ("bat-ball", "A bat and a ball cost $1.10 in total. The bat costs $1.00 more than the ball. How many cents does the ball cost? Answer with a number only.", "5"),
    ("strawberry", "How many times does the letter r appear in the word strawberry? Answer with a number only.", "3"),
    ("sequence", "What is the next number in the sequence 2, 6, 12, 20, 30? Answer with a number only.", "42"),
    ("arith", "Compute (17 * 23) - (4 ** 3). Answer with a number only.", "327"),
    ("weekday", "2026-10-10 is a Saturday. What day of the week is 2026-11-03? Answer with the weekday name only.", "tuesday"),
    ("lily", "A patch of lily pads doubles in size every day. If it takes 48 days to cover the whole lake, how many days does it take to cover half? Answer with a number only.", "47"),
    ("reverse", "Reverse the string 'anthropic'. Answer with the reversed string only.", "ciporhtna"),
    ("sisters", "Sally has 3 brothers. Each brother has 2 sisters. How many sisters does Sally have? Answer with a number only.", "1"),
]


@dataclass
class Result:
    level: str
    task: str
    answer: str
    expected: str
    correct: bool
    duration_ms: int
    output_tokens: int
    thinking_tokens: int
    cost_usd: float
    error: str = ""


def normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def grade(answer: str, expected: str) -> bool:
    """정답이 숫자면 답에서 첫 숫자만 꺼내 비교하고("5 cents" → 5), 아니면 정규화 문자열을 비교한다."""
    e = normalize(expected)
    if e.isdigit():
        m = re.search(r"-?\d+(?:\.\d+)?", str(answer).replace(",", ""))
        return m is not None and float(m.group()) == float(e)
    return normalize(answer) == e


# ---------------------------------------------------------------- runners

def run_one(level: str, task_id: str, question: str, expected: str, model: str, timeout: float = 300.0) -> Result:
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"], "additionalProperties": False}
    cmd = ["claude", "-p", question, "--model", model, "--effort", level, "--no-session-persistence", "--tools", "",
           "--max-turns", "3", "--output-format", "json", "--system-prompt", "Solve the problem and give only the final answer.",
           "--json-schema", json.dumps(schema)]
    t0 = time.time()
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        data = json.loads(run.stdout)
        if data.get("is_error"):
            raise ValueError(str(data.get("result") or data.get("subtype"))[:120])
        answer = str((data.get("structured_output") or {}).get("answer", ""))
        usage = data.get("usage") or {}
        return Result(level, task_id, answer, expected, grade(answer, expected), int(data.get("duration_ms") or (time.time() - t0) * 1000),
                      int(usage.get("output_tokens") or 0), int(((usage.get("output_tokens_details") or {}).get("thinking_tokens")) or 0),
                      float(data.get("total_cost_usd") or 0.0))
    except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, OSError) as e:
        return Result(level, task_id, "", expected, False, int((time.time() - t0) * 1000), 0, 0, 0.0, error=f"{type(e).__name__}: {e}"[:160])


def fake_one(level: str, task_id: str, question: str, expected: str, rng: random.Random) -> Result:
    """dry-run용 가짜 결과. 레벨이 높을수록 느리고 비싸고 정답률이 오르는 모양을 흉내 낸다."""
    i = LEVELS.index(level)
    p_correct = [0.5, 0.7, 0.85, 0.92, 0.95][i]
    ok = rng.random() < p_correct
    thinking = int(rng.gauss(60 * (i + 1) ** 1.6, 20 * (i + 1)))
    out = thinking + rng.randint(3, 12)
    ms = int(800 + out * 9 + rng.gauss(0, 150))
    return Result(level, task_id, expected if ok else "?", expected, ok, max(300, ms), max(1, out), max(0, thinking), round(out * 5e-7 + 0.0012, 6))


def race(model: str, levels: list[str], tasks: list[tuple[str, str, str]], *, dry_run: bool, seed: int, workers: int = 5,
         progress=lambda s: None) -> list[Result]:
    jobs = [(lv, tid, q, exp) for lv in levels for tid, q, exp in tasks]
    if dry_run:
        rng = random.Random(seed)
        return [fake_one(lv, tid, q, exp, rng) for lv, tid, q, exp in jobs]
    out: list[Result] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(lambda j: run_one(j[0], j[1], j[2], j[3], model), jobs):
            out.append(r)
            progress(f"  {r.level:>6} · {r.task:<10} {'✅' if r.correct else '❌'} {r.duration_ms / 1000:5.1f}s  think {r.thinking_tokens:>5}  ${r.cost_usd:.4f}{('  ⚠ ' + r.error) if r.error else ''}")
    return out


# ---------------------------------------------------------------- report

@dataclass
class LevelStats:
    level: str
    n: int
    correct: int
    median_ms: float
    mean_tokens: float
    mean_thinking: float
    cost: float
    errors: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.n if self.n else 0.0


def summarize(results: list[Result], levels: list[str] = LEVELS) -> list[LevelStats]:
    out = []
    for lv in levels:
        rs = [r for r in results if r.level == lv]
        if not rs:
            continue
        out.append(LevelStats(lv, len(rs), sum(r.correct for r in rs), statistics.median(r.duration_ms for r in rs),
                              statistics.fmean(r.output_tokens for r in rs), statistics.fmean(r.thinking_tokens for r in rs),
                              sum(r.cost_usd for r in rs), sum(1 for r in rs if r.error)))
    return out


def bar(value: float, vmax: float, width: int = 28) -> str:
    n = 0 if vmax <= 0 else round(value / vmax * width)
    return "█" * n + "░" * (width - n)


def render(stats: list[LevelStats], results: list[Result], model: str, tasks: list[tuple[str, str, str]] | None = None) -> str:
    tasks = tasks or TASKS
    lines = [f"🏁 effort race — {model}, 문제 {len({r.task for r in results})}개 × 레벨 {len(stats)}개 = 호출 {len(results)}회", ""]
    def section(title: str, key, fmt):
        vmax = max((key(s) for s in stats), default=0)
        lines.append(title)
        for s in stats:
            lines.append(f"  {s.level:>6} {bar(key(s), vmax)} {fmt(key(s))}")
        lines.append("")
    section("정답률", lambda s: s.accuracy, lambda v: f"{v * 100:5.1f}%")
    section("중앙값 소요 시간", lambda s: s.median_ms, lambda v: f"{v / 1000:5.1f}s")
    section("평균 생각(thinking) 토큰", lambda s: s.mean_thinking, lambda v: f"{v:7.0f}")
    section("평균 출력 토큰 (생각 포함)", lambda s: s.mean_tokens, lambda v: f"{v:7.0f}")
    section("총 비용", lambda s: s.cost, lambda v: f"${v:.4f}")
    lines.append("문제별 정답 (행: 문제, 열: " + " ".join(f"{lv:>6}" for lv in [s.level for s in stats]) + ")")
    by = {(r.level, r.task): r for r in results}
    for tid, _, _ in tasks:
        if not any(r.task == tid for r in results):
            continue
        cells = "".join(f"{('✅' if by[(s.level, tid)].correct else '❌') if (s.level, tid) in by else '  ':>6} " for s in stats)
        lines.append(f"  {tid:<11} {cells}")
    errs = [r for r in results if r.error]
    if errs:
        lines.append("")
        lines.append(f"⚠ 실패 {len(errs)}건: " + "; ".join(f"{r.level}/{r.task}: {r.error}" for r in errs[:5]))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="effort 레벨별 시간·토큰·비용·정답률 레이스")
    ap.add_argument("--dry-run", action="store_true", help="모델 없이 시드 고정 가짜 결과")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--levels", default=",".join(LEVELS), help="쉼표 구분 (기본: low,medium,high,xhigh,max)")
    ap.add_argument("--tasks", type=int, default=len(TASKS), help="앞에서부터 N개 문제만")
    ap.add_argument("--workers", type=int, default=5, help="동시 호출 수")
    ap.add_argument("--from", dest="from_file", type=Path, help="저장된 results JSON을 다시 그린다")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "results")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args(argv)
    levels = [l.strip() for l in args.levels.split(",") if l.strip()]
    bad = [l for l in levels if l not in LEVELS]
    if bad:
        ap.error(f"모르는 레벨: {bad} (가능: {LEVELS})")
    tasks = TASKS[: args.tasks]
    if args.from_file:
        saved = json.loads(args.from_file.read_text(encoding="utf-8"))
        results = [Result(**r) for r in saved["results"]]
        model = saved.get("model", args.model)
    else:
        print(f"({'dry-run 가짜 결과' if args.dry_run else args.model}, 레벨 {levels}, 문제 {len(tasks)}개, 동시 {args.workers})", flush=True)
        results = race(args.model, levels, tasks, dry_run=args.dry_run, seed=args.seed, workers=args.workers, progress=lambda s: print(s, flush=True))
        model = args.model
        if not args.no_save:
            args.out.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            path = args.out / f"{stamp}-{'dry' if args.dry_run else model}.json"
            path.write_text(json.dumps({"model": model, "levels": levels, "results": [asdict(r) for r in results]}, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"📝 결과 저장: {path}")
    print()
    print(render(summarize(results, levels), results, model, tasks), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())

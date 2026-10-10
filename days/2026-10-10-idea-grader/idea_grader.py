#!/usr/bin/env python3
"""idea-grader — news/*.md의 "현실 적용 아이디어"를 RULES 1절 기준으로 채점하는 작은 eval.

규칙 채점(결정적, 키 불필요)과 모델 판정(--judge, Haiku 5.5, 선택)을 분리한다.
두 파일을 --compare로 비교하면 루틴 프롬프트를 고쳤을 때 점수가 올랐는지(힐클라이밍) 본다.

  python3 idea_grader.py ../../news/2026-10-10.md
  python3 idea_grader.py ../../news/2026-10-october-all.md --worst 8
  python3 idea_grader.py A.md --compare B.md
  python3 idea_grader.py news.md --judge --items 1,2     # 실제 Haiku 판정 (항목당 1호출)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean

# ---------------------------------------------------------------- 파싱

ITEM_RE = re.compile(r"^## (\d+)\. (.+?)\s*$")
IDEAS_HEAD_RE = re.compile(r"^- 현실 적용")
IDEA_LINE_RE = re.compile(r"^  - (.+?)\s*$")


@dataclass
class Item:
    n: int
    title: str
    ideas: list[str] = field(default_factory=list)


def parse_news(md: str) -> list[Item]:
    """`## N. 제목` 아래 `- 현실 적용:` 블록의 `  - ` 줄을 아이디어로 모은다. 블록이 없는 항목은 ideas=[]."""
    items: list[Item] = []
    cur: Item | None = None
    in_ideas = False
    for line in md.splitlines():
        m = ITEM_RE.match(line)
        if m:
            cur = Item(int(m.group(1)), m.group(2))
            items.append(cur)
            in_ideas = False
            continue
        if cur is None:
            continue
        if IDEAS_HEAD_RE.match(line):
            in_ideas = True
            continue
        if in_ideas:
            m2 = IDEA_LINE_RE.match(line)
            if m2:
                cur.ideas.append(m2.group(1))
            elif line.strip() == "" or not line.startswith("  "):
                in_ideas = False
    return items


# ---------------------------------------------------------------- 규칙

ARROW = "→"
VAGUE = ["활용 가능", "활용할 수 있", "도움이 될 것", "도움이 된다", "도움이 될", "유용하", "유용할", "효율적으로", "효과적으로", "기대된다", "고려해 볼", "검토해 볼"]
MIN_IDEAS = 5
MIN_LEN, MAX_LEN = 20, 220

CONTEXTS: dict[str, list[str]] = {
    "repo": ["이 저장소", "오늘의", "daily lab", "루틴", "e2e", "news 파일"],
    "team": ["팀", "사내", "회사", "관리자", "운영", "조직", "엔터프라이즈", "Enterprise", "CI", "배포", "온보딩", "리더", "플랫폼"],
    "product": ["서비스", "제품", "앱", "봇", "고객", "사용자", "파이프라인", "라우터", "게이트웨이", "커넥터", "SaaS", "스타트업"],
    "personal": ["개인", "혼자", "사이드", "취미", "학습", "개발자 →", "외국어 사용자", "학생", "교육"],
}


def contexts_of(idea: str) -> set[str]:
    where = idea.split(ARROW)[0]
    hit = {k for k, words in CONTEXTS.items() if any(w in where for w in words)}
    return hit or {"other"}


def bigrams(s: str) -> set[str]:
    t = re.sub(r"\s+", "", s)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def similarity(a: str, b: str) -> float:
    """첫 두 구간(어디에 → 무엇을)의 문자 바이그램 Jaccard. 같은 아이디어의 변주를 잡는다."""
    ka, kb = ARROW.join(a.split(ARROW)[:2]), ARROW.join(b.split(ARROW)[:2])
    A, B = bigrams(ka), bigrams(kb)
    return len(A & B) / len(A | B) if A and B else 0.0


DUP_THRESHOLD = 0.55


@dataclass
class LineCheck:
    idea: str
    arrows: int
    vague: list[str]
    length_ok: bool
    contexts: set[str]

    @property
    def shape_ok(self) -> bool:
        return self.arrows >= 2

    @property
    def problems(self) -> list[str]:
        p = []
        if not self.shape_ok:
            p.append(f"화살표 {self.arrows}개 (어디에 → 무엇을 → 왜 이득, 2개 필요)")
        if self.vague:
            p.append("막연한 말: " + ", ".join(self.vague))
        if not self.length_ok:
            p.append(f"길이 {len(self.idea)}자 ({MIN_LEN}~{MAX_LEN})")
        return p


def vague_in(idea: str) -> list[str]:
    """막연한 표현 목록 중 들어 있는 것. '도움이 될'처럼 더 긴 매치('도움이 될 것')에 포함되는 것은 뺀다."""
    hits = [v for v in VAGUE if v in idea]
    return [v for v in hits if not any(v != w and v in w for w in hits)]


def check_line(idea: str) -> LineCheck:
    return LineCheck(idea, idea.count(ARROW), vague_in(idea), MIN_LEN <= len(idea) <= MAX_LEN, contexts_of(idea))


@dataclass
class ItemScore:
    item: Item
    lines: list[LineCheck]
    dup_pairs: list[tuple[int, int, float]]
    judge: dict | None = None

    @property
    def count_ok(self) -> bool:
        return len(self.lines) >= MIN_IDEAS

    @property
    def contexts(self) -> set[str]:
        return set().union(*(l.contexts for l in self.lines)) if self.lines else set()

    @property
    def effective(self) -> int:
        """중복 쌍을 하나로 친 유효 아이디어 수."""
        dropped = {b for _, b, _ in self.dup_pairs}
        return len(self.lines) - len(dropped)

    @property
    def rule_score(self) -> int:
        """0~100. 개수 30, 형식 30, 막연한 말 없음 20, 맥락 다양성 10, 중복 없음 10."""
        if not self.lines:
            return 0
        n = len(self.lines)
        s = 30 * min(1.0, self.effective / MIN_IDEAS)
        s += 30 * sum(l.shape_ok and l.length_ok for l in self.lines) / n
        s += 20 * sum(not l.vague for l in self.lines) / n
        s += 10 * min(1.0, len(self.contexts - {"other"}) / 3)
        s += 10 * (1.0 if not self.dup_pairs else max(0.0, 1 - len(self.dup_pairs) / n))
        return round(s)

    @property
    def score(self) -> int:
        """judge가 있으면 규칙 70 : 판정 30."""
        if self.judge is None:
            return self.rule_score
        return round(self.rule_score * 0.7 + self.judge["score"] * 0.3)


def grade_item(item: Item) -> ItemScore:
    lines = [check_line(i) for i in item.ideas]
    dups = []
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            sim = similarity(lines[i].idea, lines[j].idea)
            if sim >= DUP_THRESHOLD:
                dups.append((i, j, round(sim, 2)))
    return ItemScore(item, lines, dups)


# ---------------------------------------------------------------- 모델 판정 (선택)

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "ideas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "concrete": {"type": "integer", "minimum": 0, "maximum": 2},
                    "benefit": {"type": "integer", "minimum": 0, "maximum": 2},
                    "note": {"type": "string"},
                },
                "required": ["index", "concrete", "benefit", "note"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["ideas"],
    "additionalProperties": False,
}

JUDGE_SYSTEM = (
    "You grade 'real-world application ideas' written for a Claude/Anthropic news item. Each idea must name a concrete place "
    "(team, product, workflow), a concrete action someone could start today, and a specific benefit. Score each idea: "
    "concrete 0-2 (0 = vague or generic, 2 = a specific scene with a named tool/setting/command), benefit 0-2 (0 = none or "
    "hand-wavy, 2 = a specific measurable or observable gain). Be strict: 'useful', 'helps', 'improves efficiency' alone is 0. "
    "Write note in Korean, under 20 chars. Answer only through the JSON schema."
)


def judge_prompt(item: Item) -> str:
    body = "\n".join(f"{i + 1}. {idea}" for i, idea in enumerate(item.ideas))
    return f"News item: {item.title}\n\nIdeas:\n{body}"


def parse_judge(data: dict, n_ideas: int) -> dict:
    """structured_output → {score 0~100, per: [(concrete, benefit, note)], cost}."""
    rows = {int(r["index"]): r for r in (data.get("ideas") or []) if isinstance(r, dict) and "index" in r}
    per = []
    for i in range(1, n_ideas + 1):
        r = rows.get(i, {})
        per.append((int(r.get("concrete", 0)), int(r.get("benefit", 0)), str(r.get("note", ""))[:30]))
    total = sum(c + b for c, b, _ in per)
    return {"score": round(100 * total / (4 * n_ideas)) if n_ideas else 0, "per": per}


def run_judge(item: Item, model: str = "claude-haiku-5-5", timeout: float = 180) -> dict:
    cmd = ["claude", "-p", judge_prompt(item), "--model", model, "--effort", "low", "--no-session-persistence", "--tools", "",
           "--max-turns", "3", "--output-format", "json", "--system-prompt", JUDGE_SYSTEM, "--json-schema", json.dumps(JUDGE_SCHEMA)]
    t0 = time.time()
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        data = json.loads(run.stdout)
        if data.get("is_error"):
            raise ValueError(str(data.get("result") or data.get("subtype"))[:120])
        out = parse_judge(data.get("structured_output") or {}, len(item.ideas))
        out["cost"] = float(data.get("total_cost_usd") or 0.0)
        out["ms"] = int(data.get("duration_ms") or (time.time() - t0) * 1000)
        return out
    except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, OSError) as e:
        return {"score": 0, "per": [], "cost": 0.0, "ms": int((time.time() - t0) * 1000), "error": f"{type(e).__name__}: {e}"[:160]}


# ---------------------------------------------------------------- 출력

def short(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def render(scores: list[ItemScore], label: str, worst: int = 5) -> str:
    out = [f"## 현실 적용 채점 — {label}", ""]
    head = "| # | 항목 | 개수 | 형식 | 막연 | 맥락 | 중복 | 규칙" + (" | 판정 | 합계" if any(s.judge for s in scores) else "") + " |"
    out += [head, "|" + "|".join("---" for _ in range(head.count("|") - 1)) + "|"]
    for s in scores:
        n = len(s.lines)
        shape = f"{sum(l.shape_ok and l.length_ok for l in s.lines)}/{n}" if n else "-"
        vague = str(sum(bool(l.vague) for l in s.lines))
        ctx = ",".join(sorted(s.contexts - {"other"})) or "-"
        dup = str(len(s.dup_pairs))
        row = f"| {s.item.n} | {short(s.item.title, 28)} | {n}{'' if s.count_ok else ' ⚠'} | {shape} | {vague} | {ctx} | {dup} | {s.rule_score}"
        if any(x.judge for x in scores):
            j = s.judge
            row += f" | {j['score'] if j and 'error' not in j else '-'} | {s.score}"
        out.append(row + " |")
    graded = [s for s in scores if s.lines]
    out += ["", f"항목 {len(scores)}개, 아이디어 {sum(len(s.lines) for s in scores)}줄, 평균 {mean(s.score for s in graded) if graded else 0:.1f}점, "
            f"5개 미만 {sum(not s.count_ok for s in scores)}개, 형식 위반 {sum(not (l.shape_ok and l.length_ok) for s in scores for l in s.lines)}줄, "
            f"막연한 말 {sum(bool(l.vague) for s in scores for l in s.lines)}줄, 중복 쌍 {sum(len(s.dup_pairs) for s in scores)}개"]
    flagged = [(s.item.n, short(l.idea, 90), "; ".join(l.problems)) for s in scores for l in s.lines if l.problems]
    flagged += [(s.item.n, f"{short(s.lines[i].idea, 40)} ≈ {short(s.lines[j].idea, 40)}", f"같은 아이디어의 변주 (유사도 {sim})")
                for s in scores for i, j, sim in s.dup_pairs]
    if flagged:
        out += ["", f"### 고칠 줄 (최대 {worst}개, 전체 {len(flagged)}개)"]
        for n, text, why in flagged[:worst]:
            out.append(f"- {n}번: {text}\n  - {why}")
    judged = [s for s in scores if s.judge and "error" not in s.judge]
    if judged:
        out += ["", f"### 모델 판정 (Haiku, 항목 {len(judged)}개, ${sum(s.judge['cost'] for s in judged):.4f})"]
        for s in judged:
            low = [(i + 1, c, b, note) for i, (c, b, note) in enumerate(s.judge["per"]) if c + b <= 1]
            out.append(f"- {s.item.n}번 {s.judge['score']}점" + (": " + "; ".join(f"{i}) 구체 {c} 이득 {b} {note}" for i, c, b, note in low) if low else ""))
    errs = [s for s in scores if s.judge and "error" in s.judge]
    for s in errs:
        out.append(f"- ⚠ {s.item.n}번 판정 실패: {s.judge['error']}")
    return "\n".join(out)


def render_compare(a: list[ItemScore], b: list[ItemScore], la: str, lb: str) -> str:
    """같은 번호의 항목끼리 점수 차. 힐클라이밍의 '둘 다 올랐나'를 보는 표."""
    am, bm = {s.item.n: s for s in a}, {s.item.n: s for s in b}
    out = [f"## 비교 — {la} → {lb}", "", "| # | 항목 | 전 | 후 | Δ |", "|---|---|---|---|---|"]
    ups = downs = 0
    for n in sorted(am.keys() & bm.keys()):
        d = bm[n].score - am[n].score
        ups += d > 0
        downs += d < 0
        out.append(f"| {n} | {short(bm[n].item.title, 28)} | {am[n].score} | {bm[n].score} | {d:+d} |")
    ma = mean(s.score for s in a) if a else 0
    mb = mean(s.score for s in b) if b else 0
    out += ["", f"평균 {ma:.1f} → {mb:.1f} ({mb - ma:+.1f}), 오른 항목 {ups}, 내린 항목 {downs}, "
            f"{'✅ 채택' if mb > ma and downs == 0 else '⚠ 되돌리기 검토 (내린 항목이 있거나 평균이 안 올랐다)'}"]
    return "\n".join(out)


# ---------------------------------------------------------------- CLI

def grade_file(path: Path, judge_items: set[int] | None = None, model: str = "claude-haiku-5-5", progress=lambda s: None) -> list[ItemScore]:
    scores = [grade_item(it) for it in parse_news(path.read_text(encoding="utf-8"))]
    if judge_items is not None:
        for s in scores:
            if s.lines and (not judge_items or s.item.n in judge_items):
                s.judge = run_judge(s.item, model)
                progress(f"  judge {s.item.n:>2} → {s.judge.get('score', '?')}점 {s.judge.get('ms', 0) / 1000:.1f}s ${s.judge.get('cost', 0):.4f}" + (f"  ⚠ {s.judge['error']}" if "error" in s.judge else ""))
    return scores


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("news", type=Path, help="news/YYYY-MM-DD.md")
    ap.add_argument("--compare", type=Path, help="두 번째 파일. 같은 번호 항목끼리 점수 차를 본다")
    ap.add_argument("--judge", action="store_true", help="Haiku 5.5로 구체성·이득을 판정 (항목당 claude -p 1회)")
    ap.add_argument("--items", default="", help="--judge 대상 항목 번호 (쉼표). 기본 전부")
    ap.add_argument("--model", default="claude-haiku-5-5")
    ap.add_argument("--worst", type=int, default=5, help="고칠 줄 몇 개까지")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.news.exists():
        print(f"파일 없음: {a.news}", file=sys.stderr)
        return 2
    judge_items = ({int(x) for x in a.items.split(",") if x} if a.judge else None)
    scores = grade_file(a.news, judge_items, a.model, progress=lambda s: print(s, file=sys.stderr))
    if a.compare:
        other = grade_file(a.compare, judge_items, a.model, progress=lambda s: print(s, file=sys.stderr))
        print(render_compare(scores, other, a.news.name, a.compare.name))
        return 0
    if a.json:
        print(json.dumps([{"n": s.item.n, "title": s.item.title, "ideas": len(s.lines), "rule": s.rule_score, "score": s.score,
                           "problems": [l.problems for l in s.lines], "dups": s.dup_pairs, "judge": s.judge} for s in scores], ensure_ascii=False, indent=2))
        return 0
    print(render(scores, a.news.name, worst=a.worst))
    return 0 if all(s.count_ok for s in scores if s.lines) else 1


if __name__ == "__main__":
    sys.exit(main())

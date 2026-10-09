#!/usr/bin/env python3
"""model-caps — Models API 응답을 모델 능력표(Markdown)로, 그리고 스냅샷 간 diff로.

GET /v1/models 가 2026-10월에 얻은 필드(line, lifecycle, capabilities.thinking.types.disabled,
capabilities.server_tools, effort 레벨…)를 표로 만든다. 키가 없으면 sample-models.json으로 dry-run.

  python3 model_caps.py                       # sample-models.json → Markdown 표 (dry-run)
  python3 model_caps.py --live --save snapshots/2026-10-10.json
  python3 model_caps.py --from snapshots/2026-10-10.json --diff snapshots/2026-10-03.json
  python3 model_caps.py --latest haiku        # 해당 line의 최신 active 모델 id 한 줄
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, fields
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable

HERE = Path(__file__).resolve().parent
SAMPLE = HERE / "sample-models.json"
API_BASE = "https://api.anthropic.com"
API_VERSION = "2023-06-01"
LIFECYCLES = ("active", "deprecated", "retired")
EFFORTS = ("low", "medium", "high", "xhigh", "max")

# ---------------------------------------------------------------- 데이터

@dataclass(frozen=True)
class Row:
    """표 한 줄. 불리언 능력은 True/False, 응답에 없으면 None(표에서 ?)."""
    id: str
    display_name: str
    line: str | None
    lifecycle: str
    created: str            # YYYY-MM-DD
    max_input: int | None
    max_output: int | None
    think_adaptive: bool | None
    think_enabled: bool | None
    think_disabled: bool | None
    efforts: str            # "low…max" 지원 레벨을 압축한 문자열, "?" 모름
    web_search: bool | None
    code_execution: bool | None
    structured_outputs: bool | None
    image_input: bool | None
    pdf_input: bool | None
    batch: bool | None
    deprecated_at: str | None
    retires_at: str | None


def _sup(obj: Any) -> bool | None:
    """CapabilitySupport({"supported": bool}) → bool, 없거나 모양이 다르면 None."""
    if isinstance(obj, dict) and isinstance(obj.get("supported"), bool):
        return obj["supported"]
    return None


def _day(s: Any) -> str | None:
    return s[:10] if isinstance(s, str) and len(s) >= 10 else None


def efforts_of(cap: Any) -> str:
    """effort 능력 → 'low-max' 같은 범위 문자열. 중간이 빠지면 쉼표로 나열. 미지원은 '-', 모르면 '?'."""
    if not isinstance(cap, dict):
        return "?"
    if cap.get("supported") is False:
        return "-"
    on = [e for e in EFFORTS if _sup(cap.get(e))]
    if not on:
        return "?" if cap.get("supported") is None else "-"
    idx = [EFFORTS.index(e) for e in on]
    if idx == list(range(idx[0], idx[-1] + 1)):
        return on[0] if len(on) == 1 else f"{on[0]}-{on[-1]}"
    return ",".join(on)


def _dict(x: Any) -> dict[str, Any]:
    """응답의 중첩 객체. dict가 아니면(null, 문자열…) 빈 dict로 보고 모든 능력을 ?로 둔다."""
    return x if isinstance(x, dict) else {}


def row_of(m: dict[str, Any]) -> Row:
    cap = _dict(m.get("capabilities"))
    think = _dict(cap.get("thinking"))
    types = _dict(think.get("types"))
    tools = _dict(cap.get("server_tools"))
    return Row(
        id=str(m.get("id", "?")),
        display_name=str(m.get("display_name") or m.get("id", "?")),
        line=m.get("line"),
        lifecycle=str(m.get("lifecycle") or "active"),
        created=_day(m.get("created_at")) or "?",
        max_input=m.get("max_input_tokens"),
        max_output=m.get("max_tokens"),
        think_adaptive=_sup(types.get("adaptive")),
        think_enabled=_sup(types.get("enabled")),
        think_disabled=_sup(types.get("disabled")),
        efforts=efforts_of(cap.get("effort")),
        web_search=_sup(tools.get("web_search")),
        code_execution=_sup(tools.get("code_execution")),
        structured_outputs=_sup(cap.get("structured_outputs")),
        image_input=_sup(cap.get("image_input")),
        pdf_input=_sup(cap.get("pdf_input")),
        batch=_sup(cap.get("batch")),
        deprecated_at=_day(m.get("deprecated_at")),
        retires_at=_day(m.get("retires_at")),
    )


def models_of(payload: Any) -> list[dict[str, Any]]:
    """응답 JSON({"data": [...]}) 또는 모델 리스트 → 모델 dict 리스트."""
    if isinstance(payload, dict):
        payload = payload.get("data", [])
    if not isinstance(payload, list):
        raise ValueError("models payload must be a list or {data: [...]}")
    return [m for m in payload if isinstance(m, dict) and m.get("id")]


def load_models(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return models_of(json.load(f))


# ---------------------------------------------------------------- API

Fetcher = Callable[[str], dict[str, Any]]


def http_get(url: str, api_key: str, timeout: float = 30) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={
        "x-api-key": api_key, "anthropic-version": API_VERSION, "accept": "application/json",
        "user-agent": "claude-daily-lab model-caps/0.1",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — 고정 호스트
        return json.load(resp)


def fetch_models(fetch: Fetcher, base: str = API_BASE, lifecycles: Iterable[str] = (), limit: int = 100,
                 max_pages: int = 20) -> list[dict[str, Any]]:
    """after_id 커서로 끝까지 받는다. lifecycles를 주면 retired도 요청할 수 있다."""
    q = [f"limit={limit}"] + [f"lifecycle[]={lc}" for lc in lifecycles]
    out: list[dict[str, Any]] = []
    after: str | None = None
    for _ in range(max_pages):
        url = f"{base}/v1/models?" + "&".join(q + ([f"after_id={after}"] if after else []))
        page = fetch(url)
        out.extend(models_of(page))
        if not page.get("has_more") or not page.get("last_id"):
            break
        after = page["last_id"]
    return out


# ---------------------------------------------------------------- 표

def fmt_tokens(n: int | None) -> str:
    if n is None:
        return "?"
    if n >= 1_000_000 and n % 100_000 == 0:
        return f"{n / 1_000_000:g}M"
    if n >= 1_000:
        return f"{n // 1_000}K"
    return str(n)


def mark(b: bool | None) -> str:
    return "?" if b is None else ("✓" if b else "✗")


COLUMNS: list[tuple[str, Callable[[Row], str]]] = [
    ("모델", lambda r: f"`{r.id}`"),
    ("line", lambda r: r.line or "-"),
    ("상태", lambda r: r.lifecycle + (f" (~{r.retires_at})" if r.retires_at else "")),
    ("출시", lambda r: r.created),
    ("입력", lambda r: fmt_tokens(r.max_input)),
    ("출력", lambda r: fmt_tokens(r.max_output)),
    ("thinking a/e/d", lambda r: f"{mark(r.think_adaptive)}{mark(r.think_enabled)}{mark(r.think_disabled)}"),
    ("effort", lambda r: r.efforts),
    ("web", lambda r: mark(r.web_search)),
    ("code", lambda r: mark(r.code_execution)),
    ("JSON", lambda r: mark(r.structured_outputs)),
    ("img", lambda r: mark(r.image_input)),
    ("pdf", lambda r: mark(r.pdf_input)),
    ("batch", lambda r: mark(r.batch)),
]


def sort_rows(rows: Iterable[Row]) -> list[Row]:
    """active → deprecated → retired 순, 같은 상태 안에서는 최신 출시가 위."""
    order = {lc: i for i, lc in enumerate(LIFECYCLES)}
    return sorted(rows, key=lambda r: (order.get(r.lifecycle, 9), -_ord(r.created), r.id))


def _ord(day: str) -> int:
    try:
        return int(day.replace("-", ""))
    except ValueError:
        return 0


def render_table(rows: Iterable[Row], title: str | None = None) -> str:
    rs = sort_rows(rows)
    head = "| " + " | ".join(c for c, _ in COLUMNS) + " |"
    sep = "|" + "|".join("---" for _ in COLUMNS) + "|"
    body = ["| " + " | ".join(f(r) for _, f in COLUMNS) + " |" for r in rs]
    lines = ([f"### {title}", ""] if title else []) + [head, sep] + body
    lines += ["", f"{len(rs)} models · thinking a/e/d = adaptive/enabled/disabled 허용 · ✓ 지원 ✗ 미지원 ? 응답에 없음"]
    return "\n".join(lines)


def latest_of_line(rows: Iterable[Row], line: str) -> Row | None:
    """해당 line의 active 모델 중 가장 최근 출시. 라우터가 'haiku 최신'을 코드로 고를 때."""
    cands = [r for r in rows if r.line == line and r.lifecycle == "active"]
    return max(cands, key=lambda r: (_ord(r.created), r.id), default=None)


# ---------------------------------------------------------------- diff

IGNORE_IN_DIFF = {"display_name"}


def diff_rows(old: Iterable[Row], new: Iterable[Row]) -> dict[str, Any]:
    o = {r.id: r for r in old}
    n = {r.id: r for r in new}
    added = sorted(n.keys() - o.keys())
    removed = sorted(o.keys() - n.keys())
    changed: dict[str, list[tuple[str, Any, Any]]] = {}
    for mid in sorted(o.keys() & n.keys()):
        a, b = asdict(o[mid]), asdict(n[mid])
        delta = [(k, a[k], b[k]) for k in (f.name for f in fields(Row)) if k not in IGNORE_IN_DIFF and a[k] != b[k]]
        if delta:
            changed[mid] = delta
    return {"added": added, "removed": removed, "changed": changed}


def render_diff(d: dict[str, Any], old_label: str, new_label: str) -> str:
    out = [f"### 변경: {old_label} → {new_label}", ""]
    if not (d["added"] or d["removed"] or d["changed"]):
        return "\n".join(out + ["변경 없음"])
    for mid in d["added"]:
        out.append(f"- ➕ 추가 `{mid}`")
    for mid in d["removed"]:
        out.append(f"- ➖ 사라짐 `{mid}` (목록에서 빠짐. retired는 lifecycle=retired를 요청해야 보인다)")
    for mid, delta in d["changed"].items():
        out.append(f"- 🔁 `{mid}`: " + "; ".join(f"{k} {_v(a)} → {_v(b)}" for k, a, b in delta))
    return "\n".join(out)


def _v(x: Any) -> str:
    return "?" if x is None else ("✓" if x is True else "✗" if x is False else str(x))


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--live", action="store_true", help="ANTHROPIC_API_KEY로 실제 GET /v1/models")
    src.add_argument("--from", dest="from_path", type=Path, help="저장된 응답 JSON에서 읽기 (기본: sample-models.json dry-run)")
    ap.add_argument("--lifecycle", default="", help="쉼표 구분: active,deprecated,retired (live 요청 필터)")
    ap.add_argument("--only", default="", help="표에 넣을 lifecycle만 (쉼표 구분). 기본 전부")
    ap.add_argument("--line", default="", help="이 line만 (haiku/sonnet/opus/fable/mythos)")
    ap.add_argument("--diff", type=Path, help="이전 스냅샷 JSON과 비교해 변경만 출력")
    ap.add_argument("--save", type=Path, help="받은 원본 응답을 이 경로에 저장 (예: snapshots/%s.json)" % date.today())
    ap.add_argument("--latest", metavar="LINE", help="해당 line의 최신 active 모델 id만 출력")
    ap.add_argument("--json", action="store_true", help="표 대신 Row JSON 배열 출력")
    ap.add_argument("--base-url", default=os.environ.get("ANTHROPIC_BASE_URL", API_BASE))
    a = ap.parse_args(argv)

    if a.live:
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            print("ANTHROPIC_API_KEY 가 없다. --from <json> 이나 dry-run(인자 없음)을 쓴다.", file=sys.stderr)
            return 2
        lcs = [s for s in a.lifecycle.split(",") if s]
        bad = [s for s in lcs if s not in LIFECYCLES]
        if bad:
            print(f"--lifecycle 값이 이상하다: {bad}", file=sys.stderr)
            return 2
        try:
            models = fetch_models(lambda u: http_get(u, key), base=a.base_url, lifecycles=lcs)
        except urllib.error.HTTPError as e:
            print(f"HTTP {e.code} {e.reason} — {e.read()[:300].decode('utf-8', 'replace')}", file=sys.stderr)
            return 1
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"요청 실패: {e}", file=sys.stderr)
            return 1
        label = "live " + date.today().isoformat()
    else:
        path = a.from_path or SAMPLE
        models = load_models(path)
        label = path.name + ("" if a.from_path else " (dry-run 샘플, API 응답이 아님)")

    if a.save:
        a.save.parent.mkdir(parents=True, exist_ok=True)
        a.save.write_text(json.dumps({"data": models, "fetched_at": date.today().isoformat()}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved {len(models)} models → {a.save}", file=sys.stderr)

    rows = [row_of(m) for m in models]
    if a.only:
        keep = set(a.only.split(","))
        rows = [r for r in rows if r.lifecycle in keep]
    if a.line:
        rows = [r for r in rows if r.line == a.line]

    if a.latest:
        r = latest_of_line(rows, a.latest)
        if r is None:
            print(f"line={a.latest} 인 active 모델이 없다", file=sys.stderr)
            return 1
        print(r.id)
        return 0
    if a.diff:
        old = [row_of(m) for m in load_models(a.diff)]
        print(render_diff(diff_rows(old, rows), a.diff.name, label))
        return 0
    if a.json:
        print(json.dumps([asdict(r) for r in rows], ensure_ascii=False, indent=2))
        return 0
    print(render_table(rows, title=f"모델 능력표 — {label}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

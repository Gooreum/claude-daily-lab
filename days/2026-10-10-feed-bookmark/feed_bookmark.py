#!/usr/bin/env python3
"""feed_bookmark.py — 소스별 북마크로 Atom/RSS 피드를 증분 읽는 CLI.

"Building effective agent automations" (claude.dev 블로그, 2026-10-08)의 조언을 그대로 구현한다:
  * 소스마다 북마크(이미 본 entry id)를 두고 새 항목만 보고한다.
  * 읽기 실패는 "조용한 하루"가 아니라 "불가(unavailable)"로 따로 보고하고 북마크를 건드리지 않는다.
  * 읽기 전용이다. 쓰는 파일은 북마크 상태 파일 하나뿐이며 원자적으로 저장한다.

표준 라이브러리만 사용한다. `file://` URL을 지원하므로 네트워크 없이 테스트할 수 있다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ATOM = "{http://www.w3.org/2005/Atom}"
SEEN_LIMIT = 200          # 소스당 기억하는 entry id 수 (피드 길이보다 작아지지 않게 보정)
DEFAULT_MAX_AGE_HOURS = 48
DEFAULT_TIMEOUT = 15.0
USER_AGENT = "feed-bookmark/1.0 (+https://github.com/claude-daily-lab)"
EXIT_OK = 0
EXIT_UNAVAILABLE = 2


class FetchError(Exception):
    """네트워크/파일 읽기 실패."""


class ParseError(Exception):
    """피드 형식을 해석할 수 없음."""


@dataclass
class Entry:
    id: str
    title: str
    link: str
    published: datetime | None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "link": self.link,
            "published": self.published.isoformat() if self.published else None,
        }


@dataclass
class SourceResult:
    name: str
    url: str
    status: str                      # "new" | "quiet" | "unavailable"
    entries: list[Entry] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "url": self.url,
            "status": self.status,
            "reason": self.reason,
            "entries": [e.to_dict() for e in self.entries],
        }


# ---------------------------------------------------------------- fetch / parse

def fetch(url: str, timeout: float = DEFAULT_TIMEOUT) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/atom+xml, application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise FetchError(f"HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise FetchError(f"URL error: {e.reason}") from e
    except (OSError, ValueError) as e:  # timeout, 잘못된 URL 등
        raise FetchError(f"{type(e).__name__}: {e}") from e


def _parse_dt(text: str | None) -> datetime | None:
    if not text:
        return None
    text = text.strip()
    dt: datetime | None = None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def _fallback_id(title: str, link: str, published: datetime | None) -> str:
    if link:
        return link
    key = f"{title}|{published.isoformat() if published else ''}"
    return "sha1:" + hashlib.sha1(key.encode("utf-8")).hexdigest()


def _atom_entry(el: ET.Element) -> Entry:
    title = _text(el.find(ATOM + "title"))
    link = ""
    for ln in el.findall(ATOM + "link"):
        href = ln.get("href", "")
        if ln.get("rel", "alternate") == "alternate" and href:
            link = href
            break
        link = link or href
    published = _parse_dt(_text(el.find(ATOM + "published"))) or _parse_dt(_text(el.find(ATOM + "updated")))
    eid = _text(el.find(ATOM + "id")) or _fallback_id(title, link, published)
    return Entry(eid, title, link, published)


def _rss_item(el: ET.Element) -> Entry:
    title = _text(el.find("title"))
    link = _text(el.find("link"))
    published = _parse_dt(_text(el.find("pubDate")))
    eid = _text(el.find("guid")) or _fallback_id(title, link, published)
    return Entry(eid, title, link, published)


def parse_feed(data: bytes) -> list[Entry]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise ParseError(f"XML parse error: {e}") from e
    if root.tag == ATOM + "feed":
        return [_atom_entry(e) for e in root.findall(ATOM + "entry")]
    if root.tag == "rss":
        channel = root.find("channel")
        if channel is None:
            raise ParseError("RSS without <channel>")
        return [_rss_item(i) for i in channel.findall("item")]
    raise ParseError(f"unknown root element {root.tag!r}")


# ---------------------------------------------------------------- bookmark diff

def diff_source(
    entries: list[Entry],
    bookmark: dict | None,
    now: datetime,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
) -> tuple[list[Entry], dict]:
    """(새 항목, 다음 북마크)를 돌려준다.

    첫 실행(bookmark None)에는 max_age_hours 안의 항목만 새 항목으로 보고하고,
    그보다 오래된 항목은 북마크에만 흡수한다. 이후 실행은 북마크만이 기준이다.
    """
    first_run = bookmark is None
    seen_list: list[str] = list(bookmark.get("seen_ids", [])) if bookmark else []
    seen = set(seen_list)
    cutoff = now - timedelta(hours=max_age_hours)

    new: list[Entry] = []
    for e in entries:
        if e.id in seen:
            continue
        if first_run and (e.published is None or e.published < cutoff):
            continue
        new.append(e)

    # 최신 항목이 위로 오게 정렬. 날짜 없는 항목은 맨 뒤.
    new.sort(key=lambda e: (e.published is None, -(e.published.timestamp() if e.published else 0)))

    current_ids = [e.id for e in entries]
    merged = seen_list + [i for i in current_ids if i not in seen]
    limit = max(SEEN_LIMIT, len(current_ids))
    merged = merged[-limit:]
    next_bookmark = {
        "seen_ids": merged,
        "last_ok": now.isoformat(),
        "last_new_count": len(new),
    }
    return new, next_bookmark


# ---------------------------------------------------------------- run

def run(
    sources: list[dict],
    state: dict,
    *,
    now: datetime,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    timeout: float = DEFAULT_TIMEOUT,
    fetcher=fetch,
) -> tuple[list[SourceResult], dict]:
    bookmarks: dict = dict(state.get("bookmarks", {}))
    results: list[SourceResult] = []
    for src in sources:
        name, url = src["name"], src["url"]
        try:
            entries = parse_feed(fetcher(url, timeout))
        except (FetchError, ParseError) as e:
            results.append(SourceResult(name, url, "unavailable", reason=str(e)))
            continue  # 북마크는 그대로 둔다
        if src.get("match"):  # 범용 피드(GeekNews, Product Hunt)는 제목이 정규식에 맞는 항목만 본다
            pat = re.compile(src["match"], re.IGNORECASE)
            entries = [e for e in entries if pat.search(e.title or "")]
        new, nxt = diff_source(entries, bookmarks.get(name), now, max_age_hours)
        bookmarks[name] = nxt
        results.append(SourceResult(name, url, "new" if new else "quiet", new))
    return results, {"version": 1, "bookmarks": bookmarks}


# ---------------------------------------------------------------- io

def load_sources(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("sources") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise ValueError(f"{path}: 'sources' 목록이 비어 있거나 형식이 다릅니다")
    out = []
    for i, it in enumerate(items):
        if not isinstance(it, dict) or not it.get("name") or not it.get("url"):
            raise ValueError(f"{path}: sources[{i}]에 name/url이 필요합니다")
        src = {"name": str(it["name"]), "url": str(it["url"])}
        if it.get("match"):
            try:
                re.compile(str(it["match"]))
            except re.error as e:
                raise ValueError(f"{path}: sources[{i}].match 정규식 오류: {e}") from e
            src["match"] = str(it["match"])
        out.append(src)
    return out


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "bookmarks": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{path}: 상태 파일이 깨졌습니다 ({e}). 지우고 다시 시작하세요") from e
    if not isinstance(data, dict) or not isinstance(data.get("bookmarks", {}), dict):
        raise ValueError(f"{path}: 상태 파일 형식이 다릅니다")
    data.setdefault("bookmarks", {})
    return data


def save_state(path: Path, state: dict) -> None:
    """같은 디렉터리의 임시 파일에 쓴 뒤 os.replace로 바꿔치기한다 (중간에 죽어도 기존 파일은 온전)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------- render

STATUS_LABEL = {"new": "새 항목", "quiet": "조용함 (새 항목 없음)", "unavailable": "⚠️ 읽기 불가"}


def render_markdown(results: list[SourceResult], now: datetime) -> str:
    n_new = sum(len(r.entries) for r in results)
    n_src_new = sum(1 for r in results if r.status == "new")
    n_quiet = sum(1 for r in results if r.status == "quiet")
    n_unavail = sum(1 for r in results if r.status == "unavailable")
    lines = [
        f"# 피드 증분 다이제스트 — {now.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"새 항목 {n_new}개 (소스 {n_src_new}개) · 조용함 {n_quiet} · 읽기 불가 {n_unavail}",
        "",
    ]
    for r in results:
        if r.status == "new":
            lines.append(f"## {r.name} — 새 항목 {len(r.entries)}개")
            for e in r.entries:
                when = e.published.strftime("%Y-%m-%d %H:%M") if e.published else "날짜 없음"
                title = e.title or "(제목 없음)"
                lines.append(f"- [{title}]({e.link}) — {when}" if e.link else f"- {title} — {when}")
        elif r.status == "quiet":
            lines.append(f"## {r.name} — {STATUS_LABEL['quiet']}")
        else:
            lines.append(f"## {r.name} — {STATUS_LABEL['unavailable']}: {r.reason} (북마크 유지)")
        lines.append("")
    if n_unavail:
        lines.append(f"> 읽기 불가 소스 {n_unavail}개. 이 결과는 '조용한 하루'가 아니라 '확인 못 한 하루'다.")
        lines.append("")
    return "\n".join(lines)


def render_json(results: list[SourceResult], now: datetime) -> str:
    return json.dumps(
        {"generated_at": now.isoformat(), "results": [r.to_dict() for r in results]},
        ensure_ascii=False,
        indent=2,
    )


# ---------------------------------------------------------------- cli

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="feed_bookmark.py",
        description="소스별 북마크로 Atom/RSS 피드를 증분 읽어 새 항목만 보고한다. "
                    "종료 코드: 0=모든 소스 읽음(조용함 포함), 2=읽기 불가 소스 있음.",
    )
    here = Path(__file__).resolve().parent
    p.add_argument("--sources", type=Path, default=here / "sources.json", help="소스 목록 JSON (기본: 스크립트 옆 sources.json)")
    p.add_argument("--state", type=Path, default=Path("feed-bookmark-state.json"), help="북마크 상태 파일 (기본: ./feed-bookmark-state.json)")
    p.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS, help="첫 실행에 새 항목으로 볼 최대 나이 (기본 48)")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="소스당 fetch 타임아웃 초 (기본 15)")
    p.add_argument("--dry-run", action="store_true", help="북마크를 저장하지 않는다")
    p.add_argument("--json", action="store_true", help="Markdown 대신 JSON 출력")
    p.add_argument("--now", help="현재 시각 ISO8601 (테스트용, 기본 UTC now)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = _parse_dt(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        print(f"--now 값을 해석할 수 없습니다: {args.now}", file=sys.stderr)
        return 1
    try:
        sources = load_sources(args.sources)
        state = load_state(args.state)
    except (OSError, ValueError) as e:
        print(f"feed_bookmark: {e}", file=sys.stderr)
        return 1

    results, new_state = run(sources, state, now=now, max_age_hours=args.max_age_hours, timeout=args.timeout)
    print(render_json(results, now) if args.json else render_markdown(results, now), end="")
    if not args.dry_run:
        try:
            save_state(args.state, new_state)
        except OSError as e:
            print(f"feed_bookmark: 상태 저장 실패: {e}", file=sys.stderr)
            return 1
    return EXIT_UNAVAILABLE if any(r.status == "unavailable" for r in results) else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

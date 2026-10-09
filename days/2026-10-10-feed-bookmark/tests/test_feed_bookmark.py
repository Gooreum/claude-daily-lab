"""feed_bookmark.py 단위·통합 테스트. 네트워크 없이 file:// fixture로만 돈다.
실행: 프로젝트 폴더에서 `python3 -m unittest discover -s tests -v` 또는 `bash test.sh`
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIX = HERE / "fixtures"
sys.path.insert(0, str(ROOT))

import feed_bookmark as fb  # noqa: E402

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def uri(name: str) -> str:
    return (FIX / name).resolve().as_uri()


class ParseTests(unittest.TestCase):
    def test_atom_entries(self):
        entries = fb.parse_feed((FIX / "atom_v1.xml").read_bytes())
        self.assertEqual([e.title for e in entries], ["v1.2.0", "v1.1.0", "v1.0.0"])
        self.assertEqual(entries[0].id, "tag:example.org,2026:v1.2.0")
        self.assertEqual(entries[0].link, "https://example.org/releases/v1.2.0")
        self.assertEqual(entries[0].published, datetime(2026, 10, 10, 2, 0, tzinfo=timezone.utc))

    def test_rss_guid_pubdate_and_fallback_id(self):
        entries = fb.parse_feed((FIX / "rss.xml").read_bytes())
        self.assertEqual(entries[0].id, "blog-2")
        self.assertEqual(entries[0].published, datetime(2026, 10, 10, 1, 30, tzinfo=timezone.utc))
        self.assertEqual(entries[1].id, "https://example.org/blog/first")  # guid 없으면 link

    def test_empty_feed_is_zero_entries(self):
        self.assertEqual(fb.parse_feed((FIX / "empty.xml").read_bytes()), [])

    def test_broken_xml_raises_parse_error(self):
        with self.assertRaises(fb.ParseError):
            fb.parse_feed((FIX / "broken.xml").read_bytes())

    def test_non_feed_raises_parse_error(self):
        with self.assertRaises(fb.ParseError):
            fb.parse_feed((FIX / "notfeed.html").read_bytes())


class FetchTests(unittest.TestCase):
    def test_file_url(self):
        self.assertIn(b"<feed", fb.fetch(uri("atom_v1.xml")))

    def test_missing_file_is_fetch_error(self):
        with self.assertRaises(fb.FetchError):
            fb.fetch(uri("does-not-exist.xml"))


class DiffTests(unittest.TestCase):
    def setUp(self):
        self.v1 = fb.parse_feed((FIX / "atom_v1.xml").read_bytes())
        self.v2 = fb.parse_feed((FIX / "atom_v2.xml").read_bytes())

    def test_first_run_reports_only_recent_but_absorbs_all(self):
        new, bm = fb.diff_source(self.v1, None, NOW, max_age_hours=48)
        self.assertEqual([e.title for e in new], ["v1.2.0", "v1.1.0"])  # v1.0.0은 100시간 전
        self.assertEqual(len(bm["seen_ids"]), 3)
        self.assertEqual(bm["last_new_count"], 2)

    def test_first_run_boundary_exactly_at_cutoff_counts_as_new(self):
        new, _ = fb.diff_source(self.v1, None, NOW, max_age_hours=30)  # v1.1.0은 정확히 30h 전
        self.assertEqual([e.title for e in new], ["v1.2.0", "v1.1.0"])

    def test_second_run_reports_only_added_entry(self):
        _, bm1 = fb.diff_source(self.v1, None, NOW, 48)
        new, bm2 = fb.diff_source(self.v2, bm1, NOW, 48)
        self.assertEqual([e.title for e in new], ["v1.3.0"])
        self.assertEqual(len(bm2["seen_ids"]), 4)

    def test_rerun_same_feed_is_quiet(self):
        _, bm1 = fb.diff_source(self.v1, None, NOW, 48)
        new, _ = fb.diff_source(self.v1, bm1, NOW, 48)
        self.assertEqual(new, [])

    def test_after_bookmark_old_unseen_entry_still_reported(self):
        # 북마크가 있으면 나이와 무관하게 "못 본 것"은 전부 새 항목이다
        bm = {"seen_ids": ["tag:example.org,2026:v1.2.0"]}
        new, _ = fb.diff_source(self.v1, bm, NOW, 48)
        self.assertEqual([e.title for e in new], ["v1.1.0", "v1.0.0"])

    def test_seen_ids_never_shrink_below_feed_length(self):
        many = [fb.Entry(f"id-{i}", f"t{i}", "", NOW) for i in range(fb.SEEN_LIMIT + 50)]
        _, bm = fb.diff_source(many, None, NOW, 48)
        self.assertEqual(len(bm["seen_ids"]), fb.SEEN_LIMIT + 50)
        new, _ = fb.diff_source(many, bm, NOW, 48)
        self.assertEqual(new, [])


class RunTests(unittest.TestCase):
    def test_unavailable_keeps_bookmark_and_other_sources_advance(self):
        sources = [
            {"name": "ok", "url": uri("atom_v1.xml")},
            {"name": "gone", "url": uri("missing.xml")},
            {"name": "bad", "url": uri("broken.xml")},
        ]
        state = {"bookmarks": {"gone": {"seen_ids": ["keep-me"], "last_ok": "x"}}}
        results, new_state = fb.run(sources, state, now=NOW)
        by = {r.name: r for r in results}
        self.assertEqual(by["ok"].status, "new")
        self.assertEqual(by["gone"].status, "unavailable")
        self.assertIn("URL error", by["gone"].reason)
        self.assertEqual(by["bad"].status, "unavailable")
        self.assertIn("XML parse error", by["bad"].reason)
        self.assertEqual(new_state["bookmarks"]["gone"], {"seen_ids": ["keep-me"], "last_ok": "x"})
        self.assertNotIn("bad", new_state["bookmarks"])
        self.assertEqual(len(new_state["bookmarks"]["ok"]["seen_ids"]), 3)

    def test_render_markdown_marks_unavailable(self):
        results = [
            fb.SourceResult("a", "u", "new", [fb.Entry("1", "T", "https://x", NOW)]),
            fb.SourceResult("b", "u", "quiet"),
            fb.SourceResult("c", "u", "unavailable", reason="HTTP 503"),
        ]
        md = fb.render_markdown(results, NOW)
        self.assertIn("새 항목 1개 (소스 1개) · 조용함 1 · 읽기 불가 1", md)
        self.assertIn("- [T](https://x) — 2026-10-10 12:00", md)
        self.assertIn("## c — ⚠️ 읽기 불가: HTTP 503 (북마크 유지)", md)
        self.assertIn("'확인 못 한 하루'", md)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.state = self.dir / "state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write_sources(self, *pairs):
        p = self.dir / "sources.json"
        p.write_text(json.dumps({"sources": [{"name": n, "url": uri(f)} for n, f in pairs]}))
        return p

    def cli(self, *args):
        cmd = [sys.executable, str(ROOT / "feed_bookmark.py"), "--now", NOW.isoformat(), "--state", str(self.state), *args]
        return subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.dir))

    def test_first_run_then_quiet_exit_0(self):
        src = self.write_sources(("ex", "atom_v1.xml"))
        r1 = self.cli("--sources", str(src))
        self.assertEqual(r1.returncode, 0, r1.stderr)
        self.assertIn("## ex — 새 항목 2개", r1.stdout)
        self.assertTrue(self.state.exists())
        r2 = self.cli("--sources", str(src))
        self.assertEqual(r2.returncode, 0)
        self.assertIn("## ex — 조용함", r2.stdout)

    def test_dry_run_writes_no_state(self):
        src = self.write_sources(("ex", "atom_v1.xml"))
        r = self.cli("--sources", str(src), "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.state.exists())

    def test_unavailable_exit_2_and_json(self):
        src = self.write_sources(("ex", "atom_v1.xml"), ("gone", "missing.xml"))
        r = self.cli("--sources", str(src), "--json")
        self.assertEqual(r.returncode, 2)
        data = json.loads(r.stdout)
        self.assertEqual([x["status"] for x in data["results"]], ["new", "unavailable"])
        saved = json.loads(self.state.read_text())  # 원자적 저장 결과가 유효한 JSON
        self.assertEqual(list(saved["bookmarks"]), ["ex"])
        self.assertFalse(list(self.dir.glob("*.tmp")))

    def test_corrupt_state_exit_1(self):
        src = self.write_sources(("ex", "atom_v1.xml"))
        self.state.write_text("{not json")
        r = self.cli("--sources", str(src))
        self.assertEqual(r.returncode, 1)
        self.assertIn("상태 파일이 깨졌습니다", r.stderr)

    def test_bad_sources_exit_1(self):
        p = self.dir / "sources.json"
        p.write_text('{"sources": []}')
        r = self.cli("--sources", str(p))
        self.assertEqual(r.returncode, 1)
        self.assertIn("sources", r.stderr)


if __name__ == "__main__":
    unittest.main()

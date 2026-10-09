import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import model_caps as mc  # noqa: E402

SAMPLE = Path(__file__).resolve().parents[1] / "sample-models.json"
PREV = Path(__file__).resolve().parents[1] / "sample-models-prev.json"


def cap(v):
    return {"supported": v}


FULL = {
    "id": "claude-x-1", "display_name": "X", "line": "sonnet", "lifecycle": "active",
    "created_at": "2026-10-01T00:00:00Z", "deprecated_at": None, "retires_at": None,
    "max_input_tokens": 1_000_000, "max_tokens": 64_000,
    "capabilities": {
        "thinking": {"supported": True, "types": {"adaptive": cap(True), "enabled": cap(True), "disabled": cap(False)}},
        "effort": {"supported": True, "low": cap(True), "medium": cap(True), "high": cap(True), "xhigh": cap(False), "max": cap(True)},
        "server_tools": {"supported": True, "web_search": cap(True), "code_execution": cap(False)},
        "structured_outputs": cap(True), "image_input": cap(True), "pdf_input": cap(False), "batch": cap(True),
    },
}


class RowOf(unittest.TestCase):
    def test_full_model(self):
        r = mc.row_of(FULL)
        self.assertEqual((r.id, r.line, r.lifecycle, r.created), ("claude-x-1", "sonnet", "active", "2026-10-01"))
        self.assertEqual((r.think_adaptive, r.think_enabled, r.think_disabled), (True, True, False))
        self.assertEqual(r.efforts, "low,medium,high,max")  # xhigh가 빠져 비연속 → 나열
        self.assertEqual((r.web_search, r.code_execution, r.pdf_input), (True, False, False))

    def test_null_capabilities_become_unknown(self):
        r = mc.row_of({"id": "old", "lifecycle": "retired", "capabilities": None})
        self.assertIsNone(r.think_disabled)
        self.assertIsNone(r.web_search)
        self.assertEqual(r.efforts, "?")
        self.assertEqual(r.created, "?")
        self.assertEqual(r.display_name, "old")

    def test_efforts_contiguous_range_and_unsupported(self):
        self.assertEqual(mc.efforts_of({"supported": True, "low": cap(True), "medium": cap(True), "high": cap(True), "xhigh": cap(True), "max": cap(True)}), "low-max")
        self.assertEqual(mc.efforts_of({"supported": True, "medium": cap(True), "high": cap(True)}), "medium-high")
        self.assertEqual(mc.efforts_of({"supported": True, "high": cap(True)}), "high")
        self.assertEqual(mc.efforts_of({"supported": False}), "-")
        self.assertEqual(mc.efforts_of(None), "?")

    def test_malformed_support_object_is_unknown_not_crash(self):
        r = mc.row_of({"id": "weird", "capabilities": {"server_tools": {"web_search": {"supported": "yes"}}, "thinking": "nope"}})
        self.assertIsNone(r.web_search)
        self.assertIsNone(r.think_adaptive)


class Payload(unittest.TestCase):
    def test_accepts_dict_or_list_and_drops_junk(self):
        self.assertEqual([m["id"] for m in mc.models_of({"data": [{"id": "a"}, {"nope": 1}, "x"]})], ["a"])
        self.assertEqual([m["id"] for m in mc.models_of([{"id": "b"}])], ["b"])
        with self.assertRaises(ValueError):
            mc.models_of("text")

    def test_sample_fixture_loads_eight_models(self):
        self.assertEqual(len(mc.load_models(SAMPLE)), 8)


class Fetch(unittest.TestCase):
    def test_paginates_with_after_id_and_lifecycle_filter(self):
        urls = []
        pages = [
            {"data": [{"id": "m1"}, {"id": "m2"}], "has_more": True, "last_id": "m2"},
            {"data": [{"id": "m3"}], "has_more": False, "last_id": "m3"},
        ]

        def fetch(url):
            urls.append(url)
            return pages[len(urls) - 1]

        got = mc.fetch_models(fetch, base="https://x.test", lifecycles=["active", "retired"], limit=2)
        self.assertEqual([m["id"] for m in got], ["m1", "m2", "m3"])
        self.assertEqual(urls[0], "https://x.test/v1/models?limit=2&lifecycle[]=active&lifecycle[]=retired")
        self.assertTrue(urls[1].endswith("&after_id=m2"))

    def test_stops_at_max_pages_even_if_has_more(self):
        n = 0

        def fetch(url):
            nonlocal n
            n += 1
            return {"data": [{"id": f"m{n}"}], "has_more": True, "last_id": f"m{n}"}

        got = mc.fetch_models(fetch, max_pages=3)
        self.assertEqual(len(got), 3)


class Table(unittest.TestCase):
    def test_fmt_tokens(self):
        self.assertEqual([mc.fmt_tokens(x) for x in (None, 999, 64_000, 200_000, 1_000_000, 1_500_000)], ["?", "999", "64K", "200K", "1M", "1.5M"])

    def test_sort_active_first_then_newest(self):
        rows = [mc.row_of(m) for m in mc.load_models(SAMPLE)]
        ids = [r.id for r in mc.sort_rows(rows)]
        self.assertEqual(ids[0], "claude-haiku-5-5")
        self.assertEqual(ids[-1], "claude-3-7-sonnet-20250219")
        self.assertLess(ids.index("claude-opus-5"), ids.index("claude-haiku-4-5"))

    def test_render_table_has_header_rows_and_unknown_marks(self):
        rows = [mc.row_of(m) for m in mc.load_models(SAMPLE)]
        md = mc.render_table(rows, title="t")
        lines = md.splitlines()
        self.assertEqual(lines[0], "### t")
        self.assertTrue(lines[2].startswith("| 모델 | line | 상태 |"))
        self.assertEqual(lines[3].count("---"), len(mc.COLUMNS))
        self.assertIn("| `claude-3-7-sonnet-20250219` | - | retired (~2026-02-19) | 2025-02-19 | 200K | 128K | ??? | ? |", md)
        self.assertIn("8 models", md)

    def test_latest_of_line_ignores_deprecated(self):
        rows = [mc.row_of(m) for m in mc.load_models(PREV)]
        self.assertEqual(mc.latest_of_line(rows, "haiku").id, "claude-haiku-4-5")
        rows = [mc.row_of(m) for m in mc.load_models(SAMPLE)]
        self.assertEqual(mc.latest_of_line(rows, "haiku").id, "claude-haiku-5-5")
        self.assertIsNone(mc.latest_of_line(rows, "mythos"))


class Diff(unittest.TestCase):
    def test_added_removed_changed(self):
        old = [mc.row_of(m) for m in mc.load_models(PREV)]
        new = [mc.row_of(m) for m in mc.load_models(SAMPLE)]
        d = mc.diff_rows(old, new)
        self.assertEqual(d["added"], ["claude-3-7-sonnet-20250219", "claude-haiku-5-5"])
        self.assertEqual(d["removed"], [])
        self.assertIn("claude-haiku-4-5", d["changed"])
        self.assertIn(("lifecycle", "active", "deprecated"), d["changed"]["claude-haiku-4-5"])
        self.assertEqual(d["changed"]["claude-sonnet-5-5"], [("code_execution", False, True)])
        self.assertNotIn("claude-opus-5-5", d["changed"])

    def test_render_diff_no_change(self):
        rows = [mc.row_of(m) for m in mc.load_models(SAMPLE)]
        self.assertTrue(mc.render_diff(mc.diff_rows(rows, rows), "a", "b").endswith("변경 없음"))

    def test_render_diff_lines(self):
        old = [mc.row_of({"id": "gone"}), mc.row_of({"id": "same", "line": "opus"})]
        new = [mc.row_of({"id": "same", "line": "fable"}), mc.row_of({"id": "new"})]
        md = mc.render_diff(mc.diff_rows(old, new), "old", "new")
        self.assertIn("- ➕ 추가 `new`", md)
        self.assertIn("- ➖ 사라짐 `gone`", md)
        self.assertIn("- 🔁 `same`: line opus → fable", md)


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        import contextlib
        import io
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = mc.main(list(args))
        return rc, out.getvalue(), err.getvalue()

    def test_default_is_dry_run_sample(self):
        rc, out, _ = self.run_cli()
        self.assertEqual(rc, 0)
        self.assertIn("dry-run 샘플", out)
        self.assertIn("`claude-haiku-5-5`", out)

    def test_live_without_key_exits_2(self):
        import os
        os.environ.pop("ANTHROPIC_API_KEY", None)
        rc, _, err = self.run_cli("--live")
        self.assertEqual(rc, 2)
        self.assertIn("ANTHROPIC_API_KEY", err)

    def test_save_json_latest_and_diff(self):
        with tempfile.TemporaryDirectory() as d:
            snap = Path(d) / "snap.json"
            rc, _, err = self.run_cli("--save", str(snap), "--json")
            self.assertEqual(rc, 0)
            self.assertIn("saved 8 models", err)
            self.assertEqual(len(json.loads(snap.read_text())["data"]), 8)
            rc, out, _ = self.run_cli("--from", str(snap), "--latest", "opus")
            self.assertEqual((rc, out.strip()), (0, "claude-opus-5-5"))
            rc, out, _ = self.run_cli("--from", str(snap), "--diff", str(PREV))
            self.assertEqual(rc, 0)
            self.assertIn("➕ 추가 `claude-haiku-5-5`", out)

    def test_latest_missing_line_exits_1(self):
        rc, _, err = self.run_cli("--latest", "mythos")
        self.assertEqual(rc, 1)
        self.assertIn("mythos", err)


if __name__ == "__main__":
    unittest.main()

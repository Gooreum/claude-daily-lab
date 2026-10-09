"""motion_lite.py 테스트. 모델 호출 없이 검증·렌더·CLI를 확인한다."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import motion_lite as ML  # noqa: E402


def sb():
    return copy.deepcopy(ML.BUILTIN)


class Validation(unittest.TestCase):
    def test_builtin_is_valid(self):
        ML.validate_storyboard(ML.BUILTIN)

    def test_schema_and_validator_agree_on_limits(self):
        self.assertEqual(ML.SCHEMA["properties"]["scenes"]["maxItems"], ML.MAX_SCENES)
        self.assertEqual(ML.SCHEMA["properties"]["scenes"]["items"]["properties"]["shapes"]["maxItems"], ML.MAX_SHAPES)
        self.assertEqual(ML.SCHEMA["properties"]["scenes"]["items"]["properties"]["shapes"]["items"]["properties"]["anim"]["enum"], ML.ANIMS)

    def test_rejects_bad_inputs(self):
        cases = {
            "title 없음": lambda s: s.pop("title"),
            "장면 1개": lambda s: s["scenes"].__setitem__(slice(None), s["scenes"][:1]),
            "duration 너무 김": lambda s: s["scenes"][0].__setitem__("duration_s", 30),
            "bg 색 형식": lambda s: s["scenes"][0].__setitem__("bg", "navy"),
            "shape kind": lambda s: s["scenes"][0]["shapes"][0].__setitem__("kind", "star"),
            "x 범위": lambda s: s["scenes"][0]["shapes"][0].__setitem__("x", 140),
            "anim 값": lambda s: s["scenes"][0]["shapes"][0].__setitem__("anim", "explode"),
            "color 형식": lambda s: s["scenes"][0]["shapes"][0].__setitem__("color", "red"),
            "shapes 비어 있음": lambda s: s["scenes"][0].__setitem__("shapes", []),
            "delay 범위": lambda s: s["scenes"][0]["shapes"][0].__setitem__("delay_s", 9),
        }
        for name, mutate in cases.items():
            s = sb(); mutate(s)
            with self.assertRaises(ML.StoryboardError, msg=name):
                ML.validate_storyboard(s)

    def test_boundaries_accepted(self):
        s = sb()
        s["scenes"][0]["duration_s"] = 1.5
        s["scenes"][1]["duration_s"] = 8
        s["scenes"][0]["shapes"][0].update({"x": 0, "y": 100, "w": 1, "h": 100, "delay_s": 6})
        ML.validate_storyboard(s)


class Render(unittest.TestCase):
    def test_html_embeds_storyboard_and_is_self_contained(self):
        html = ML.render_html(ML.BUILTIN)
        self.assertIn('<script id="sb" type="application/json">', html)
        start = html.index('type="application/json">') + len('type="application/json">')
        embedded = json.loads(html[start:html.index("</script>", start)])
        self.assertEqual(embedded["title"], ML.BUILTIN["title"])
        self.assertEqual(len(embedded["scenes"]), 4)
        self.assertNotIn("http://", html.split("<script>")[1])
        self.assertNotIn("https://", html.split("<script>")[1])
        self.assertIn("MediaRecorder", html)
        self.assertIn("captureStream", html)

    def test_script_breakout_is_escaped_and_meta_dropped(self):
        s = sb(); s["title"] = "</script><b>x"; s["_meta"] = {"cost_usd": 1}
        html = ML.render_html(s)
        self.assertNotIn("</script><b>x", html)
        self.assertNotIn("cost_usd", html)
        self.assertIn("<title>&lt;/script&gt;&lt;b&gt;x</title>", html)

    def test_render_rejects_invalid(self):
        s = sb(); s["scenes"] = []
        with self.assertRaises(ML.StoryboardError):
            ML.render_html(s)

    def test_slugify(self):
        self.assertEqual(ML.slugify("Claude Code 모드란?"), "claude-code-모드란")
        self.assertEqual(ML.slugify("!!!"), "motion")


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "motion_lite.py"), *args], capture_output=True, text=True)

    def test_dry_run_writes_html(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.run_cli("--dry-run", "--out", d, "--save-json")
            self.assertEqual(r.returncode, 0, r.stderr)
            files = sorted(p.name for p in Path(d).iterdir())
            self.assertEqual(files, ["claude-code-모드란.html", "claude-code-모드란.json"])
            self.assertIn("4장면, 18.0초", r.stdout)

    def test_storyboard_file_and_bad_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json"; p.write_text(json.dumps(sb()), encoding="utf-8")
            self.assertEqual(self.run_cli("--storyboard", str(p), "--out", d).returncode, 0)
            p.write_text('{"title": "x", "scenes": []}', encoding="utf-8")
            r = self.run_cli("--storyboard", str(p), "--out", d)
            self.assertEqual(r.returncode, 1)
            self.assertIn("scenes는 2~", r.stderr)

    def test_no_args_is_an_error(self):
        self.assertEqual(self.run_cli().returncode, 2)


class ModelBackend(unittest.TestCase):
    def _with_fake(self, stdout, fn):
        orig = subprocess.run
        captured = {}
        def run(cmd, **k):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
        subprocess.run = run
        try:
            return fn(), captured
        finally:
            subprocess.run = orig

    def test_valid_structured_output_is_used(self):
        out = json.dumps({"structured_output": sb(), "total_cost_usd": 0.004, "duration_ms": 3200})
        result, cap = self._with_fake(out, lambda: ML.storyboard_from_model("x", model="m"))
        self.assertEqual(result["title"], ML.BUILTIN["title"])
        self.assertEqual(result["_meta"]["cost_usd"], 0.004)
        self.assertIn("--json-schema", cap["cmd"])
        self.assertEqual(cap["cmd"][cap["cmd"].index("--model") + 1], "m")

    def test_invalid_model_output_raises(self):
        out = json.dumps({"structured_output": {"title": "t", "scenes": [{"caption": "c"}]}})
        with self.assertRaises(ML.StoryboardError):
            self._with_fake(out, lambda: ML.storyboard_from_model("x"))

    def test_is_error_raises(self):
        out = json.dumps({"is_error": True, "result": "Not logged in"})
        with self.assertRaises(ML.StoryboardError):
            self._with_fake(out, lambda: ML.storyboard_from_model("x"))


if __name__ == "__main__":
    unittest.main()

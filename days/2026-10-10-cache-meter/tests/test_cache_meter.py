"""cache_meter.py 테스트. 모델 호출 없이 프롬프트 생성·집계·그래프·백엔드 파싱·CLI를 확인한다."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import cache_meter as CM  # noqa: E402


class Prompts(unittest.TestCase):
    def test_handbook_is_deterministic_and_long(self):
        a, b = CM.handbook(), CM.handbook()
        self.assertEqual(a, b)
        self.assertGreater(len(a), 15000)
        self.assertIn("45 days from invoice", a)

    def test_stable_is_identical_across_calls(self):
        self.assertEqual(CM.system_prompt("stable", 0, "BASE"), CM.system_prompt("stable", 7, "BASE"))

    def test_volatile_head_and_tail_positions_and_uniqueness(self):
        h1, h2 = CM.system_prompt("volatile-head", 0, "BASE"), CM.system_prompt("volatile-head", 1, "BASE")
        self.assertTrue(h1.endswith("\nBASE") and h2.endswith("\nBASE"))
        self.assertNotEqual(h1, h2)
        t1 = CM.system_prompt("volatile-tail", 0, "BASE")
        self.assertTrue(t1.startswith("BASE\n[request 0"))

    def test_unknown_scenario(self):
        with self.assertRaises(ValueError):
            CM.system_prompt("nope", 0, "BASE")


class Math(unittest.TestCase):
    def test_hit_rate_and_prompt_tokens(self):
        c = CM.Call("stable", 1, 0, 6000, 40, 10, 0.0001, 1000)
        self.assertEqual(c.prompt_tokens, 6040)
        self.assertAlmostEqual(c.hit_rate, 6000 / 6040)
        self.assertEqual(CM.Call("s", 0, 0, 0, 0, 0, 0, 0).hit_rate, 0.0)

    def test_summarize_excludes_first_call_from_hit_rate(self):
        calls = CM.measure(CM.SCENARIOS, 4, "m", dry_run=True, seed=1)
        stats = {s.scenario: s for s in CM.summarize(calls)}
        self.assertGreater(stats["stable"].hit_rate_after_first, 0.98)
        self.assertEqual(stats["stable"].writes_after_first, 0)
        self.assertEqual(stats["volatile-head"].hit_rate_after_first, 0.0)
        self.assertEqual(stats["volatile-head"].writes_after_first, 3 * 6000)
        self.assertGreater(stats["volatile-tail"].hit_rate_after_first, 0.95)
        self.assertLess(stats["volatile-head"].total_cost, 0.004)
        self.assertLess(stats["stable"].total_cost, stats["volatile-head"].total_cost / 2)

    def test_summarize_counts_errors_and_subset(self):
        calls = [CM.Call("stable", 0, 100, 0, 5, 1, 0.0, 10), CM.Call("stable", 1, 0, 0, 0, 0, 0.0, 10, error="boom")]
        s = CM.summarize(calls, ["stable"])[0]
        self.assertEqual((s.n, s.errors), (2, 1))
        self.assertEqual(CM.summarize(calls, ["volatile-tail"]), [])

    def test_bar(self):
        self.assertEqual(CM.bar(0, 10, 4), "░░░░")
        self.assertEqual(CM.bar(10, 10, 4), "████")
        self.assertEqual(CM.bar(3, 0, 4), "░░░░")


class Render(unittest.TestCase):
    def test_render_sections_and_glyph_row(self):
        calls = CM.measure(CM.SCENARIOS, 3, "m", dry_run=True, seed=2)
        text = CM.render(calls, CM.summarize(calls), "m")
        for key in ("호출별 캐시 읽기 비율", "2회차 이후 평균 캐시 적중률", "총 비용", "누적 비용 곡선", "stable", "volatile-head"):
            self.assertIn(key, text)
        self.assertIn("stable         ▒ ■ ■", text)
        self.assertIn("volatile-head  ▒ ▒ ▒", text)
        self.assertNotIn("⚠ 실패", text)

    def test_render_marks_errors(self):
        calls = [CM.Call("stable", 0, 100, 0, 5, 1, 0.0, 10), CM.Call("stable", 1, 0, 0, 0, 0, 0.0, 10, error="ValueError: x")]
        text = CM.render(calls, CM.summarize(calls, ["stable"]), "m")
        self.assertIn("stable         ▒ ✗", text)
        self.assertIn("⚠ 실패 1건: stable#2: ValueError: x", text)


class Backend(unittest.TestCase):
    def _fake(self, stdout):
        orig = subprocess.run
        cap = {}
        def run(cmd, **k):
            cap["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
        subprocess.run = run
        try:
            return CM.run_call("volatile-tail", 2, "m", "BASE"), cap
        finally:
            subprocess.run = orig

    def test_parses_usage(self):
        out = json.dumps({"usage": {"cache_creation_input_tokens": 12, "cache_read_input_tokens": 5900, "input_tokens": 40, "output_tokens": 9},
                          "total_cost_usd": 0.00008, "duration_ms": 1234})
        c, cap = self._fake(out)
        self.assertEqual((c.cache_write, c.cache_read, c.uncached_input, c.output_tokens, c.cost_usd, c.duration_ms, c.error),
                         (12, 5900, 40, 9, 0.00008, 1234, ""))
        sp = cap["cmd"][cap["cmd"].index("--system-prompt") + 1]
        self.assertTrue(sp.startswith("BASE\n[request 2"))
        self.assertIn("--no-session-persistence", cap["cmd"])

    def test_error_and_garbage_recorded(self):
        c, _ = self._fake(json.dumps({"is_error": True, "subtype": "error_max_turns", "result": None}))
        self.assertIn("error_max_turns", c.error)
        c, _ = self._fake("nope")
        self.assertIn("JSONDecodeError", c.error)


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "cache_meter.py"), *args], capture_output=True, text=True)

    def test_dry_run_saves_and_reloads(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.run_cli("--dry-run", "-n", "3", "--scenarios", "stable,volatile-head", "--out", d)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("시나리오 2개 × 3회 = 호출 6회", r.stdout)
            saved = list(Path(d).glob("*-dry.json"))
            self.assertEqual(len(saved), 1)
            r2 = self.run_cli("--from", str(saved[0]), "--scenarios", "stable,volatile-head")
            self.assertEqual(r2.returncode, 0, r2.stderr)
            self.assertIn("호출 6회", r2.stdout)

    def test_bad_args(self):
        self.assertEqual(self.run_cli("--dry-run", "--scenarios", "x", "--no-save").returncode, 2)
        self.assertEqual(self.run_cli("--dry-run", "-n", "1", "--no-save").returncode, 2)


if __name__ == "__main__":
    unittest.main()

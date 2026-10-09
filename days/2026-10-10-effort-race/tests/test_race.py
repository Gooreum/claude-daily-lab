"""race.py 테스트. 모델 호출 없이 채점·집계·그래프·CLI·백엔드 파싱을 확인한다."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import race as R  # noqa: E402


class Grading(unittest.TestCase):
    def test_normalize_and_grade(self):
        self.assertTrue(R.grade("5", "5"))
        self.assertTrue(R.grade("5 cents", "5"))
        self.assertTrue(R.grade("05", "5"))
        self.assertTrue(R.grade("Tuesday.", "tuesday"))
        self.assertTrue(R.grade("ciporhtna", "ciporhtna"))
        self.assertTrue(R.grade("The ball costs 5 cents.", "5"))
        self.assertTrue(R.grade("1,000", "1000"))
        self.assertFalse(R.grade("10", "5"))
        self.assertFalse(R.grade("15", "5"))
        self.assertFalse(R.grade("five", "5"))
        self.assertFalse(R.grade("", "5"))
        self.assertFalse(R.grade("42", "327"))

    def test_tasks_have_unique_ids_and_answers(self):
        ids = [t[0] for t in R.TASKS]
        self.assertEqual(len(ids), len(set(ids)))
        for _, q, exp in R.TASKS:
            self.assertTrue(q.strip() and exp.strip())


class Aggregation(unittest.TestCase):
    def results(self):
        return R.race("m", R.LEVELS, R.TASKS, dry_run=True, seed=3)

    def test_dry_run_is_reproducible_and_complete(self):
        a, b = self.results(), self.results()
        self.assertEqual([r.__dict__ for r in a], [r.__dict__ for r in b])
        self.assertEqual(len(a), len(R.LEVELS) * len(R.TASKS))
        self.assertEqual({(r.level, r.task) for r in a}, {(lv, t[0]) for lv in R.LEVELS for t in R.TASKS})

    def test_summarize_counts(self):
        rs = self.results()
        stats = R.summarize(rs)
        self.assertEqual([s.level for s in stats], R.LEVELS)
        for s in stats:
            self.assertEqual(s.n, len(R.TASKS))
            self.assertEqual(s.correct, sum(r.correct for r in rs if r.level == s.level))
            self.assertAlmostEqual(s.cost, sum(r.cost_usd for r in rs if r.level == s.level))
        self.assertEqual(R.summarize(rs, ["max"])[0].level, "max")
        self.assertEqual(R.summarize([], ["low"]), [])

    def test_bar_scaling(self):
        self.assertEqual(R.bar(0, 10, 4), "░░░░")
        self.assertEqual(R.bar(10, 10, 4), "████")
        self.assertEqual(R.bar(5, 10, 4), "██░░")
        self.assertEqual(R.bar(5, 0, 4), "░░░░")  # vmax 0이면 빈 막대

    def test_render_has_sections_and_grid(self):
        rs = self.results()
        text = R.render(R.summarize(rs), rs, "m")
        for key in ("정답률", "중앙값 소요 시간", "평균 생각(thinking) 토큰", "총 비용", "문제별 정답", "bat-ball", "sisters"):
            self.assertIn(key, text)
        self.assertNotIn("⚠ 실패", text)

    def test_render_lists_errors(self):
        rs = [R.Result("low", "arith", "", "327", False, 1000, 0, 0, 0.0, error="ValueError: boom"), R.Result("low", "lily", "47", "47", True, 900, 5, 0, 0.001)]
        text = R.render(R.summarize(rs, ["low"]), rs, "m")
        self.assertIn("⚠ 실패 1건: low/arith: ValueError: boom", text)
        self.assertIn("50.0%", text)


class Backend(unittest.TestCase):
    def _fake(self, stdout, rc=0):
        orig = subprocess.run
        captured = {}
        def run(cmd, **k):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, rc, stdout=stdout, stderr="")
        subprocess.run = run
        try:
            return R.run_one("xhigh", "arith", "q", "327", "m"), captured
        finally:
            subprocess.run = orig

    def test_parses_usage_and_grades(self):
        out = json.dumps({"structured_output": {"answer": "327"}, "duration_ms": 2100, "total_cost_usd": 0.0031,
                          "usage": {"output_tokens": 140, "output_tokens_details": {"thinking_tokens": 120}}})
        r, cap = self._fake(out)
        self.assertEqual((r.correct, r.duration_ms, r.output_tokens, r.thinking_tokens, r.cost_usd, r.error), (True, 2100, 140, 120, 0.0031, ""))
        self.assertEqual(cap["cmd"][cap["cmd"].index("--effort") + 1], "xhigh")
        self.assertIn("--json-schema", cap["cmd"])

    def test_error_response_is_recorded_not_raised(self):
        r, _ = self._fake(json.dumps({"is_error": True, "result": "Not logged in"}))
        self.assertFalse(r.correct)
        self.assertIn("Not logged in", r.error)

    def test_garbage_stdout_is_recorded(self):
        r, _ = self._fake("not json")
        self.assertIn("JSONDecodeError", r.error)


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "race.py"), *args], capture_output=True, text=True)

    def test_dry_run_saves_and_reloads(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.run_cli("--dry-run", "--seed", "1", "--out", d, "--tasks", "3", "--levels", "low,max")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("문제 3개 × 레벨 2개 = 호출 6회", r.stdout)
            saved = list(Path(d).glob("*-dry.json"))
            self.assertEqual(len(saved), 1)
            r2 = self.run_cli("--from", str(saved[0]), "--levels", "low,max", "--tasks", "3")
            self.assertEqual(r2.returncode, 0, r2.stderr)
            self.assertIn("호출 6회", r2.stdout)

    def test_unknown_level_is_an_error(self):
        r = self.run_cli("--dry-run", "--levels", "turbo", "--no-save")
        self.assertEqual(r.returncode, 2)
        self.assertIn("모르는 레벨", r.stderr)


if __name__ == "__main__":
    unittest.main()

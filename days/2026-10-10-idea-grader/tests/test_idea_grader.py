import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import idea_grader as g  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples" / "news-sample.md"
FIXED = ROOT / "samples" / "news-sample-fixed.md"
GOOD = "사내 모노레포 → `.env` 패턴을 막는 PreToolUse 훅에 onFailure block → 가드가 조용히 꺼지지 않는다"


class Parse(unittest.TestCase):
    def test_items_and_ideas(self):
        items = g.parse_news(SAMPLE.read_text(encoding="utf-8"))
        self.assertEqual([i.n for i in items], [1, 2, 3])
        self.assertEqual(len(items[0].ideas), 6)
        self.assertEqual(len(items[1].ideas), 5)
        self.assertEqual(len(items[2].ideas), 4)
        self.assertTrue(items[0].ideas[0].startswith("사내 모노레포 →"))

    def test_item_without_ideas_block(self):
        items = g.parse_news("## 1. 제목\n- 요약: x\n\n## 2. 둘\n- 현실 적용:\n  - a → b → c\n")
        self.assertEqual(items[0].ideas, [])
        self.assertEqual(items[1].ideas, ["a → b → c"])

    def test_ideas_block_ends_at_next_top_level_bullet(self):
        items = g.parse_news("## 1. 제목\n- 현실 적용:\n  - a → b → c\n- 비고: 아님\n  - 이건 아이디어가 아님\n")
        self.assertEqual(items[0].ideas, ["a → b → c"])


class Lines(unittest.TestCase):
    def test_good_line_has_no_problems(self):
        c = g.check_line(GOOD)
        self.assertTrue(c.shape_ok and c.length_ok and not c.vague)
        self.assertEqual(c.problems, [])
        self.assertEqual(c.contexts, {"team"})

    def test_vague_and_shape(self):
        c = g.check_line("팀 → 기능 X를 활용 가능 → 도움이 될 것")
        self.assertEqual(c.vague, ["활용 가능", "도움이 될 것"])
        self.assertTrue(c.shape_ok)
        c = g.check_line("어디에나 → 잘 쓰면 좋다")
        self.assertFalse(c.shape_ok)
        self.assertFalse(c.length_ok)
        self.assertEqual(len(c.problems), 2)

    def test_contexts(self):
        self.assertEqual(g.contexts_of("이 저장소 → a → b"), {"repo"})
        self.assertEqual(g.contexts_of("고객 지원 봇 → a → b"), {"product"})
        self.assertEqual(g.contexts_of("외계 → a → b"), {"other"})

    def test_similarity_catches_variations(self):
        a = "팀 → 기능 X를 활용 가능 → 도움이 될 것"
        b = "팀 → 기능 X를 활용 가능 → 생산성에 도움이 된다"
        self.assertGreaterEqual(g.similarity(a, b), g.DUP_THRESHOLD)
        self.assertLess(g.similarity(GOOD, a), g.DUP_THRESHOLD)


class Scores(unittest.TestCase):
    def setUp(self):
        self.items = g.parse_news(SAMPLE.read_text(encoding="utf-8"))

    def test_good_item_scores_high(self):
        s = g.grade_item(self.items[0])
        self.assertTrue(s.count_ok)
        self.assertEqual(s.dup_pairs, [])
        self.assertGreaterEqual(s.rule_score, 90)

    def test_bad_item_scores_low_with_reasons(self):
        s = g.grade_item(self.items[2])
        self.assertFalse(s.count_ok)
        self.assertEqual(len(s.dup_pairs), 1)
        self.assertEqual(s.effective, 3)
        self.assertLess(s.rule_score, 65)
        self.assertEqual(s.lines[0].vague, ["활용 가능", "도움이 될 것"])

    def test_empty_item_scores_zero(self):
        self.assertEqual(g.grade_item(g.Item(9, "x")).rule_score, 0)

    def test_judge_blends_70_30(self):
        s = g.grade_item(self.items[0])
        s.judge = {"score": 40, "per": [], "cost": 0.0}
        self.assertEqual(s.score, round(s.rule_score * 0.7 + 12))

    def test_parse_judge_missing_rows_count_zero(self):
        j = g.parse_judge({"ideas": [{"index": 1, "concrete": 2, "benefit": 2, "note": "좋음"}, {"index": 3, "concrete": 1, "benefit": 0, "note": ""}]}, 4)
        self.assertEqual(j["score"], round(100 * 5 / 16))
        self.assertEqual(j["per"][1], (0, 0, ""))


class Render(unittest.TestCase):
    def test_table_and_fix_list(self):
        scores = [g.grade_item(i) for i in g.parse_news(SAMPLE.read_text(encoding="utf-8"))]
        md = g.render(scores, "s.md", worst=4)
        self.assertIn("| # | 항목 | 개수 | 형식 | 막연 | 맥락 | 중복 | 규칙 |", md)
        self.assertIn("| 3 | (일부러 나쁜 항목) 가상의 기능 X 출시 | 4 ⚠ |", md)
        self.assertIn("### 고칠 줄 (최대 4개, 전체 4개)", md)
        self.assertIn("막연한 말: 활용 가능, 도움이 될 것", md)
        self.assertIn("같은 아이디어의 변주", md)

    def test_compare_flags_regression_and_adopts_gain(self):
        a = [g.grade_item(i) for i in g.parse_news(SAMPLE.read_text(encoding="utf-8"))]
        b = [g.grade_item(i) for i in g.parse_news(FIXED.read_text(encoding="utf-8"))]
        up = g.render_compare(a, b, "a", "b")
        self.assertIn("✅ 채택", up)
        self.assertIn("오른 항목 1, 내린 항목 0", up)
        down = g.render_compare(b, a, "b", "a")
        self.assertIn("⚠ 되돌리기 검토", down)


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        import contextlib
        import io
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = g.main(list(args))
        return rc, out.getvalue(), err.getvalue()

    def test_exit_1_when_an_item_has_fewer_than_five(self):
        rc, out, _ = self.run_cli(str(SAMPLE))
        self.assertEqual(rc, 1)
        self.assertIn("5개 미만 1개", out)

    def test_fixed_sample_exits_0(self):
        rc, out, _ = self.run_cli(str(FIXED))
        self.assertEqual(rc, 0)
        self.assertIn("5개 미만 0개", out)

    def test_json_and_missing_file(self):
        rc, out, _ = self.run_cli(str(SAMPLE), "--json")
        self.assertEqual(rc, 0)
        self.assertIn('"rule"', out)
        rc, _, err = self.run_cli("nope.md")
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()

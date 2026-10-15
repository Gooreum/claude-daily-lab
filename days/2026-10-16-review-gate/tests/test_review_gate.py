import argparse, json, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import review_gate as rg  # noqa: E402

FX = HERE / "fixtures"


def gate(name, **kw):
    a = argparse.Namespace(max_important=0, max_nit=None, max_pre_existing=None, trust_title=False, on_no_verdict="fail")
    for k, v in kw.items():
        setattr(a, k, v)
    runs = json.loads((FX / name).read_text())["check_runs"]
    return rg.evaluate(rg.pick_check_run(runs), a)


class GateTests(unittest.TestCase):
    def test_important_fails(self):
        r = gate("important.json")
        self.assertEqual(r["verdict"], "fail")
        self.assertEqual(r["counts"], {"normal": 2, "nit": 1, "pre_existing": 0})

    def test_clean_passes(self):
        self.assertEqual(gate("clean.json")["verdict"], "pass")

    def test_nits_do_not_fail_by_default(self):
        self.assertEqual(gate("nits_only.json")["verdict"], "pass")

    def test_nit_and_pre_existing_limits(self):
        self.assertEqual(gate("nits_only.json", max_nit=3)["verdict"], "fail")
        self.assertEqual(gate("nits_only.json", max_pre_existing=0)["verdict"], "fail")
        self.assertEqual(gate("nits_only.json", max_nit=4, max_pre_existing=1)["verdict"], "pass")

    def test_missing_count_line_is_no_verdict_not_zero(self):
        self.assertEqual(gate("no_line.json")["verdict"], "none")

    def test_title_trusted_only_on_request(self):
        self.assertEqual(gate("no_line_clean_title.json")["verdict"], "none")
        self.assertEqual(gate("no_line_clean_title.json", trust_title=True)["verdict"], "pass")

    def test_in_progress_and_skipped_are_no_verdict(self):
        self.assertEqual(gate("in_progress.json")["verdict"], "none")
        self.assertEqual(gate("skipped.json")["verdict"], "none")

    def test_other_checks_ignored(self):
        self.assertEqual(gate("other_checks_only.json")["verdict"], "none")

    def test_latest_run_wins(self):
        self.assertEqual(gate("rerun.json")["verdict"], "pass")

    def test_malformed_is_no_verdict(self):
        self.assertEqual(gate("malformed.json")["verdict"], "none")

    def test_last_marker_wins(self):
        self.assertEqual(gate("two_lines.json")["verdict"], "pass")


class LintTests(unittest.TestCase):
    GOOD = ("# Review instructions\n## What Important means here\nReserve Important for broken behavior.\n"
            "## Cap the nits\nReport at most five Nits per review.\n## Do not report\n- Generated files\n")

    def ids(self, text):
        return {i[1] for i in rg.lint_text(text)}

    def test_good_file_clean(self):
        self.assertEqual(self.ids(self.GOOD), set())

    def test_missing_pieces(self):
        self.assertEqual(self.ids("Be careful.\n"), {"R010", "R011", "R012"})

    def test_empty_is_error(self):
        self.assertEqual(rg.lint_text("  \n")[0][0], "error")

    def test_general_and_open_ended(self):
        ids = self.ids(self.GOOD + "Run npm install first.\nFlag everything you see.\n")
        self.assertEqual(ids, {"R020", "R021"})

    def test_korean_cap(self):
        self.assertNotIn("R011", self.ids("Important는 장애만.\nnit는 최대 5개.\n생성 파일 제외.\n"))


class LintGitTests(unittest.TestCase):
    def sh(self, *a, cwd):
        subprocess.run(a, cwd=cwd, check=True, capture_output=True)

    def test_base_checks(self):
        with tempfile.TemporaryDirectory() as d:
            self.sh("git", "init", "-q", "-b", "main", cwd=d)
            self.sh("git", "config", "user.email", "t@example.com", cwd=d)
            self.sh("git", "config", "user.name", "t", cwd=d)
            (Path(d) / "REVIEW.md").write_text(LintTests.GOOD)
            self.sh("git", "add", "REVIEW.md", cwd=d)
            self.sh("git", "commit", "-qm", "init", cwd=d)
            self.assertEqual(rg.git_state(d, "main", "REVIEW.md"), (True, True))
            (Path(d) / "REVIEW.md").write_text(LintTests.GOOD + "- more\n")
            self.assertEqual(rg.git_state(d, "main", "REVIEW.md"), (True, False))
            (Path(d) / "new").mkdir()
            (Path(d) / "new" / "REVIEW.md").write_text(LintTests.GOOD)
            self.assertEqual(rg.git_state(d, "main", "new/REVIEW.md"), (False, False))


if __name__ == "__main__":
    unittest.main()

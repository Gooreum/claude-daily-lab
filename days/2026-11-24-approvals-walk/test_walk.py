import json
import os
import subprocess
import sys
import unittest

import approvals_walk as aw

HERE = os.path.dirname(os.path.abspath(__file__))


def policy(name):
    with open(os.path.join(HERE, "samples", name), encoding="utf-8") as f:
        return aw.load_policy(f.read())


class Glob(unittest.TestCase):
    def test_cases(self):
        yes = [("**", "a/b/c.py"), ("src/**", "src/a/b.py"), ("**/.claude/**", ".claude/approvals.yml"),
               ("**/.claude/**", "pkg/.claude/x"), ("*.md", "README.md"), ("**/*.lock", "a/b/yarn.lock"),
               ("**/{package,package-lock}.json", "web/package.json"), ("release/**", "release/1.2")]
        no = [("*.md", "docs/README.md"), ("src/**", "lib/a.py"), ("**/.claude/**", "claude/x"),
              ("**/{package,package-lock}.json", "web/pnpm.json")]
        for p, s in yes:
            self.assertTrue(aw.glob_match(p, s), (p, s))
        for p, s in no:
            self.assertFalse(aw.glob_match(p, s), (p, s))

    def test_exclusion(self):
        self.assertTrue(aw.paths_match(["**", "!docs/**"], "src/a.py"))
        self.assertFalse(aw.paths_match(["**", "!docs/**"], "docs/a.md"))


class Yaml(unittest.TestCase):
    def test_block_and_flow(self):
        doc = aw.parse_yaml('a: 1\nb:\n  - x: "q # not comment"  # comment\n    y: [1, two]\n  - { z: true }\nc:\n- k\n- m\n')
        self.assertEqual(doc, {"a": 1, "b": [{"x": "q # not comment", "y": [1, "two"]}, {"z": True}], "c": ["k", "m"]})

    def test_nested_seats(self):
        doc = aw.parse_yaml('v: { claude: approves, seats: [{ count: 1, from: [humans, "!pr/authors"] }] }')
        self.assertEqual(doc["v"]["seats"][0]["from"], ["humans", "!pr/authors"])

    def test_sample_loads(self):
        for n in ("basic.yml", "layered.yml", "leaky.yml", "gap.yml", "observe.yml"):
            policy(n)


class Validate(unittest.TestCase):
    def test_unknown_key_refused(self):
        with self.assertRaises(aw.PolicyError) as c:
            policy("typo.yml")
        self.assertIn("verdicts", str(c.exception))

    def test_bad_claude_value(self):
        with self.assertRaises(aw.PolicyError):
            aw.load_policy('version: 1\nrules:\n  - purpose: "x"\n    paths: ["**"]\n    verdict: { claude: approve, seats: 1 }\n')

    def test_version_required(self):
        with self.assertRaises(aw.PolicyError):
            aw.load_policy('rules:\n  - purpose: "x"\n    paths: ["**"]\n    verdict: { claude: blocks }\n')


class Walk(unittest.TestCase):
    def run_(self, name, files, review, **kw):
        return aw.walk(policy(name), files, review, **kw)

    def test_basic_pass_fail_none(self):
        p = self.run_("basic.yml", ["src/a.py"], "pass")
        self.assertEqual((p["state"], p["seats"], p["claude_may_approve"]), ("needs", 1, True))
        for r in ("fail", "none", "error", "incomplete"):
            x = self.run_("basic.yml", ["src/a.py"], r)
            self.assertEqual((x["seats"], x["claude_may_approve"]), (2, False), r)

    def test_blocks_until_pass(self):
        self.assertEqual(self.run_("layered.yml", ["services/x.go"], "pass")["seats"], 1)
        for r in ("fail", "none", "error"):
            self.assertEqual(self.run_("layered.yml", ["services/x.go"], r)["state"], "blocked", r)

    def test_docs_excluded_from_broad_rule(self):
        x = self.run_("layered.yml", ["docs/a.md"], "pass")
        self.assertEqual((x["seats"], x["claude_may_approve"]), (0, True))
        y = self.run_("layered.yml", ["docs/a.md"], "none")
        self.assertEqual(y["seats"], 2)

    def test_strictest_wins_across_files(self):
        x = self.run_("layered.yml", ["docs/a.md", "src/b.py"], "pass")
        self.assertEqual((x["state"], x["seats"], x["independent"]), ("needs", 1, True))
        z = self.run_("layered.yml", ["docs/a.md", "src/b.py", "services/c.go"], "fail")
        self.assertEqual(z["state"], "blocked")

    def test_pass_with_open_high_finding_is_blocked(self):
        x = self.run_("layered.yml", ["src/b.py"], "pass", severity="high")
        self.assertEqual(x["state"], "blocked")

    def test_kleene_or_with_missing_result(self):
        # 리뷰 결과가 없어도 severity >= high 가 참이면 OR 전체가 참 → 막힘
        x = self.run_("layered.yml", ["src/b.py"], "none", severity="high")
        self.assertEqual(x["state"], "blocked")
        y = self.run_("layered.yml", ["src/b.py"], "none")
        self.assertEqual((y["state"], y["seats"]), ("needs", 2))

    def test_narrow_rule_asking_less_changes_nothing(self):
        # 문서의 경고: 좁은 규칙이 덜 요구해도 넓은 규칙이 그 경로를 빼기 전에는 바뀌지 않는다
        x = self.run_("leaky.yml", ["docs/a.md"], "pass")
        self.assertEqual((x["seats"], x["claude_may_approve"]), (2, False))
        self.assertEqual([a["rule"] for a in x["files"][0]["rules"]], [1, 2])
        fixed = self.run_("layered.yml", ["docs/a.md"], "pass")
        self.assertEqual((fixed["seats"], fixed["claude_may_approve"]), (0, True))

    def test_size_rule_adds_seats_only_when_true(self):
        files = ["docs/f%d.md" % i for i in range(51)]
        self.assertEqual(self.run_("layered.yml", files, "pass")["seats"], 3)
        self.assertEqual(self.run_("layered.yml", files[:50], "pass")["seats"], 0)

    def test_unreviewed_file_and_neutral(self):
        x = self.run_("gap.yml", ["src/a.py", "docs/x.md"], "pass")
        self.assertEqual(x["unreviewed"], ["docs/x.md"])
        y = self.run_("gap.yml", ["docs/x.md"], "pass")
        self.assertEqual(y["state"], "neutral")

    def test_protected_file_takes_a_person_and_no_claude(self):
        x = self.run_("basic.yml", ["src/a.py", ".claude/approvals.yml"], "pass")
        self.assertEqual(x["seats"], 2)  # 보호 규칙(2명)이 겹쳐 엄격한 쪽이 이긴다
        self.assertFalse(x["claude_may_approve"])
        y = self.run_("gap.yml", [".gitattributes"], "pass")
        self.assertEqual((y["state"], y["seats"]), ("needs", 1))

    def test_observe_decides_nothing(self):
        self.assertEqual(self.run_("observe.yml", ["a.py"], "fail")["state"], "neutral")

    def test_rule_if_without_result_turns_red(self):
        p = aw.load_policy('version: 1\nrules:\n  - purpose: "x"\n    paths: ["**"]\n    if: "claude/code_review = pass"\n    verdict: { claude: comments, seats: 1 }\n')
        self.assertEqual(aw.walk(p, ["a"], "none")["state"], "red")
        self.assertEqual(aw.walk(p, ["a"], "pass")["state"], "needs")
        self.assertEqual(aw.walk(p, ["a"], "fail")["state"], "red")  # 맞는 규칙은 있으나 if가 모두 거짓

    def test_bot_author_override(self):
        p = aw.load_policy('version: 1\nrules:\n  - purpose: "x"\n    paths: ["**"]\n    verdict: { claude: comments, seats: 2 }\n'
                           '    override:\n      - { if: "ALL pr/authors = bot:dependabot AND claude/code_review = pass", verdict: { claude: approves, seats: 0 } }\n')
        self.assertEqual(aw.walk(p, ["a"], "pass", authors=["bot:dependabot"])["seats"], 0)
        self.assertEqual(aw.walk(p, ["a"], "pass", authors=["bot:dependabot", "human"])["seats"], 2)
        self.assertEqual(aw.walk(p, ["a"], "none", authors=["bot:dependabot"])["seats"], 2)

    def test_unsimulated_condition_noted(self):
        p = aw.load_policy('version: 1\nrules:\n  - purpose: "x"\n    paths: ["**"]\n    verdict: { claude: comments, seats: 2 }\n'
                           '    override:\n      - { if: "claude/diff = same_intent", verdict: { claude: approves, seats: 0 } }\n')
        r = aw.walk(p, ["a"], "pass")
        self.assertEqual(r["seats"], 2)
        self.assertTrue(any("시뮬레이션하지 않는" in n for n in r["notes"]))


class Cli(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run([sys.executable, os.path.join(HERE, "approvals_walk.py")] + list(args),
                              capture_output=True, text=True)

    def test_json_all_reviews(self):
        r = self.cli(os.path.join(HERE, "samples", "basic.yml"), "--files", "a.py", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([x["review"] for x in json.loads(r.stdout)], aw.RESULTS)

    def test_strict_exit_codes(self):
        s = os.path.join(HERE, "samples")
        self.assertEqual(self.cli(os.path.join(s, "gap.yml"), "--files", "docs/x.md,src/a.py", "--strict").returncode, 1)
        self.assertEqual(self.cli(os.path.join(s, "basic.yml"), "--files", "a.py", "--strict").returncode, 0)
        self.assertEqual(self.cli(os.path.join(s, "typo.yml"), "--files", "a.py").returncode, 2)
        self.assertEqual(self.cli(os.path.join(s, "basic.yml")).returncode, 2)

    def test_files_from_stdin(self):
        r = subprocess.run([sys.executable, os.path.join(HERE, "approvals_walk.py"), os.path.join(HERE, "samples", "basic.yml"),
                            "--files-from", "-", "--review", "pass"], input="src/a.py\n\nlib/b.py\n", capture_output=True, text=True)
        self.assertIn("파일 2개", r.stdout)
        self.assertIn("승인 1명 필요", r.stdout)


if __name__ == "__main__":
    unittest.main()

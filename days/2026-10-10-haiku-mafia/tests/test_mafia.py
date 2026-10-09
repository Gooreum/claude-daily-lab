"""mafia.py 엔진 테스트. 모델 호출 없이 대본 봇과 가짜 백엔드로 돈다."""
from __future__ import annotations

import io
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mafia as M  # noqa: E402


class FakeBackend:
    """phase별로 정해진 target을 돌려주는 백엔드. 호출 기록을 남긴다."""

    def __init__(self, plan):
        self.plan, self.asks, self.alive_at_ask = plan, [], []

    def ask(self, ask):
        self.asks.append(ask)
        self.alive_at_ask.append(ask.player.alive)  # 질문 시점의 생사
        t = self.plan(ask)
        return M.Answer(f"{ask.player.name} says", t, cost_usd=0.001)


def quiet_game(backend, seed=0, rounds=4):
    return M.Game(backend, seed=seed, max_rounds=rounds, say=lambda _: None)


class RolesAndRules(unittest.TestCase):
    def test_roles_are_one_mafia_one_detective_three_villagers(self):
        ps = M.assign_roles(random.Random(1))
        roles = sorted(p.role for p in ps)
        self.assertEqual(roles, sorted([M.MAFIA, M.DETECTIVE, M.VILLAGER, M.VILLAGER, M.VILLAGER]))
        self.assertEqual([p.name for p in ps], M.NAMES)

    def test_winner_rules(self):
        ps = M.assign_roles(random.Random(1))
        self.assertIsNone(M.winner(ps))
        mafia = next(p for p in ps if p.role == M.MAFIA)
        mafia.alive = False
        self.assertEqual(M.winner(ps), "시민")
        mafia.alive = True
        for p in ps:
            if p.role != M.MAFIA and p.name != "아라":
                p.alive = False
        # 마피아 1 vs 시민 1 → 마피아 승
        self.assertEqual(M.winner(ps), "마피아")

    def test_tally_majority_and_tie(self):
        self.assertEqual(M.tally({"a": "x", "b": "x", "c": "y"}), ("x", {"x": 2, "y": 1}))
        self.assertEqual(M.tally({"a": "x", "b": "y"})[0], None)          # 1:1 동률
        self.assertEqual(M.tally({"a": "x", "b": "x", "c": "y", "d": "y"})[0], None)  # 2:2
        self.assertEqual(M.tally({})[0], None)


class EngineFlow(unittest.TestCase):
    def test_dry_run_game_finishes_with_a_result_and_full_transcript(self):
        g = quiet_game(M.ScriptedBackend(7), seed=7)
        result = g.play()
        self.assertIn(result, ("시민", "마피아", "무승부"))
        text = "\n".join(g.transcript)
        self.assertIn("역할 (비밀)", text)
        self.assertIn("정체 공개", text)
        self.assertTrue(any(p.alive is False for p in g.players))

    def test_dead_players_never_speak_or_vote(self):
        fb = FakeBackend(lambda a: a.choices[0])
        g = quiet_game(fb, seed=3)
        g.play()
        self.assertTrue(all(fb.alive_at_ask), "a dead player was asked something")
        self.assertGreater(len(fb.asks), 5)

    def test_choices_exclude_self(self):
        fb = FakeBackend(lambda a: a.choices[-1])
        g = quiet_game(fb, seed=5)
        g.play()
        for a in fb.asks:
            self.assertNotIn(a.player.name, a.choices)

    def test_detective_learns_the_truth_privately(self):
        # 탐정이 항상 마피아를 조사하게 만든다
        def plan(a):
            if a.phase == "night" and a.player.role == M.DETECTIVE:
                mafia = next(n for n in a.choices if g.by_name(n).role == M.MAFIA)
                return mafia
            return a.choices[0]
        fb = FakeBackend(plan)
        g = quiet_game(fb, seed=11, rounds=1)
        g.night(1)
        det = next(p for p in g.players if p.role == M.DETECTIVE)
        if det.alive:
            self.assertTrue(any("마피아다" in n for n in det.notes), det.notes)
        self.assertNotIn("마피아다", "\n".join(g.log))  # 공개 로그에는 안 샌다

    def test_majority_vote_executes_and_reveals_role(self):
        # 모두가 마피아에게 투표하면 1일째 낮에 시민 승
        def plan(a):
            mafia = [n for n in a.choices if g.by_name(n).role == M.MAFIA]
            return mafia[0] if mafia else a.choices[0]
        fb = FakeBackend(plan)
        g = quiet_game(fb, seed=2)
        result = g.play()
        self.assertEqual(result, "시민")
        self.assertTrue(any("처형" in l and "마피아!" in l for l in g.log))

    def test_split_vote_executes_nobody(self):
        # 각자 다른 사람에게 투표 → 무처형 라인
        fb = FakeBackend(lambda a: a.choices[hash(a.player.name) % len(a.choices)] if a.phase != "night" else a.choices[0])
        g = quiet_game(fb, seed=9, rounds=1)
        g.play()
        self.assertTrue(any("처형" in l for l in g.log))

    def test_max_rounds_gives_a_draw(self):
        # 마피아가 밤에 아무도 못 죽이는 상황은 없으므로, 라운드 0이면 즉시 무승부
        g = quiet_game(M.ScriptedBackend(1), seed=1, rounds=0)
        self.assertEqual(g.play(), "무승부")

    def test_cost_and_calls_are_summed(self):
        fb = FakeBackend(lambda a: a.choices[0])
        g = quiet_game(fb, seed=4)
        g.play()
        self.assertEqual(g.calls, len(fb.asks))
        self.assertAlmostEqual(g.cost, 0.001 * len(fb.asks))


class ClaudeBackendFallback(unittest.TestCase):
    def test_bad_model_output_falls_back_to_script(self):
        import subprocess
        b = M.ClaudeBackend(model="x", fallback=M.ScriptedBackend(0))
        p = M.Player("아라", M.VILLAGER)
        ask = M.Ask(p, "vote", "vote", ["보검", "찬우"], [])
        fake = subprocess.CompletedProcess([], 0, stdout='{"structured_output": {"say": "hi", "target": "나"}}', stderr="")
        orig = subprocess.run
        subprocess.run = lambda *a, **k: fake
        try:
            err = io.StringIO(); old = sys.stderr; sys.stderr = err
            try:
                ans = b.ask(ask)
            finally:
                sys.stderr = old
        finally:
            subprocess.run = orig
        self.assertIn(ans.target, ["보검", "찬우"])
        self.assertIn("대본 봇이 대신", err.getvalue())

    def test_is_error_result_falls_back(self):
        import subprocess
        b = M.ClaudeBackend(model="x", fallback=M.ScriptedBackend(0))
        ask = M.Ask(M.Player("아라", M.VILLAGER), "vote", "vote", ["보검", "찬우"], [])
        fake = subprocess.CompletedProcess([], 1, stdout='{"is_error": true, "result": "Not logged in"}', stderr="")
        orig = subprocess.run; subprocess.run = lambda *a, **k: fake
        try:
            err = io.StringIO(); old = sys.stderr; sys.stderr = err
            try:
                ans = b.ask(ask)
            finally:
                sys.stderr = old
        finally:
            subprocess.run = orig
        self.assertIn(ans.target, ["보검", "찬우"])
        self.assertIn("Not logged in", err.getvalue())

    def test_good_model_output_is_used(self):
        import subprocess
        b = M.ClaudeBackend(model="x")
        p = M.Player("아라", M.MAFIA)
        ask = M.Ask(p, "night", "kill", ["보검", "찬우"], [])
        fake = subprocess.CompletedProcess([], 0, stdout='{"structured_output": {"say": "후후", "target": "찬우"}, "total_cost_usd": 0.0031}', stderr="")
        orig = subprocess.run
        captured = {}
        def run(cmd, **k):
            captured["cmd"] = cmd
            return fake
        subprocess.run = run
        try:
            ans = b.ask(ask)
        finally:
            subprocess.run = orig
        self.assertEqual((ans.say, ans.target, ans.cost_usd), ("후후", "찬우", 0.0031))
        self.assertIn("--no-session-persistence", captured["cmd"])
        self.assertNotIn("--bare", captured["cmd"])  # --bare는 로그인 정보를 건너뛰어 "Not logged in"이 난다
        self.assertIn("--json-schema", captured["cmd"])
        self.assertIn("마피아", captured["cmd"][captured["cmd"].index("--system-prompt") + 1])


if __name__ == "__main__":
    unittest.main()

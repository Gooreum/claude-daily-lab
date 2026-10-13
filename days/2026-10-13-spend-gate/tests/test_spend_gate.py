"""spend_gate.py 단위·CLI 테스트. 키·모델 없이 돈다. 트랜스크립트는 테스트 안에서 만든다."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(HOOKS))
import spend_gate as sg  # noqa: E402

SCRIPT = str(HOOKS / "spend_gate.py")
PRICES = sg.load_prices(str(HOOKS / "prices.json"))


def line(mid, model, inp=0, out=0, read=0, w5=0, w1=0, typ="assistant"):
    usage = {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": read,
             "cache_creation_input_tokens": w5 + w1,
             "cache_creation": {"ephemeral_5m_input_tokens": w5, "ephemeral_1h_input_tokens": w1}}
    return json.dumps({"type": typ, "uuid": f"u-{mid}-{out}", "message": {"id": mid, "model": model, "usage": usage}})


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.env = {**os.environ, "SPEND_GATE_STATE": str(self.tmp / "state"),
                    "SPEND_GATE_CONFIG": str(self.tmp / "cfg.json"), "SPEND_GATE_PRICES": str(HOOKS / "prices.json")}
        self.env.pop("SPEND_GATE_DRY_RUN", None)
        self.env.pop("SPEND_GATE_SESSION_USD", None)
        self.env.pop("SPEND_GATE_DAILY_USD", None)
        self._old = {k: os.environ.get(k) for k in self.env if k.startswith("SPEND_GATE")}
        for k in self._old:
            os.environ[k] = self.env[k]
        for k in ("SPEND_GATE_DRY_RUN", "SPEND_GATE_SESSION_USD", "SPEND_GATE_DAILY_USD"):
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def cfg(self, **kw):
        (self.tmp / "cfg.json").write_text(json.dumps(kw))

    def transcript(self, *lines, name="s1.jsonl"):
        p = self.tmp / name
        p.write_text("\n".join(lines) + "\n")
        return str(p)

    def hook(self, sid, transcript, *args, extra_env=None):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": sid, "transcript_path": transcript}
        return subprocess.run([sys.executable, SCRIPT, "hook", *args], input=json.dumps(payload),
                              capture_output=True, text=True, env={**self.env, **(extra_env or {})})


class CostMath(Base):
    def test_haiku_cost_by_components(self):
        t = self.transcript(line("m1", "claude-haiku-5-5", inp=1_000_000, out=1_000_000, read=1_000_000, w5=1_000_000, w1=1_000_000))
        c = sg.session_cost(t, PRICES)
        self.assertAlmostEqual(c["usd"], 0.10 + 0.50 + 0.01 + 0.125 + 0.20, places=6)

    def test_sonnet_and_opus_rates(self):
        t = self.transcript(line("a", "claude-sonnet-5-5", out=1_000_000), line("b", "claude-opus-5-5", out=1_000_000))
        c = sg.session_cost(t, PRICES)
        self.assertAlmostEqual(c["by_model"]["claude-sonnet-5-5"], 10.0)
        self.assertAlmostEqual(c["by_model"]["claude-opus-5-5"], 20.0)

    def test_duplicate_lines_of_one_message_count_once(self):
        # 같은 message.id가 content 블록마다 여러 줄로 기록된다. 출력 토큰은 최종값(최대)만 센다.
        t = self.transcript(line("m", "claude-sonnet-5-5", out=100), line("m", "claude-sonnet-5-5", out=100), line("m", "claude-sonnet-5-5", out=500))
        c = sg.session_cost(t, PRICES)
        self.assertEqual(c["messages"], 1)
        self.assertAlmostEqual(c["usd"], 500 * 10 / 1e6, places=9)

    def test_unknown_model_uses_fallback_and_is_flagged(self):
        t = self.transcript(line("m", "claude-mystery-9", out=1_000_000))
        c = sg.session_cost(t, PRICES)
        self.assertAlmostEqual(c["usd"], 20.0)
        self.assertEqual(c["unknown_models"], ["claude-mystery-9"])

    def test_longest_prefix_and_1m_suffix(self):
        r, known = sg.rates_for("claude-haiku-5-5[1m]", PRICES)
        self.assertTrue(known)
        self.assertEqual(r["input"], 0.10)
        r, known = sg.rates_for("claude-haiku-5-5-20261007", PRICES)
        self.assertTrue(known)

    def test_write_without_ttl_split_is_priced_as_5m(self):
        rec = {"model": "claude-sonnet-5-5", "u": {"cache_creation_input_tokens": 1_000_000}, "w5": 0, "w1": 0}
        usd, _ = sg.message_cost(rec, PRICES)
        self.assertAlmostEqual(usd, 2.50)

    def test_ignores_garbage_synthetic_and_non_assistant(self):
        t = self.transcript("not json", "{", line("x", "<synthetic>", out=10**9), line("y", "claude-opus-5-5", out=10**9, typ="user"),
                            line("z", "claude-haiku-5-5", out=1_000_000))
        c = sg.session_cost(t, PRICES)
        self.assertEqual(c["messages"], 1)
        self.assertAlmostEqual(c["usd"], 0.5)

    def test_subagent_transcripts_are_included(self):
        main = self.transcript(line("m", "claude-haiku-5-5", out=1_000_000))
        sub = self.tmp / "s1" / "subagents"
        sub.mkdir(parents=True)
        (sub / "agent-1.jsonl").write_text(line("sa", "claude-opus-5-5", out=1_000_000) + "\n")
        c = sg.session_cost(main, PRICES)
        self.assertAlmostEqual(c["usd"], 20.5)

    def test_missing_transcript_costs_zero(self):
        self.assertEqual(sg.session_cost(str(self.tmp / "nope.jsonl"), PRICES)["usd"], 0.0)
        self.assertEqual(sg.session_cost(None, PRICES)["usd"], 0.0)


class HookBehaviour(Base):
    def test_under_cap_passes_silently(self):
        self.cfg(session_usd=5, daily_usd=20, warn_ratio=0.8)
        r = self.hook("s1", self.transcript(line("m", "claude-haiku-5-5", out=1000)))
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_session_cap_blocks_with_exit_2_and_reason(self):
        self.cfg(session_usd=1, daily_usd=100)
        r = self.hook("s1", self.transcript(line("m", "claude-sonnet-5-5", out=200_000)))  # $2
        self.assertEqual(r.returncode, 2)
        self.assertIn("세션 $2.0000 ≥ 상한 $1.00", r.stderr)
        self.assertIn("사용자에게 보고", r.stderr)

    def test_daily_cap_sums_sessions(self):
        self.cfg(session_usd=100, daily_usd=3)
        a = self.hook("A", self.transcript(line("a", "claude-sonnet-5-5", out=200_000), name="a.jsonl"))  # $2
        self.assertEqual(a.returncode, 0)
        b = self.hook("B", self.transcript(line("b", "claude-sonnet-5-5", out=150_000), name="b.jsonl"))  # $1.5 → 합 3.5
        self.assertEqual(b.returncode, 2)
        self.assertIn("오늘 합계 $3.5000 ≥ 상한 $3.00", b.stderr)

    def test_session_cost_is_set_not_added_across_calls(self):
        self.cfg(session_usd=100, daily_usd=3)
        t = self.transcript(line("a", "claude-sonnet-5-5", out=200_000))  # $2
        for _ in range(3):  # 같은 세션이 도구를 여러 번 불러도 합계가 불지 않는다
            self.assertEqual(self.hook("A", t).returncode, 0)

    def test_warns_once_at_ratio_via_systemMessage(self):
        self.cfg(session_usd=10, daily_usd=100, warn_ratio=0.8)
        t = self.transcript(line("a", "claude-sonnet-5-5", out=850_000))  # $8.5 = 85%
        r = self.hook("A", t)
        self.assertEqual(r.returncode, 0)
        self.assertIn("systemMessage", json.loads(r.stdout))
        self.assertIn("85%", r.stdout)
        self.assertEqual(self.hook("A", t).stdout, "")  # 두 번째는 조용

    def test_env_overrides_config(self):
        self.cfg(session_usd=100, daily_usd=100)
        t = self.transcript(line("a", "claude-sonnet-5-5", out=200_000))
        r = self.hook("A", t, extra_env={"SPEND_GATE_SESSION_USD": "0.5"})
        self.assertEqual(r.returncode, 2)

    def test_dry_run_never_blocks_and_does_not_write_ledger(self):
        self.cfg(session_usd=0.01, daily_usd=100)
        t = self.transcript(line("a", "claude-sonnet-5-5", out=200_000))
        r = self.hook("A", t, "--dry-run")
        self.assertEqual(r.returncode, 0)
        self.assertIn("[dry-run] 막았을 것", r.stderr)
        self.assertFalse((self.tmp / "state" / "ledger.json").exists())
        r = self.hook("A", t, extra_env={"SPEND_GATE_DRY_RUN": "1"})
        self.assertEqual(r.returncode, 0)

    def test_bad_stdin_is_hook_failure_exit_1(self):
        r = subprocess.run([sys.executable, SCRIPT], input="not json", capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 1)
        r = subprocess.run([sys.executable, SCRIPT], input="[1]", capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 1)

    def test_broken_config_prices_and_ledger_are_exit_1(self):
        t = self.transcript(line("a", "claude-haiku-5-5", out=1))
        (self.tmp / "cfg.json").write_text("{oops")
        self.assertEqual(self.hook("A", t).returncode, 1)
        self.cfg(session_usd=-1)
        self.assertEqual(self.hook("A", t).returncode, 1)
        self.cfg(session_usd=5)
        (self.tmp / "p.json").write_text("{}")
        self.assertEqual(self.hook("A", t, extra_env={"SPEND_GATE_PRICES": str(self.tmp / "p.json")}).returncode, 1)
        self.assertEqual(self.hook("A", t, extra_env={"SPEND_GATE_PRICES": str(self.tmp / "missing.json")}).returncode, 1)
        (self.tmp / "state").mkdir(exist_ok=True)
        (self.tmp / "state" / "ledger.json").write_text("garbage")
        self.assertEqual(self.hook("A", t).returncode, 1)

    def test_non_numeric_env_cap_is_exit_1(self):
        self.cfg(session_usd=5)
        r = self.hook("A", self.transcript(line("a", "claude-haiku-5-5", out=1)), extra_env={"SPEND_GATE_SESSION_USD": "abc"})
        self.assertEqual(r.returncode, 1)

    def test_missing_transcript_path_passes(self):
        self.cfg(session_usd=5)
        r = self.hook("A", None)
        self.assertEqual(r.returncode, 0)

    def test_new_day_resets_ledger(self):
        self.cfg(session_usd=100, daily_usd=3)
        self.assertEqual(self.hook("A", self.transcript(line("a", "claude-sonnet-5-5", out=200_000), name="a.jsonl")).returncode, 0)
        lp = self.tmp / "state" / "ledger.json"
        d = json.loads(lp.read_text())
        d["date"] = "2000-01-01"
        d["sessions"]["OLD"] = 999.0
        lp.write_text(json.dumps(d))
        r = self.hook("B", self.transcript(line("b", "claude-sonnet-5-5", out=150_000), name="b.jsonl"))
        self.assertEqual(r.returncode, 0, r.stderr)  # 어제 999달러는 오늘 합계에 없다
        self.assertNotIn("OLD", json.loads(lp.read_text())["sessions"])


class RaiseAndStatus(Base):
    def test_raise_session_unblocks_that_session_only(self):
        self.cfg(session_usd=1, daily_usd=100)
        ta = self.transcript(line("a", "claude-sonnet-5-5", out=200_000), name="a.jsonl")  # $2
        tb = self.transcript(line("b", "claude-sonnet-5-5", out=200_000), name="b.jsonl")
        self.assertEqual(self.hook("A", ta).returncode, 2)
        r = subprocess.run([sys.executable, SCRIPT, "raise", "--usd", "5", "--session-id", "A"], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.hook("A", ta).returncode, 0)
        self.assertEqual(self.hook("B", tb).returncode, 2)

    def test_raise_defaults_to_last_session_and_daily_scope(self):
        self.cfg(session_usd=1, daily_usd=2.5)
        t = self.transcript(line("a", "claude-sonnet-5-5", out=300_000))  # $3 → 세션·일 모두 초과
        self.assertEqual(self.hook("A", t).returncode, 2)
        run = lambda *a: subprocess.run([sys.executable, SCRIPT, "raise", *a], capture_output=True, text=True, env=self.env)
        self.assertEqual(run("--usd", "5").returncode, 0)                       # 마지막 세션 A
        self.assertEqual(self.hook("A", t).returncode, 2)                        # 일 상한이 남아 아직 막힌다
        self.assertEqual(run("--usd", "1", "--scope", "daily").returncode, 0)
        self.assertEqual(self.hook("A", t).returncode, 0)

    def test_raise_rejects_nonpositive_and_unknown_session(self):
        run = lambda *a: subprocess.run([sys.executable, SCRIPT, "raise", *a], capture_output=True, text=True, env=self.env)
        self.assertEqual(run("--usd", "0").returncode, 1)
        self.assertEqual(run("--usd", "1").returncode, 1)  # 장부가 비어 마지막 세션을 모른다

    def test_status_lists_sessions(self):
        self.cfg(session_usd=5, daily_usd=20)
        self.hook("sess-abcdef-123", self.transcript(line("a", "claude-sonnet-5-5", out=100_000)))
        r = subprocess.run([sys.executable, SCRIPT, "status"], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0)
        self.assertIn("오늘 $1.0000 / 상한 $20.00", r.stdout)
        self.assertIn("sess-abcdef-", r.stdout)

    def test_cost_command_prints_table(self):
        t = self.transcript(line("a", "claude-sonnet-5-5", out=100_000), line("b", "claude-mystery", out=1000))
        r = subprocess.run([sys.executable, SCRIPT, "cost", t], capture_output=True, text=True, env=self.env)
        self.assertIn("claude-sonnet-5-5", r.stdout)
        self.assertIn("(fallback 단가)", r.stdout)

    def test_parallel_sessions_do_not_corrupt_ledger(self):
        self.cfg(session_usd=100, daily_usd=1000)
        procs = []
        for i in range(8):
            t = self.transcript(line(f"m{i}", "claude-haiku-5-5", out=1_000_000), name=f"p{i}.jsonl")
            payload = json.dumps({"session_id": f"S{i}", "transcript_path": t})
            p = subprocess.Popen([sys.executable, SCRIPT, "hook"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, env=self.env)
            p.stdin.write(payload)
            p.stdin.close()
            procs.append(p)
        codes = []
        for p in procs:
            p.stdout.close()
            p.stderr.close()
            codes.append(p.wait())
        self.assertEqual(codes, [0] * 8)
        d = json.loads((self.tmp / "state" / "ledger.json").read_text())
        self.assertEqual(sorted(d["sessions"]), [f"S{i}" for i in range(8)])


if __name__ == "__main__":
    unittest.main()

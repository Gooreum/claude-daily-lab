import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "session_bulkhead.py"
sys.path.insert(0, str(HOOK.parent))
import session_bulkhead as sb  # noqa: E402

T = 1_000_000.0
CFG = dict(sb.DEFAULTS)


def sess(sid, top="/w/a", ports=None, heavy_ago=None, age=0):
    return sb.Session(sid=sid, cwd=top, toplevel=top, ts=T - age,
                      ports={p: T - age for p in (ports or [])},
                      heavy_ts=(T - heavy_ago) if heavy_ago is not None else 0.0)


def ev(cmd, others=(), me_top="/w/me", cfg=None, mem="8000", listening=None):
    env = {"SESSION_BULKHEAD_MEM_MB": mem}
    if listening is not None:
        env["SESSION_BULKHEAD_LISTENING"] = listening
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        me = sb.Session(sid="me-session", cwd=me_top, toplevel=me_top, ts=T)
        vs, ports, heavy = sb.evaluate(cmd, me, list(others), cfg or CFG, T)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return vs, ports, heavy


def rules(cmd, **kw):
    return sorted({v.rule for v in ev(cmd, **kw)[0]})


class NameKill(unittest.TestCase):
    others = [sess("other-1")]

    def test_blocked_when_other_session_alive(self):
        for c in ["pkill node", "pkill -f vite", "killall node", "sudo pkill -9 node",
                  "taskkill /F /IM node.exe", "kill $(pgrep -f next)", "kill `pidof node`",
                  "ps aux | grep node | awk '{print $2}' | xargs kill -9", "cd x && pkill node; echo done"]:
            self.assertEqual(rules(c, others=self.others), ["name-kill"], c)

    def test_allowed_alone(self):
        self.assertEqual(rules("pkill node"), [])

    def test_strict_blocks_alone(self):
        os.environ["SESSION_BULKHEAD_STRICT"] = "1"
        try:
            self.assertEqual(rules("pkill node"), ["name-kill"])
        finally:
            del os.environ["SESSION_BULKHEAD_STRICT"]

    def test_pid_based_kill_allowed(self):
        for c in ["kill 1234", "kill -9 $!", "taskkill /PID 4242 /F", "npm run dev & echo $!", "pgrep node"]:
            self.assertEqual(rules(c, others=self.others), [], c)

    def test_pkill_scoped_to_own_tree_allowed(self):
        self.assertEqual(rules("pkill -f /w/me/node_modules/.bin/vite", others=self.others), [])
        self.assertEqual(rules("pkill -f /w/other/node_modules/.bin/vite", others=self.others), ["name-kill"])

    def test_message_names_alternative(self):
        msg = ev("pkill node", others=self.others)[0][0].message
        self.assertIn("kill <pid>", msg)
        self.assertIn("1개", msg)


class Ports(unittest.TestCase):
    others = [sess("other-1", ports=["3000", "5173"])]

    def test_taken_port_blocked(self):
        for c in ["npm run dev -- --port 3000", "PORT=3000 npm start", "vite --port=5173",
                  "python3 -m http.server 3000", "python manage.py runserver 0.0.0.0:3000",
                  "docker run -p 3000:80 nginx", "next dev -p 3000"]:
            self.assertEqual(rules(c, others=self.others), ["port"], c)

    def test_free_port_ok_and_claimed(self):
        vs, ports, _ = ev("npm run dev -- --port 3001", others=self.others)
        self.assertEqual(vs, [])
        self.assertEqual(ports, {"3001"})

    def test_clients_do_not_claim_or_conflict(self):
        for c in ["curl localhost:3000/health", "lsof -i :3000", "ss -ltn | grep :3000", "ssh -p 3000 host", "wget http://127.0.0.1:3000"]:
            vs, ports, _ = ev(c, others=self.others)
            self.assertEqual((vs, ports), ([], set()), c)

    def test_kill_by_port_of_other_session_blocked(self):
        for c in ["lsof -ti:3000 | xargs kill -9", "kill $(lsof -t -i :3000)", "fuser -k 3000/tcp"]:
            self.assertEqual(rules(c, others=self.others), ["port"], c)

    def test_kill_by_own_or_unclaimed_port_ok(self):
        self.assertEqual(rules("lsof -ti:4000 | xargs kill", others=self.others), [])

    def test_hint_skips_used_ports(self):
        msg = ev("vite --port 5173", others=self.others)[0][0].message
        self.assertIn("5174", msg)

    def test_stale_claim_not_listening_ignored(self):
        old = [sess("other-1", ports=["3000"], age=600)]
        self.assertEqual(rules("vite --port 3000", others=old, listening=""), [])

    def test_old_claim_still_listening_blocks(self):
        old = [sess("other-1", ports=["3000"], age=600)]
        self.assertEqual(rules("vite --port 3000", others=old, listening="3000"), ["port"])

    def test_fresh_claim_blocks_even_if_not_yet_listening(self):
        fresh = [sess("other-1", ports=["3000"], age=5)]
        self.assertEqual(rules("vite --port 3000", others=fresh, listening=""), ["port"])

    def test_privileged_ports_ignored(self):
        self.assertEqual(ev("ssh -p 22 host")[1], set())


class Heavy(unittest.TestCase):
    def test_too_many_concurrent_builds(self):
        others = [sess("o1", heavy_ago=30), sess("o2", "/w/b", heavy_ago=60)]
        for c in ["npm run build", "pnpm test", "cargo build --release", "pytest -q", "make -j8", "docker build .", "npx tsc --noEmit"]:
            self.assertEqual(rules(c, others=others), ["heavy"], c)

    def test_one_other_build_is_fine(self):
        self.assertEqual(rules("npm run build", others=[sess("o1", heavy_ago=30)]), [])

    def test_old_builds_do_not_count(self):
        others = [sess("o1", heavy_ago=500), sess("o2", "/w/b", heavy_ago=900)]
        self.assertEqual(rules("npm run build", others=others), [])

    def test_low_memory_blocks_even_alone(self):
        self.assertEqual(rules("npm test", mem="300"), ["heavy"])
        self.assertEqual(rules("npm test", mem="4000"), [])

    def test_light_commands_never_blocked(self):
        self.assertEqual(rules("ls -la && git status", mem="100", others=[sess("o1", heavy_ago=1), sess("o2", "/w/b", heavy_ago=1)]), [])

    def test_max_heavy_configurable(self):
        cfg = dict(CFG, max_heavy=1)
        self.assertEqual(rules("npm run build", others=[sess("o1", heavy_ago=10)], cfg=cfg), ["heavy"])


class SharedGit(unittest.TestCase):
    same = [sess("o1", top="/w/me")]

    def test_mutating_git_in_shared_tree_blocked(self):
        for c in ["git checkout main", "git checkout -b feat", "git switch dev", "git reset --hard HEAD~1", "git clean -fd",
                  "git stash", "git stash pop", "git restore .", "git rebase main", "git pull", "git merge dev"]:
            self.assertEqual(rules(c, others=self.same), ["shared-git"], c)

    def test_read_only_and_soft_ok(self):
        for c in ["git status", "git diff", "git log --oneline", "git reset --soft HEAD~1", "git reset HEAD file",
                  "git stash list", "git stash show", "git clean -n", "git commit -m x", "git add -A"]:
            self.assertEqual(rules(c, others=self.same), [], c)

    def test_separate_worktree_ok(self):
        self.assertEqual(rules("git checkout main", others=[sess("o1", top="/w/other")]), [])

    def test_dash_C_targets_other_tree(self):
        others = [sess("o1", top="/w/other")]
        self.assertEqual(rules("git -C /w/other checkout main", others=others), ["shared-git"])
        self.assertEqual(rules("git -C /w/other status", others=others), [])

    def test_alone_ok(self):
        self.assertEqual(rules("git checkout main"), [])


class Misc(unittest.TestCase):
    def test_disable_rule(self):
        cfg = dict(CFG, disable=["name-kill"])
        self.assertEqual(rules("pkill node", others=[sess("o1")], cfg=cfg), [])

    def test_multiple_violations_reported_together(self):
        others = [sess("o1", top="/w/me", ports=["3000"])]
        self.assertEqual(rules("pkill node && git checkout main && vite --port 3000", others=others),
                         ["name-kill", "port", "shared-git"])

    def test_env_prefix_does_not_hide_command(self):
        self.assertEqual(rules("FOO=1 sudo nohup pkill node", others=[sess("o1")]), ["name-kill"])


class HookProcess(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state"
        self.tree = Path(self.tmp.name) / "repo"
        (self.tree / ".git").mkdir(parents=True)
        self.env = dict(os.environ, SESSION_BULKHEAD_STATE=str(self.state), SESSION_BULKHEAD_MEM_MB="8000",
                        SESSION_BULKHEAD_CONFIG=str(Path(self.tmp.name) / "none.json"))
        for k in ("SESSION_BULKHEAD_DRY_RUN", "SESSION_BULKHEAD_STRICT", "SESSION_BULKHEAD_NOW", "SESSION_BULKHEAD_DISABLE"):
            self.env.pop(k, None)

    def tearDown(self):
        self.tmp.cleanup()

    def hook(self, sid, cmd, tool="Bash", cwd=None, mode="hook", env=None, raw=None):
        payload = raw if raw is not None else json.dumps({"session_id": sid, "cwd": str(cwd or self.tree), "tool_name": tool,
                                                          "hook_event_name": "PreToolUse", "tool_input": {"command": cmd}})
        return subprocess.run([sys.executable, str(HOOK), mode], input=payload, capture_output=True, text=True,
                              env=dict(self.env, **(env or {})))

    def test_two_sessions_end_to_end(self):
        a = self.hook("aaaaaaaa-1", "npm run dev -- --port 3000")
        self.assertEqual(a.returncode, 0, a.stderr)
        b = self.hook("bbbbbbbb-2", "npm run dev -- --port 3000")
        self.assertEqual(b.returncode, 2)
        self.assertIn("[session-bulkhead:port]", b.stderr)
        self.assertIn("aaaaaaaa", b.stderr)
        self.assertEqual(b.stdout, "")
        c = self.hook("bbbbbbbb-2", "pkill node")
        self.assertEqual(c.returncode, 2)
        self.assertIn("name-kill", c.stderr)
        d = self.hook("bbbbbbbb-2", "git checkout main")
        self.assertEqual(d.returncode, 2)
        self.assertIn("shared-git", d.stderr)

    def test_blocked_command_does_not_claim_port(self):
        self.hook("aaaaaaaa-1", "vite --port 3000")
        self.hook("bbbbbbbb-2", "vite --port 3000")
        reg = json.loads((self.state / "bbbbbbbb-2.json").read_text())
        self.assertEqual(reg["ports"], {})

    def test_alone_nothing_blocked_and_registered(self):
        r = self.hook("solo-1", "pkill node")
        self.assertEqual(r.returncode, 0)
        reg = json.loads((self.state / "solo-1.json").read_text())
        self.assertEqual(reg["toplevel"], str(self.tree.resolve()))

    def test_registry_stores_no_command_text(self):
        self.hook("solo-1", "echo SECRET=hunter2 && vite --port 4000")
        self.assertNotIn("hunter2", (self.state / "solo-1.json").read_text())

    def test_non_bash_tool_ignored(self):
        r = self.hook("aaaaaaaa-1", "x", tool="Read")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertFalse(self.state.exists())

    def test_bad_input_is_hook_failure_exit1(self):
        self.assertEqual(self.hook("x", "x", raw="not json").returncode, 1)
        self.assertEqual(self.hook("x", "x", raw=json.dumps({"tool_name": "Bash", "tool_input": {}})).returncode, 1)

    def test_bad_config_is_exit1(self):
        cfg = Path(self.tmp.name) / "bad.json"
        cfg.write_text("{broken")
        r = self.hook("a", "ls", env={"SESSION_BULKHEAD_CONFIG": str(cfg)})
        self.assertEqual(r.returncode, 1)
        self.assertIn("설정", r.stderr)

    def test_dry_run_reports_but_passes(self):
        self.hook("aaaaaaaa-1", "vite --port 3000")
        r = self.hook("bbbbbbbb-2", "vite --port 3000", env={"SESSION_BULKHEAD_DRY_RUN": "1"})
        self.assertEqual(r.returncode, 0)
        self.assertIn("dry-run", r.stderr)
        self.assertIn("port", r.stderr)

    def test_session_end_removes_registry(self):
        self.hook("aaaaaaaa-1", "ls")
        self.assertTrue((self.state / "aaaaaaaa-1.json").exists())
        r = self.hook("aaaaaaaa-1", "", mode="end", raw=json.dumps({"session_id": "aaaaaaaa-1"}))
        self.assertEqual(r.returncode, 0)
        self.assertFalse((self.state / "aaaaaaaa-1.json").exists())
        self.assertEqual(self.hook("bbbbbbbb-2", "pkill node").returncode, 0)

    def test_expired_and_corrupt_registries_ignored(self):
        self.hook("aaaaaaaa-1", "vite --port 3000", env={"SESSION_BULKHEAD_NOW": "1000"})
        (self.state / "junk.json").write_text("{nope")
        r = self.hook("bbbbbbbb-2", "vite --port 3000", env={"SESSION_BULKHEAD_NOW": str(1000 + 7200)})
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_disable_env(self):
        self.hook("aaaaaaaa-1", "ls")
        r = self.hook("bbbbbbbb-2", "pkill node", env={"SESSION_BULKHEAD_DISABLE": "name-kill"})
        self.assertEqual(r.returncode, 0)

    def test_unknown_rule_name_fails_loudly(self):
        r = self.hook("a", "ls", env={"SESSION_BULKHEAD_DISABLE": "nope"})
        self.assertEqual(r.returncode, 1)

    def test_status_and_check(self):
        self.hook("aaaaaaaa-1", "vite --port 3000")
        s = subprocess.run([sys.executable, str(HOOK), "status"], capture_output=True, text=True, env=self.env)
        self.assertIn("aaaaaaaa", s.stdout)
        self.assertIn("3000", s.stdout)
        c = subprocess.run([sys.executable, str(HOOK), "check", "vite --port 3000", "--session-id", "zzz"],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(c.returncode, 2)
        self.assertIn("차단됨", c.stdout)
        self.assertFalse((self.state / "zzz.json").exists())


if __name__ == "__main__":
    unittest.main()

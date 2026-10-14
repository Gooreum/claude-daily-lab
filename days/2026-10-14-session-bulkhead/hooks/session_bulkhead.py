#!/usr/bin/env python3
"""session_bulkhead.py — Claude Code PreToolUse 훅: 한 기기에서 도는 병렬 세션이 서로를 건드리지 못하게 막는다.

세션마다 장부 파일(cwd·git 작업 트리·잡은 포트·최근 무거운 명령 시각)을 남기고, Bash 명령을 실행하기 전에
"다른 살아 있는 세션"의 장부와 대조해 아래 넷을 exit 2로 막는다. 막는 이유는 stderr로 낸다(모델이 읽는 채널).

  name-kill   pkill/killall/taskkill /IM/`kill $(pgrep …)` 같은 이름 기반 종료 (다른 세션의 서버까지 죽는다)
  port        다른 세션이 잡은 포트로 서버를 띄우거나 그 포트의 프로세스를 죽이기
  heavy       빌드·테스트를 동시에 너무 많이 돌리거나 여유 메모리가 모자랄 때 또 빌드 시작
  shared-git  다른 세션이 같이 쓰는 git 작업 트리에서 checkout/switch/reset --hard/clean/stash 등

사용:
  훅 모드(기본)   stdin으로 PreToolUse JSON.  종료 코드 0=통과, 2=차단, 1=훅 실패(onFailure 적용)
  end             SessionEnd 훅. 이 세션의 장부를 지운다
  status          살아 있는 세션 표
  check CMD       장부를 바꾸지 않고 CMD가 막히는지만 본다 (--session-id, --cwd)

환경변수: SESSION_BULKHEAD_STATE(장부 폴더, 기본 ~/.claude/session-bulkhead), SESSION_BULKHEAD_CONFIG,
  SESSION_BULKHEAD_DRY_RUN=1(막지 않고 말만), SESSION_BULKHEAD_STRICT=1(혼자여도 이름 기반 종료 차단),
  SESSION_BULKHEAD_DISABLE=name-kill,port,heavy,shared-git 중 끄고 싶은 규칙,
  SESSION_BULKHEAD_TTL_S, SESSION_BULKHEAD_MAX_HEAVY, SESSION_BULKHEAD_HEAVY_WINDOW_S, SESSION_BULKHEAD_MIN_MEM_MB
  (테스트용: SESSION_BULKHEAD_NOW, SESSION_BULKHEAD_MEM_MB, SESSION_BULKHEAD_LISTENING)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULES = ("name-kill", "port", "heavy", "shared-git")
DEFAULTS = {"ttl_s": 3600, "max_heavy": 2, "heavy_window_s": 120, "min_mem_mb": 1024, "port_grace_s": 120, "disable": []}

WRAPPERS = {"sudo", "env", "nohup", "time", "exec", "command", "setsid", "nice", "stdbuf"}
CLIENTS = {"curl", "wget", "http", "https", "nc", "ncat", "lsof", "ss", "netstat", "ping", "ssh", "telnet",
           "fuser", "kill", "xargs", "grep", "echo", "cat", "pgrep", "ps", "awk", "sed", "head", "tail", "open"}
HEAVY = re.compile(
    r"^(?:(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:build|test|lint|typecheck)\b"
    r"|npx\s+(?:tsc|vitest|jest|webpack|next\s+build|vite\s+build)\b"
    r"|tsc\b|vitest\b|jest\b|pytest\b|py\.test\b|make\b|mvn\s|xcodebuild\b|bazel\s+build\b"
    r"|cargo\s+(?:build|test|check|clippy)\b|go\s+(?:build|test)\b|(?:\./)?gradlew?\s"
    r"|docker\s+(?:compose\s+)?build\b)")
PORT_FORMS = re.compile(
    r"(?:--port(?:=|\s+)|\bPORT=|\bPORT\s*=\s*|(?<![\w/-])-p\s*|runserver\s+|http\.server\s+|(?<![\w.])(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\*)?:)"
    r"(\d{4,5})\b")
GIT_MUTATING = {"checkout", "switch", "restore", "clean", "rebase", "merge", "pull"}


@dataclass
class Violation:
    rule: str
    message: str


@dataclass
class Session:
    sid: str
    cwd: str = ""
    toplevel: str = ""
    ts: float = 0.0
    ports: dict = field(default_factory=dict)  # "3000" -> 클레임 시각
    heavy_ts: float = 0.0


# ── 설정·장부 ───────────────────────────────────────────────────────────────

def now() -> float:
    v = os.environ.get("SESSION_BULKHEAD_NOW")
    return float(v) if v else time.time()


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    p = Path(os.environ.get("SESSION_BULKHEAD_CONFIG") or HERE / "session-bulkhead.json")
    if p.exists():
        try:
            cfg.update(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            raise SystemExit(f"설정 파일을 읽을 수 없다: {p} ({e})")
    for env, key, cast in (("TTL_S", "ttl_s", float), ("MAX_HEAVY", "max_heavy", int),
                           ("HEAVY_WINDOW_S", "heavy_window_s", float), ("MIN_MEM_MB", "min_mem_mb", float)):
        v = os.environ.get("SESSION_BULKHEAD_" + env)
        if v:
            cfg[key] = cast(v)
    if os.environ.get("SESSION_BULKHEAD_DISABLE"):
        cfg["disable"] = list(cfg["disable"]) + [x.strip() for x in os.environ["SESSION_BULKHEAD_DISABLE"].split(",") if x.strip()]
    unknown = set(cfg["disable"]) - set(RULES)
    if unknown:
        raise SystemExit(f"알 수 없는 규칙 이름: {sorted(unknown)} (가능: {', '.join(RULES)})")
    return cfg


def state_dir() -> Path:
    return Path(os.environ.get("SESSION_BULKHEAD_STATE") or Path.home() / ".claude" / "session-bulkhead")


def _fname(sid: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", sid)[:80] + ".json"


def read_sessions(d: Path, ttl: float, t: float) -> list[Session]:
    """살아 있는(ttl 안에 활동한) 세션들. 깨진 파일은 건너뛴다."""
    out = []
    if not d.is_dir():
        return out
    for f in d.glob("*.json"):
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            s = Session(sid=str(raw["sid"]), cwd=raw.get("cwd", ""), toplevel=raw.get("toplevel", ""),
                        ts=float(raw.get("ts", 0)), ports={str(k): float(v) for k, v in raw.get("ports", {}).items()},
                        heavy_ts=float(raw.get("heavy_ts", 0)))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
        if t - s.ts <= ttl:
            out.append(s)
    return out


def write_session(d: Path, s: Session) -> None:
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / (_fname(s.sid) + ".tmp")
    tmp.write_text(json.dumps({"sid": s.sid, "cwd": s.cwd, "toplevel": s.toplevel, "ts": s.ts,
                               "ports": s.ports, "heavy_ts": s.heavy_ts}, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, d / _fname(s.sid))


# ── 시스템 정보 ─────────────────────────────────────────────────────────────

def git_toplevel(path: str) -> str:
    """`.git`(폴더 또는 worktree의 파일)이 있는 가장 가까운 상위 폴더. 없으면 path 자체."""
    p = Path(path or ".").resolve()
    for cand in (p, *p.parents):
        if (cand / ".git").exists():
            return str(cand)
    return str(p)


def available_mem_mb() -> float | None:
    v = os.environ.get("SESSION_BULKHEAD_MEM_MB")
    if v:
        return float(v)
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def listening_ports() -> set[str] | None:
    """지금 LISTEN 중인 포트. /proc이 없으면(macOS) None = 판단 불가."""
    v = os.environ.get("SESSION_BULKHEAD_LISTENING")
    if v is not None:
        return {x.strip() for x in v.split(",") if x.strip()}
    ports, seen = set(), False
    for f in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = Path(f).read_text().splitlines()[1:]
        except OSError:
            continue
        seen = True
        for ln in lines:
            cols = ln.split()
            if len(cols) > 3 and cols[3] == "0A":
                ports.add(str(int(cols[1].rsplit(":", 1)[1], 16)))
    return ports if seen else None


# ── 명령 해석 ───────────────────────────────────────────────────────────────

def segments(cmd: str) -> list[list[str]]:
    """명령을 ;, &&, ||, |, 줄바꿈, $(), 백틱 경계로 잘라 토큰 목록으로. 앞의 VAR=값·sudo 같은 래퍼는 벗기되 PORT는 남긴다."""
    flat = re.sub(r"\$\(|`|\(|\)", ";", cmd)
    out = []
    for seg in re.split(r"&&|\|\||;|\||\n|&(?!>)", flat):
        seg = seg.strip()
        if not seg:
            continue
        try:
            toks = shlex.split(seg)
        except ValueError:
            toks = seg.split()
        env = [t for t in toks[:6] if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t)]
        while toks and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]) or toks[0] in WRAPPERS):
            toks = toks[1:]
        if toks:
            out.append(env + ["\0"] + toks if env else toks)
    return out


def split_env(seg: list[str]) -> tuple[list[str], list[str]]:
    if "\0" in seg:
        i = seg.index("\0")
        return seg[:i], seg[i + 1:]
    return [], seg


def claimed_ports(cmd: str) -> set[str]:
    """이 명령이 서버를 띄우며 잡으려는 포트. curl·lsof 같은 클라이언트·조회 명령은 뺀다."""
    ports: set[str] = set()
    for seg in segments(cmd):
        env, toks = split_env(seg)
        if toks[0] in CLIENTS:
            continue
        text = " ".join(env + toks)
        ports.update(m.group(1) for m in PORT_FORMS.finditer(text))
    return {p for p in ports if 1024 <= int(p) <= 65535}


def kill_by_port_targets(cmd: str) -> set[str]:
    """`lsof -ti:3000 | xargs kill`, `fuser -k 3000/tcp`, `kill $(lsof -t -i :3000)`에서 포트."""
    segs = segments(cmd)
    heads = [split_env(s)[1][0] for s in segs]
    has_kill = any(h == "kill" or (h == "xargs" and "kill" in s) for h, s in zip(heads, segs))
    out: set[str] = set()
    for s in segs:
        toks = split_env(s)[1]
        text = " ".join(toks)
        if toks[0] == "lsof" and has_kill:
            out.update(re.findall(r":(\d{2,5})\b", text))
        if toks[0] == "fuser" and any(t.startswith("-") and "k" in t for t in toks[1:]):
            out.update(re.findall(r"\b(\d{2,5})(?:/tcp|/udp)?\b", " ".join(toks[1:])))
    return {p for p in out if 1024 <= int(p) <= 65535}


def name_kill(cmd: str, own_top: str) -> str | None:
    """이름·패턴으로 프로세스를 죽이는 명령이면 그 설명. 자기 작업 트리 경로를 패턴에 넣은 pkill -f는 허용."""
    segs = [split_env(s)[1] for s in segments(cmd)]
    heads = [t[0] for t in segs]
    for toks in segs:
        h = toks[0]
        if h in ("killall", "killall5"):
            return f"{h} {' '.join(toks[1:])}".strip()
        if h == "pkill":
            args = [t for t in toks[1:] if not t.startswith("-")]
            if own_top and any(own_top in a for a in args):
                continue
            return f"pkill {' '.join(toks[1:])}".strip()
        if h.lower() in ("taskkill", "taskkill.exe") and any(t.lower() == "/im" for t in toks[1:]):
            return f"taskkill {' '.join(toks[1:])}".strip()
    kills = any(h == "kill" or (h == "xargs" and "kill" in t) for h, t in zip(heads, segs))
    finders = [t for t in segs if t[0] in ("pgrep", "pidof") or (t[0] == "ps")]
    if kills and finders:
        return "이름으로 찾은 PID를 kill (" + " ".join(finders[0][:3]) + " …)"
    return None


def git_ops(cmd: str, cwd: str) -> list[tuple[str, str]]:
    """작업 트리를 바꾸는 git 명령: [(설명, 대상 작업 트리 최상위)]"""
    out = []
    for seg in segments(cmd):
        toks = split_env(seg)[1]
        if toks[0] != "git":
            continue
        target, i, sub = cwd, 1, None
        while i < len(toks):
            t = toks[i]
            if t == "-C" and i + 1 < len(toks):
                target = toks[i + 1] if os.path.isabs(toks[i + 1]) else os.path.join(target, toks[i + 1])
                i += 2
            elif t in ("-c", "--git-dir", "--work-tree", "--namespace") and i + 1 < len(toks):
                i += 2
            elif t.startswith("-"):
                i += 1
            else:
                sub = t
                break
        if sub is None:
            continue
        rest = toks[i + 1:]
        hit = False
        if sub in GIT_MUTATING:
            hit = not (sub == "clean" and any(r in ("-n", "--dry-run") for r in rest))
        elif sub == "reset":
            hit = any(r in ("--hard", "--merge", "--keep") for r in rest)
        elif sub == "stash":
            hit = not (rest and rest[0] in ("list", "show"))
        if hit:
            out.append((f"git {sub}", git_toplevel(target)))
    return out


def is_heavy(cmd: str) -> bool:
    return any(HEAVY.match(" ".join(split_env(s)[1])) for s in segments(cmd))


# ── 판정 ────────────────────────────────────────────────────────────────────

def evaluate(cmd: str, me: Session, others: list[Session], cfg: dict, t: float) -> tuple[list[Violation], set[str], bool]:
    """(위반 목록, 이 명령이 새로 잡는 포트, 이 명령이 무거운가)"""
    off = set(cfg["disable"])
    vs: list[Violation] = []
    ports = claimed_ports(cmd)
    heavy = is_heavy(cmd)
    live_ports = None

    def owner_of(port: str) -> Session | None:
        nonlocal live_ports
        for o in others:
            if port in o.ports:
                if t - o.ports[port] > cfg["port_grace_s"]:
                    if live_ports is None:
                        live_ports = listening_ports()
                    if live_ports is not None and port not in live_ports:
                        continue  # 오래전에 잡았는데 지금은 아무도 안 듣는다 = 죽은 서버
                return o
        return None

    if "name-kill" not in off:
        what = name_kill(cmd, me.toplevel)
        if what and (others or os.environ.get("SESSION_BULKHEAD_STRICT") == "1"):
            n = len(others)
            vs.append(Violation("name-kill", (
                f"이름 기반 프로세스 종료는 막혀 있다: `{what}`. 지금 이 기기에 다른 Claude Code 세션이 {n}개 살아 있어서 "
                "그 세션의 개발 서버·테스트까지 함께 죽는다. 내가 직접 띄운 프로세스의 PID(`$!`나 `echo $!`로 적어 둔 값)로 "
                "`kill <pid>`를 쓰거나, 패턴에 이 작업 트리 절대경로를 넣어 범위를 좁혀라.")))
    if "port" not in off:
        for p in sorted(ports | kill_by_port_targets(cmd)):
            o = owner_of(p)
            if o:
                vs.append(Violation("port", (
                    f"포트 {p}은 다른 세션({o.sid[:8]}, {o.cwd or '?'})이 쓰는 중이다. 다른 포트(예: {_free_hint(p, others)})로 "
                    "띄우거나, 그 포트의 프로세스는 건드리지 마라.")))
    if "heavy" not in off and heavy:
        recent = [o for o in others if t - o.heavy_ts <= cfg["heavy_window_s"]]
        mem = available_mem_mb()
        if len(recent) >= cfg["max_heavy"]:
            vs.append(Violation("heavy", (
                f"다른 세션 {len(recent)}개가 최근 {int(cfg['heavy_window_s'])}초 안에 빌드·테스트를 시작했다(동시 상한 {cfg['max_heavy']}). "
                "메모리 고갈을 막으려고 잠시 뒤에 다시 시도하라.")))
        elif mem is not None and mem < cfg["min_mem_mb"]:
            vs.append(Violation("heavy", (
                f"여유 메모리가 {mem:.0f}MB로 기준 {cfg['min_mem_mb']:.0f}MB보다 적다. 빌드·테스트를 시작하면 기기가 멈출 수 있다. "
                "다른 세션의 작업이 끝난 뒤 다시 시도하라.")))
    if "shared-git" not in off:
        for desc, top in git_ops(cmd, me.cwd):
            o = next((o for o in others if o.toplevel and o.toplevel == top), None)
            if o:
                vs.append(Violation("shared-git", (
                    f"`{desc}`는 작업 트리({top})의 파일과 HEAD를 바꾼다. 이 트리를 다른 세션({o.sid[:8]})도 쓰고 있어 "
                    "그 세션의 작업이 뒤엉킨다. `git worktree add ../<이름> -b <브랜치>`로 따로 작업 트리를 만들어 거기서 하라.")))
    return vs, ports, heavy


def _free_hint(port: str, others: list[Session]) -> str:
    used = {p for o in others for p in o.ports}
    n = int(port)
    for k in range(1, 50):
        if str(n + k) not in used:
            return str(n + k)
    return str(n + 50)


# ── 진입점 ──────────────────────────────────────────────────────────────────

def run_hook(payload: dict, d: Path, cfg: dict) -> int:
    if payload.get("tool_name") != "Bash":
        return 0
    cmd = (payload.get("tool_input") or {}).get("command")
    sid = payload.get("session_id")
    if not isinstance(cmd, str) or not sid:
        raise ValueError("tool_input.command 또는 session_id가 없다")
    cwd = payload.get("cwd") or os.getcwd()
    t = now()
    live = read_sessions(d, cfg["ttl_s"], t)
    others = [s for s in live if s.sid != sid]
    prev = next((s for s in live if s.sid == sid), None)
    me = Session(sid=str(sid), cwd=cwd, toplevel=git_toplevel(cwd), ts=t,
                 ports=dict(prev.ports) if prev else {}, heavy_ts=prev.heavy_ts if prev else 0.0)
    vs, ports, heavy = evaluate(cmd, me, others, cfg, t)
    dry = os.environ.get("SESSION_BULKHEAD_DRY_RUN") == "1"
    if not vs or dry:  # 차단된 명령은 포트도 무거운 일도 "잡지" 않는다
        me.ports = {p: ts for p, ts in me.ports.items() if t - ts <= cfg["ttl_s"]}
        me.ports.update({p: t for p in ports})
        if heavy:
            me.heavy_ts = t
    write_session(d, me)
    if vs:
        msg = "\n".join(f"[session-bulkhead:{v.rule}] {v.message}" for v in vs)
        if dry:
            sys.stderr.write("[dry-run, 막지 않음]\n" + msg + "\n")
            return 0
        sys.stderr.write(msg + "\n")
        return 2
    return 0


def cmd_status(d: Path, cfg: dict) -> int:
    t = now()
    live = sorted(read_sessions(d, cfg["ttl_s"], t), key=lambda s: -s.ts)
    if not live:
        print("살아 있는 세션 없음")
        return 0
    print(f"{'세션':<10}{'마지막 활동':>10}  {'작업 트리':<40} 포트")
    for s in live:
        print(f"{s.sid[:8]:<10}{int(t - s.ts):>8}초  {s.toplevel[-40:]:<40} {','.join(sorted(s.ports)) or '-'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="병렬 Claude Code 세션 충돌 방지 훅")
    ap.add_argument("mode", nargs="?", default="hook", choices=("hook", "end", "status", "check"))
    ap.add_argument("command", nargs="?", help="check 모드에서 검사할 셸 명령")
    ap.add_argument("--session-id", default="check-session")
    ap.add_argument("--cwd", default=os.getcwd())
    a = ap.parse_args(argv)
    d = state_dir()
    if a.mode == "hook":
        try:
            return run_hook(json.load(sys.stdin), d, load_config())
        except SystemExit as e:
            sys.stderr.write(f"session-bulkhead 설정 오류: {e}\n")
            return 1
        except Exception as e:  # noqa: BLE001 — 훅 실패는 exit 1 (settings의 onFailure가 처리)
            sys.stderr.write(f"session-bulkhead 훅 실패: {type(e).__name__}: {e}\n")
            return 1
    if a.mode == "end":
        try:
            sid = json.load(sys.stdin).get("session_id")
        except ValueError:
            sid = None
        if sid:
            (d / _fname(str(sid))).unlink(missing_ok=True)
        return 0
    cfg = load_config()
    if a.mode == "status":
        return cmd_status(d, cfg)
    if not a.command:
        ap.error("check에는 검사할 명령이 필요하다")
    t = now()
    others = [s for s in read_sessions(d, cfg["ttl_s"], t) if s.sid != a.session_id]
    me = Session(sid=a.session_id, cwd=a.cwd, toplevel=git_toplevel(a.cwd), ts=t)
    vs, _, _ = evaluate(a.command, me, others, cfg, t)
    for v in vs:
        print(f"[{v.rule}] {v.message}")
    print("차단됨" if vs else "통과")
    return 2 if vs else 0


if __name__ == "__main__":
    sys.exit(main())

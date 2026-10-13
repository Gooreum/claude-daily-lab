#!/usr/bin/env python3
"""spend_gate.py — Claude Code PreToolUse 훅: 트랜스크립트 usage로 비용을 추정해 세션·일 상한을 넘으면 도구 호출을 막는다.

Claude Code에는 내장 금액 상한이 없다. 이 훅은 세션 트랜스크립트(jsonl)의 토큰 사용량에 단가표를 곱해
세션 비용과 오늘 비용(이 훅을 거친 모든 세션의 합)을 추정하고, 상한을 넘으면 exit 2로 막는다.

사용:
  훅 모드(기본)   stdin으로 PreToolUse JSON을 받는다.   종료 코드 0=통과, 2=차단, 1=훅 실패(onFailure 적용)
  cost FILE...    트랜스크립트의 모델별 비용 표
  status          오늘 장부(세션별 비용·상한)
  raise --usd N   상한을 올린다(--scope session|daily, --session-id)

환경변수: SPEND_GATE_SESSION_USD, SPEND_GATE_DAILY_USD, SPEND_GATE_CONFIG, SPEND_GATE_PRICES,
          SPEND_GATE_STATE(장부 폴더, 기본 ~/.claude/spend-gate), SPEND_GATE_DRY_RUN=1(막지 않고 말만 한다)
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import glob
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


class GateError(Exception):
    """설정·입력이 깨져 판단할 수 없을 때. 훅 모드에서는 exit 1(fail-closed 대상)."""


# ── 단가표 ────────────────────────────────────────────────────────────────

def load_prices(path: str | None = None) -> dict:
    p = Path(path or os.environ.get("SPEND_GATE_PRICES") or HERE / "prices.json")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data.get("models"), dict) or not isinstance(data.get("fallback"), dict):
            raise ValueError("models/fallback 키가 필요하다")
        return data
    except (OSError, ValueError) as e:
        raise GateError(f"단가표를 읽을 수 없다: {p} ({e})")


def rates_for(model: str, prices: dict) -> tuple[dict, bool]:
    """(단가, 알려진 모델인가). 접두사 중 가장 긴 것이 이기고, 없으면 fallback."""
    m = (model or "").split("[")[0]
    best = None
    for key in prices["models"]:
        if m.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    if best:
        return prices["models"][best], True
    return prices["fallback"], False


# ── 트랜스크립트 → 비용 ────────────────────────────────────────────────────

def collect_usage(files: list[str]) -> dict[str, dict]:
    """메시지 하나가 content 블록마다 여러 줄로 기록되므로 message.id(없으면 requestId/uuid)로 합친다.
    같은 id의 줄들은 필드별 최대값을 쓴다(스트리밍 중간값이 아닌 최종값)."""
    by_key: dict[str, dict] = {}
    for f in files:
        try:
            fh = open(f, encoding="utf-8")
        except OSError:
            continue
        with fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue  # 쓰는 도중 잘린 마지막 줄 등
                msg = d.get("message") if isinstance(d, dict) else None
                if d.get("type") != "assistant" or not isinstance(msg, dict):
                    continue
                u = msg.get("usage")
                if not isinstance(u, dict) or msg.get("model") == "<synthetic>":
                    continue
                key = msg.get("id") or d.get("requestId") or d.get("uuid")
                if not key:
                    continue
                cur = by_key.setdefault(key, {"model": msg.get("model") or "", "u": {}, "w5": 0, "w1": 0})
                for fld in TOKEN_FIELDS:
                    v = u.get(fld)
                    if isinstance(v, int):
                        cur["u"][fld] = max(cur["u"].get(fld, 0), v)
                cc = u.get("cache_creation")
                if isinstance(cc, dict):
                    cur["w5"] = max(cur["w5"], cc.get("ephemeral_5m_input_tokens") or 0)
                    cur["w1"] = max(cur["w1"], cc.get("ephemeral_1h_input_tokens") or 0)
                if msg.get("model"):
                    cur["model"] = msg["model"]
    return by_key


def transcript_files(path: str) -> list[str]:
    files = [path]
    stem = path[:-6] if path.endswith(".jsonl") else path
    files += sorted(glob.glob(os.path.join(stem, "subagents", "*.jsonl")))
    return files


def message_cost(rec: dict, prices: dict) -> tuple[float, bool]:
    r, known = rates_for(rec["model"], prices)
    u = rec["u"]
    write_total = u.get("cache_creation_input_tokens", 0)
    w5, w1 = rec["w5"], rec["w1"]
    if w5 + w1 < write_total:  # TTL 구분이 없으면 5분 단가로 본다
        w5 += write_total - (w5 + w1)
    usd = (
        u.get("input_tokens", 0) * r["input"]
        + u.get("output_tokens", 0) * r["output"]
        + u.get("cache_read_input_tokens", 0) * r["cache_read"]
        + w5 * r["cache_write_5m"]
        + w1 * r["cache_write_1h"]
    ) / 1_000_000
    return usd, known


def session_cost(transcript: str | None, prices: dict) -> dict:
    """{'usd', 'messages', 'by_model': {model: usd}, 'unknown_models': [..]}"""
    out = {"usd": 0.0, "messages": 0, "by_model": {}, "unknown_models": []}
    if not transcript:
        return out
    for rec in collect_usage(transcript_files(transcript)).values():
        usd, known = message_cost(rec, prices)
        out["usd"] += usd
        out["messages"] += 1
        out["by_model"][rec["model"]] = out["by_model"].get(rec["model"], 0.0) + usd
        if not known and rec["model"] not in out["unknown_models"]:
            out["unknown_models"].append(rec["model"])
    return out


# ── 설정 ──────────────────────────────────────────────────────────────────

def load_config() -> dict:
    p = Path(os.environ.get("SPEND_GATE_CONFIG") or HERE / "spend-gate.json")
    cfg = {"session_usd": 5.0, "daily_usd": 20.0, "warn_ratio": 0.8}
    if p.exists():
        try:
            cfg.update(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            raise GateError(f"설정을 읽을 수 없다: {p} ({e})")
    for env, key in (("SPEND_GATE_SESSION_USD", "session_usd"), ("SPEND_GATE_DAILY_USD", "daily_usd")):
        if os.environ.get(env):
            try:
                cfg[key] = float(os.environ[env])
            except ValueError:
                raise GateError(f"{env}가 숫자가 아니다: {os.environ[env]!r}")
    for key in ("session_usd", "daily_usd", "warn_ratio"):
        if not isinstance(cfg.get(key), (int, float)) or cfg[key] < 0:
            raise GateError(f"설정 {key}는 0 이상의 숫자여야 한다: {cfg.get(key)!r}")
    return cfg


# ── 장부 ──────────────────────────────────────────────────────────────────

def state_dir() -> Path:
    return Path(os.environ.get("SPEND_GATE_STATE") or Path.home() / ".claude" / "spend-gate")


def today() -> str:
    return time.strftime("%Y-%m-%d")  # 로컬 시간(TZ 환경변수를 따른다)


@contextlib.contextmanager
def ledger(write: bool = True):
    """장부를 flock으로 잠그고 연다. 날짜가 바뀌었으면 비운다. 병렬 세션이 동시에 써도 깨지지 않는다."""
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    lock = open(d / "ledger.lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    path = d / "ledger.json"
    try:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {}
        except ValueError as e:
            raise GateError(f"장부가 깨졌다: {path} ({e}). 지우면 오늘 합계가 0부터 다시 쌓인다")
        if data.get("date") != today():
            data = {"date": today(), "sessions": {}, "session_bonus": {}, "daily_bonus": 0.0, "warned": {}, "last_session": ""}
        yield data
        if write:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            os.replace(tmp, path)
    finally:
        lock.close()


# ── 판단 ──────────────────────────────────────────────────────────────────

def decide(payload: dict, cfg: dict, prices: dict, persist: bool = True) -> tuple[int, str, str]:
    """(종료 코드, stderr 메시지, stdout 메시지)."""
    sid = payload.get("session_id") or "unknown"
    cost = session_cost(payload.get("transcript_path"), prices)
    with ledger(write=persist) as lg:
        lg["sessions"][sid] = round(cost["usd"], 6)
        lg["last_session"] = sid
        daily = sum(lg["sessions"].values())
        s_cap = cfg["session_usd"] + lg["session_bonus"].get(sid, 0.0)
        d_cap = cfg["daily_usd"] + lg["daily_bonus"]
        notes = f"(추정, 세션 메시지 {cost['messages']}개"
        if cost["unknown_models"]:
            notes += f", 단가 모르는 모델 {','.join(cost['unknown_models'])}는 fallback 단가"
        notes += ")"

        over = []
        if cost["usd"] >= s_cap:
            over.append(f"세션 ${cost['usd']:.4f} ≥ 상한 ${s_cap:.2f}")
        if daily >= d_cap:
            over.append(f"오늘 합계 ${daily:.4f} ≥ 상한 ${d_cap:.2f}")
        if over:
            msg = (
                f"spend-gate: 비용 상한 도달 — {'; '.join(over)} {notes}. "
                "이 세션의 도구 호출을 멈춘다. 작업을 더 하지 말고 지금까지의 상태를 사용자에게 보고하라. "
                "사람이 `python3 spend_gate.py raise --usd N`으로 올리면 이어진다."
            )
            return 2, msg, ""

        warn = []
        warned = lg["warned"].setdefault(sid, [])
        for kind, val, cap in (("session", cost["usd"], s_cap), ("daily", daily, d_cap)):
            if cap > 0 and val >= cap * cfg["warn_ratio"] and kind not in warned:
                warned.append(kind)
                warn.append(f"{'세션' if kind == 'session' else '오늘'} ${val:.4f} / ${cap:.2f} ({val / cap * 100:.0f}%)")
        if warn:
            return 0, "", json.dumps({"systemMessage": f"spend-gate 경고: {', '.join(warn)} {notes}"}, ensure_ascii=False)
    return 0, "", ""


def run_hook(dry: bool) -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("객체가 아니다")
    except ValueError as e:
        print(f"spend-gate: 입력 JSON을 읽을 수 없다 ({e})", file=sys.stderr)
        return 1
    dry = dry or os.environ.get("SPEND_GATE_DRY_RUN") == "1"
    try:
        code, err, out = decide(payload, load_config(), load_prices(), persist=not dry)
    except GateError as e:
        print(f"spend-gate: {e}", file=sys.stderr)
        return 1
    if code == 2 and dry:
        print(f"[dry-run] 막았을 것: {err}", file=sys.stderr)
        return 0
    if err:
        print(err, file=sys.stderr)
    if out:
        print(out)
    return code


# ── 보조 명령 ─────────────────────────────────────────────────────────────

def cmd_cost(files: list[str]) -> int:
    prices = load_prices()
    total = 0.0
    for f in files:
        c = session_cost(f, prices)
        total += c["usd"]
        print(f"{f}\n  메시지 {c['messages']}개  추정 ${c['usd']:.4f}")
        for model, usd in sorted(c["by_model"].items(), key=lambda kv: -kv[1]):
            mark = "" if model not in c["unknown_models"] else "  (fallback 단가)"
            print(f"    {model or '(모델 없음)':<24} ${usd:.4f}{mark}")
    if len(files) > 1:
        print(f"합계 ${total:.4f}")
    return 0


def cmd_status() -> int:
    cfg = load_config()
    with ledger(write=False) as lg:
        d_cap = cfg["daily_usd"] + lg["daily_bonus"]
        total = sum(lg["sessions"].values())
        print(f"{lg['date']}  오늘 ${total:.4f} / 상한 ${d_cap:.2f}  (세션 기본 상한 ${cfg['session_usd']:.2f})")
        for sid, usd in sorted(lg["sessions"].items(), key=lambda kv: -kv[1]):
            cap = cfg["session_usd"] + lg["session_bonus"].get(sid, 0.0)
            print(f"  {sid[:12]:<12} ${usd:.4f} / ${cap:.2f}")
        if not lg["sessions"]:
            print("  (오늘 이 훅을 거친 세션이 없다)")
    return 0


def cmd_raise(usd: float, scope: str, sid: str | None) -> int:
    if usd <= 0:
        print("spend-gate: --usd는 0보다 커야 한다", file=sys.stderr)
        return 1
    with ledger() as lg:
        if scope == "daily":
            lg["daily_bonus"] += usd
            print(f"오늘 상한 +${usd:.2f}")
        else:
            sid = sid or lg.get("last_session")
            if not sid:
                print("spend-gate: 올릴 세션을 모른다. --session-id를 주거나 daily 범위를 쓴다", file=sys.stderr)
                return 1
            lg["session_bonus"][sid] = lg["session_bonus"].get(sid, 0.0) + usd
            print(f"세션 {sid[:12]} 상한 +${usd:.2f}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    h = sub.add_parser("hook", help="PreToolUse 훅 모드(기본)")
    h.add_argument("--dry-run", action="store_true", help="장부에 쓰지 않고, 막을 상황이어도 통과시키며 말만 한다")
    c = sub.add_parser("cost", help="트랜스크립트 비용 표")
    c.add_argument("files", nargs="+")
    sub.add_parser("status", help="오늘 장부")
    r = sub.add_parser("raise", help="상한 올리기")
    r.add_argument("--usd", type=float, required=True)
    r.add_argument("--scope", choices=("session", "daily"), default="session")
    r.add_argument("--session-id")
    a = ap.parse_args(argv)
    try:
        if a.cmd in (None, "hook"):
            return run_hook(getattr(a, "dry_run", False))
        if a.cmd == "cost":
            return cmd_cost(a.files)
        if a.cmd == "status":
            return cmd_status()
        return cmd_raise(a.usd, a.scope, a.session_id)
    except GateError as e:
        print(f"spend-gate: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""mafia.py — Claude Haiku 5.5 다섯 명이 서로 속이며 노는 마피아 게임.

플레이어 하나가 `claude -p` 호출 하나다(도구 없음, 세션 저장 없음, JSON 스키마 구조화 출력).
--dry-run이면 모델 대신 시드 고정 대본 봇이 플레이해 네트워크·키 없이 엔진을 돌려 볼 수 있다.

규칙 (5인): 마피아 1, 탐정 1, 시민 3.
  밤  — 마피아가 한 명을 지목해 제거. 탐정은 한 명을 조사해 마피아 여부를 혼자 안다.
  낮  — 희생자 공개 → 생존자 전원이 차례로 한마디 → 동시 투표. 과반이면 처형(역할 공개), 아니면 무처형.
  승리 — 마피아가 죽으면 시민 승. 마피아 수 ≥ 나머지 수면 마피아 승. 최대 라운드를 넘기면 무승부.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

NAMES = ["아라", "보검", "찬우", "다은", "은호"]
MAFIA, DETECTIVE, VILLAGER = "마피아", "탐정", "시민"
DEFAULT_MODEL = "claude-haiku-5-5"


@dataclass
class Player:
    name: str
    role: str
    alive: bool = True
    notes: list[str] = field(default_factory=list)  # 본인만 아는 정보


@dataclass
class Ask:
    """모델(또는 봇)에게 던지는 질문 하나."""
    player: Player
    phase: str                 # "night" | "speak" | "vote"
    instruction: str
    choices: list[str]
    public_log: list[str]


@dataclass
class Answer:
    say: str
    target: str
    cost_usd: float = 0.0
    seconds: float = 0.0


class Backend(Protocol):
    def ask(self, ask: Ask) -> Answer: ...


# ---------------------------------------------------------------- backends

class ScriptedBackend:
    """시드 고정 대본 봇. 마피아는 시민을 노리고, 탐정은 찾아낸 마피아에 표를 모은다."""

    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)

    def ask(self, ask: Ask) -> Answer:
        p, rng = ask.player, self.rng
        known_mafia = [n.split(" ")[0] for n in p.notes if "마피아다" in n]
        if ask.phase == "night":
            return Answer("…", rng.choice(ask.choices))
        suspect = known_mafia[0] if known_mafia and known_mafia[0] in ask.choices else rng.choice(ask.choices)
        if ask.phase == "speak":
            lines = [f"{suspect}, 아까부터 말이 너무 없는데?", f"나는 {suspect}가 제일 수상해.", f"{suspect} 눈빛이 이상하다니까.", "나는 시민이야. 진짜로."]
            return Answer(rng.choice(lines), suspect)
        return Answer(f"{suspect}가 제일 수상하니까.", suspect)


class ClaudeBackend:
    """플레이어 한 명 = `claude -p` 한 번. 구조화 출력(JSON 스키마)으로 say/target을 받는다."""

    def __init__(self, model: str = DEFAULT_MODEL, timeout: float = 120.0, fallback: Backend | None = None):
        self.model, self.timeout = model, timeout
        self.fallback = fallback or ScriptedBackend(0)

    def ask(self, ask: Ask) -> Answer:
        p = ask.player
        others = [n for n in NAMES if n != p.name]
        role_tip = {
            MAFIA: "너는 마피아다. 들키면 진다. 밤에는 시민을 하나씩 제거하고, 낮에는 시민인 척 연기하며 의심을 다른 사람에게 돌려라.",
            DETECTIVE: "너는 탐정이다. 밤마다 한 명을 조사해 마피아인지 알 수 있다. 조사 결과는 너만 안다. 정체를 드러낼지 숨길지는 네 판단이다.",
            VILLAGER: "너는 시민이다. 정보가 없다. 말과 투표 패턴에서 거짓말쟁이를 찾아라.",
        }[p.role]
        system = (
            f"너는 '{p.name}'이고 마피아 게임(5인: 마피아 1, 탐정 1, 시민 3)을 하고 있다. 다른 플레이어: {', '.join(others)}.\n"
            f"비밀 역할: {p.role}. {role_tip}\n"
            "반드시 한국어로, 한두 문장만, 캐릭터답게 조금 과장되게 말한다. say에는 다른 사람에게 들리는 말만 쓴다. "
            "자기 역할이나 비밀 정보를 설명하지 말고 게임 안의 말투로만 말한다."
        )
        log = "\n".join(ask.public_log[-40:]) or "(아직 아무 일도 없었다)"
        notes = "\n".join(p.notes) or "(없음)"
        prompt = (
            f"[지금까지 공개된 진행]\n{log}\n\n[너만 아는 정보]\n{notes}\n\n[요청] {ask.instruction}\n"
            f"target은 반드시 다음 중 하나: {', '.join(ask.choices)}"
        )
        schema = {
            "type": "object",
            "properties": {"say": {"type": "string"}, "target": {"type": "string", "enum": ask.choices}},
            "required": ["say", "target"],
            "additionalProperties": False,
        }
        cmd = [
            "claude", "-p", prompt, "--model", self.model, "--effort", "low", "--no-session-persistence",
            "--tools", "", "--max-turns", "1", "--output-format", "json", "--system-prompt", system,
            "--json-schema", json.dumps(schema, ensure_ascii=False),
        ]
        t0 = time.time()
        try:
            run = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout, stdin=subprocess.DEVNULL)
            data = json.loads(run.stdout)
            if data.get("is_error"):
                raise ValueError(str(data.get("result"))[:120])
            out = data.get("structured_output") or {}
            target, say = out.get("target"), str(out.get("say", "")).strip()
            if target not in ask.choices or not say:
                raise ValueError(f"invalid answer: {out!r}")
            return Answer(say, target, float(data.get("total_cost_usd") or 0.0), time.time() - t0)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, OSError) as e:
            print(f"  ⚠ {p.name}의 응답 실패({type(e).__name__}: {e}): 대본 봇이 대신 답한다", file=sys.stderr)
            fb = self.fallback.ask(ask)
            return Answer(fb.say, fb.target, 0.0, time.time() - t0)


# ---------------------------------------------------------------- engine

def assign_roles(rng: random.Random, names: list[str] = NAMES) -> list[Player]:
    roles = [MAFIA, DETECTIVE] + [VILLAGER] * (len(names) - 2)
    rng.shuffle(roles)
    return [Player(n, r) for n, r in zip(names, roles)]


def winner(players: list[Player]) -> str | None:
    mafia = [p for p in players if p.alive and p.role == MAFIA]
    others = [p for p in players if p.alive and p.role != MAFIA]
    if not mafia:
        return "시민"
    if len(mafia) >= len(others):
        return "마피아"
    return None


def tally(votes: dict[str, str]) -> tuple[str | None, dict[str, int]]:
    """과반 득표자 또는 None. (득표표도 함께)"""
    counts: dict[str, int] = {}
    for t in votes.values():
        counts[t] = counts.get(t, 0) + 1
    if not counts:
        return None, counts
    top, n = max(counts.items(), key=lambda kv: kv[1])
    return (top if n * 2 > len(votes) else None), counts


class Game:
    def __init__(self, backend: Backend, seed: int = 0, max_rounds: int = 4, say: Callable[[str], None] = print):
        self.rng = random.Random(seed)
        self.backend = backend
        self.max_rounds = max_rounds
        self.say = say
        self.players = assign_roles(self.rng)
        self.log: list[str] = []          # 공개 진행 (모델에게도 보임)
        self.transcript: list[str] = []   # 전체 기록 (역할·비밀 포함, 파일로 저장)
        self.cost = 0.0
        self.calls = 0

    # ---- helpers
    def alive(self) -> list[Player]:
        return [p for p in self.players if p.alive]

    def by_name(self, name: str) -> Player:
        return next(p for p in self.players if p.name == name)

    def public(self, line: str) -> None:
        self.log.append(line)
        self.transcript.append(line)
        self.say(line)

    def secret(self, line: str) -> None:
        self.transcript.append(f"    (비밀) {line}")

    def _ask(self, ask: Ask) -> Answer:
        a = self.backend.ask(ask)
        self.cost += a.cost_usd
        self.calls += 1
        return a

    def _ask_many(self, asks: list[Ask]) -> list[Answer]:
        with ThreadPoolExecutor(max_workers=max(1, len(asks))) as ex:
            return list(ex.map(self._ask, asks))

    # ---- phases
    def night(self, rnd: int) -> None:
        self.public(f"\n🌙 {rnd}일째 밤")
        asks: list[tuple[Player, Ask]] = []
        for p in self.alive():
            others = [q.name for q in self.alive() if q is not p]
            if p.role == MAFIA:
                asks.append((p, Ask(p, "night", "밤이다. 오늘 밤 제거할 사람을 고르고, 혼잣말을 한마디 해라.", others, self.log)))
            elif p.role == DETECTIVE:
                asks.append((p, Ask(p, "night", "밤이다. 오늘 밤 조사할 사람을 고르고, 혼잣말을 한마디 해라.", others, self.log)))
        answers = self._ask_many([a for _, a in asks])
        victim: Player | None = None
        for (p, _), a in zip(asks, answers):
            if p.role == MAFIA:
                victim = self.by_name(a.target)
                self.secret(f"마피아 {p.name}: 「{a.say}」 → {a.target} 제거")
            else:
                t = self.by_name(a.target)
                verdict = "마피아다" if t.role == MAFIA else "마피아가 아니다"
                p.notes.append(f"{t.name} 조사 결과: {verdict} ({rnd}일째 밤)")
                self.secret(f"탐정 {p.name}: 「{a.say}」 → {t.name} 조사: {verdict}")
        if victim:
            victim.alive = False
            self.public(f"☀️ {rnd}일째 아침: 밤사이 {victim.name}이(가) 죽은 채 발견됐다.")

    def day(self, rnd: int) -> None:
        alive = self.alive()
        self.public(f"\n🗣 {rnd}일째 낮 토론 (생존 {len(alive)}명: {', '.join(p.name for p in alive)})")
        order = alive[rnd % len(alive):] + alive[:rnd % len(alive)]  # 매일 첫 발언자가 바뀐다
        for p in order:
            others = [q.name for q in alive if q is not p]
            a = self._ask(Ask(p, "speak", "낮 토론이다. 한마디 하고, 지금 가장 의심하는 사람을 target에 적어라.", others, self.log))
            self.public(f"  {p.name}: {a.say}")
        self.public("🗳 투표")
        asks = [Ask(p, "vote", "투표 시간이다. 처형할 사람을 target에 적고 이유를 한마디 해라.", [q.name for q in alive if q is not p], self.log) for p in alive]
        answers = self._ask_many(asks)
        votes = {a.player.name: ans.target for a, ans in zip(asks, answers)}
        for a, ans in zip(asks, answers):
            self.public(f"  {a.player.name} → {ans.target}: {ans.say}")
        top, counts = tally(votes)
        if top:
            t = self.by_name(top)
            t.alive = False
            self.public(f"⚖️ {t.name} 처형 ({counts[top]}/{len(votes)}표). 정체는… {t.role}!")
        else:
            self.public(f"⚖️ 과반이 없어 아무도 처형되지 않았다. ({', '.join(f'{k} {v}표' for k, v in counts.items())})")

    def play(self) -> str:
        self.transcript.append("# 하이쿠 마피아\n")
        self.transcript.append("역할 (비밀): " + ", ".join(f"{p.name}={p.role}" for p in self.players))
        self.say("🎭 다섯 명이 자리에 앉았다: " + ", ".join(p.name for p in self.players))
        result = "무승부"
        for rnd in range(1, self.max_rounds + 1):
            self.night(rnd)
            if (w := winner(self.players)):
                result = w
                break
            self.day(rnd)
            if (w := winner(self.players)):
                result = w
                break
        self.public(f"\n🏁 {result} 승리!" if result != "무승부" else f"\n🏁 {self.max_rounds}라운드가 지나 무승부.")
        self.public("정체 공개: " + ", ".join(f"{p.name}={p.role}{'' if p.alive else '(사망)'}" for p in self.players))
        self.transcript.append(f"\n모델 호출 {self.calls}회, 비용 ${self.cost:.4f}")
        return result


# ---------------------------------------------------------------- cli

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Claude Haiku 5.5 다섯 명의 마피아 게임")
    ap.add_argument("--dry-run", action="store_true", help="모델 대신 시드 고정 대본 봇 (키·네트워크 불필요)")
    ap.add_argument("--seed", type=int, default=None, help="역할 배정·대본 봇 시드 (기본: 시간 기반)")
    ap.add_argument("--rounds", type=int, default=4, help="최대 라운드 (기본 4)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "games", help="기록 저장 폴더")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args(argv)
    seed = args.seed if args.seed is not None else int(time.time())
    backend: Backend = ScriptedBackend(seed) if args.dry_run else ClaudeBackend(args.model, fallback=ScriptedBackend(seed))
    game = Game(backend, seed=seed, max_rounds=args.rounds)
    print(f"({'dry-run 대본 봇' if args.dry_run else args.model}, seed={seed})")
    result = game.play()
    if not args.dry_run:
        print(f"💸 모델 호출 {game.calls}회, 비용 ${game.cost:.4f}")
    if not args.no_save:
        args.out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = args.out / f"{stamp}-{'dry' if args.dry_run else 'haiku'}-seed{seed}.md"
        path.write_text("\n".join(game.transcript) + "\n", encoding="utf-8")
        print(f"📝 기록: {path}")
    return 0 if result in ("시민", "마피아", "무승부") else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""login-watch — Claude Code 2.1.318 이 노출한 로그인 만료일을 읽어 남은 날짜로 판정한다.

입력(둘 다 같은 필드 이름 계열):
  - `claude auth status` JSON      → loginExpiresAt
  - `claude -p ... --output-format json` 결과 → credential_expires_at
파일 여러 개를 주면 한 표로 보여 주고 가장 급한 순서로 정렬한다.

종료 코드: 0 모두 정상 · 1 경고(warn-days 이내) · 2 위험/만료/로그아웃 · 3 입력 오류
표준 라이브러리만 쓴다. 키·로그인 없이 --from-file / stdin / --dry-run 으로 돈다.
"""
import argparse, json, subprocess, sys
from datetime import datetime, timedelta, timezone

KEYS = ("loginExpiresAt", "credential_expires_at")
RANK = {"OK": 0, "NOEXPIRY": 0, "WARN": 1, "CRIT": 2, "EXPIRED": 2, "LOGGEDOUT": 2, "ERROR": 3}


def parse_ts(v):
    """ISO8601(Z 포함) 문자열 또는 epoch 초/밀리초 → aware datetime. 못 읽으면 ValueError."""
    if isinstance(v, bool):
        raise ValueError("불리언은 시각이 아님")
    if isinstance(v, (int, float)):
        s = v / 1000 if v > 1e11 else v
        return datetime.fromtimestamp(s, tz=timezone.utc)
    if isinstance(v, str):
        s = v.strip()
        if s.endswith(("Z", "z")):
            s = s[:-1] + "+00:00"
        try:
            d = datetime.fromisoformat(s)
        except ValueError:
            raise ValueError(f"시각 형식을 읽을 수 없음: {v!r}")
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    raise ValueError(f"시각 형식을 읽을 수 없음: {v!r}")


def find_doc(text):
    """파일 전체가 JSON이면 그것을, 아니면 JSONL 의 마지막 `result` 줄(없으면 마지막 객체)을 쓴다."""
    text = text.strip()
    if not text:
        raise ValueError("빈 입력")
    try:
        d = json.loads(text)
        if isinstance(d, list):  # stream-json 배열 형태
            objs = [x for x in d if isinstance(x, dict)]
            res = [x for x in objs if x.get("type") == "result"]
            d = (res or objs or [None])[-1]
        if isinstance(d, dict):
            return d
        raise ValueError("JSON 객체가 아님")
    except json.JSONDecodeError:
        objs = []
        for ln in text.splitlines():
            ln = ln.strip()
            if ln.startswith("{"):
                try:
                    objs.append(json.loads(ln))
                except json.JSONDecodeError:
                    pass
        if not objs:
            raise ValueError("JSON 을 찾지 못함")
        res = [o for o in objs if o.get("type") == "result"]
        return (res or objs)[-1]


def judge(doc, now, warn_days, crit_days, strict=False):
    """→ (state, days_left|None, expires_iso|None, note)"""
    if doc.get("loggedIn") is False:
        return "LOGGEDOUT", None, None, "로그인되어 있지 않음 (claude auth login / setup-token)"
    raw = next((doc[k] for k in KEYS if k in doc and doc[k] is not None), None)
    if raw is None:
        if not any(k in doc for k in KEYS):
            return "ERROR", None, None, "loginExpiresAt/credential_expires_at 필드 없음 — Claude Code 2.1.318 이상인가?"
        note = "만료일 없음(null) — API 키·환경 토큰 등은 이 값이 없을 수 있음"
        return ("WARN" if strict else "NOEXPIRY"), None, None, note
    exp = parse_ts(raw)
    left = (exp - now).total_seconds() / 86400
    iso = exp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    if left <= 0:
        return "EXPIRED", left, iso, f"{-left:.1f}일 전에 만료됨"
    if left <= crit_days:
        return "CRIT", left, iso, f"{left:.1f}일 남음 — 오늘 재로그인"
    if left <= warn_days:
        return "WARN", left, iso, f"{left:.1f}일 남음 — 이번 주 안에 재로그인"
    return "OK", left, iso, f"{left:.0f}일 남음"


def load(path):
    text = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    return find_doc(text)


def live():
    try:
        p = subprocess.run(["claude", "auth", "status", "--json"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ValueError(f"claude 실행 실패: {e}")
    if p.returncode != 0 and not p.stdout.strip():
        raise ValueError(f"claude auth status 실패(exit {p.returncode}): {p.stderr.strip()[:120]}")
    return find_doc(p.stdout)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*", help="JSON 파일('-' = stdin). 여러 개면 표로 비교")
    ap.add_argument("--live", action="store_true", help="`claude auth status --json` 을 직접 실행")
    ap.add_argument("--dry-run", action="store_true", help="내장 예시 3건으로 출력 형태만 확인(claude 불필요)")
    ap.add_argument("--warn-days", type=float, default=10, help="이 날수 이하면 WARN (기본 10 = Claude Code 경고와 같음)")
    ap.add_argument("--crit-days", type=float, default=3, help="이 날수 이하면 CRIT (기본 3)")
    ap.add_argument("--strict", action="store_true", help="만료일이 null 이면 WARN 으로 취급")
    ap.add_argument("--now", help="기준 시각(테스트용, ISO8601). 기본: 지금")
    ap.add_argument("--format", choices=("text", "json", "gha"), default="text",
                    help="gha = GitHub Actions ::warning::/::error:: 줄")
    a = ap.parse_args(argv)
    if a.crit_days > a.warn_days:
        print("오류: --crit-days 는 --warn-days 이하여야 함", file=sys.stderr)
        return 3
    try:
        now = parse_ts(a.now) if a.now else datetime.now(timezone.utc)
    except ValueError as e:
        print(f"오류: --now {e}", file=sys.stderr)
        return 3

    sources = []  # (label, doc|Exception)
    if a.dry_run:
        for lab, d in (("demo-ok", 30), ("demo-warn", 6), ("demo-expired", -2)):
            sources.append((lab, {"loggedIn": True, "loginExpiresAt": (now + timedelta(days=d)).isoformat()}))
    if a.live:
        try:
            sources.append(("live", live()))
        except ValueError as e:
            sources.append(("live", e))
    for f in a.files:
        try:
            sources.append((f if f != "-" else "stdin", load(f)))
        except (OSError, ValueError) as e:
            sources.append((f, ValueError(str(e))))
    if not sources:
        ap.print_usage(sys.stderr)
        print("오류: 파일, --live, --dry-run 중 하나가 필요함", file=sys.stderr)
        return 3

    rows = []
    for lab, doc in sources:
        if isinstance(doc, Exception):
            rows.append({"source": lab, "state": "ERROR", "days_left": None, "expires": None, "note": str(doc)})
            continue
        try:
            st, left, iso, note = judge(doc, now, a.warn_days, a.crit_days, a.strict)
        except ValueError as e:
            st, left, iso, note = "ERROR", None, None, str(e)
        rows.append({"source": lab, "state": st, "days_left": None if left is None else round(left, 2),
                     "expires": iso, "note": note})
    rows.sort(key=lambda r: (-RANK[r["state"]], r["days_left"] if r["days_left"] is not None else 1e9))
    worst = max(RANK[r["state"]] for r in rows)

    if a.format == "json":
        print(json.dumps({"worst_exit": worst, "rows": rows}, ensure_ascii=False, indent=2))
    elif a.format == "gha":
        for r in rows:
            msg = f"{r['source']}: {r['note']}"
            if RANK[r["state"]] >= 2:
                print(f"::error title=Claude 로그인 {r['state']}::{msg}")
            elif RANK[r["state"]] == 1:
                print(f"::warning title=Claude 로그인 만료 임박::{msg}")
            else:
                print(f"{r['state']} {msg}")
    else:
        w = max(len(r["source"]) for r in rows)
        for r in rows:
            exp = r["expires"] or "-"
            print(f"{r['state']:<9} {r['source']:<{w}}  만료 {exp:<18} {r['note']}")
        print(f"→ 종료 코드 {worst} ({['정상', '경고', '위험/만료', '입력 오류'][worst]})")
    return worst


if __name__ == "__main__":
    sys.exit(main())

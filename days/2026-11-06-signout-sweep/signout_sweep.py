#!/usr/bin/env python3
"""signout-sweep — 멤버 이메일 목록을 받아 Claude Enterprise Admin API로 "모든 기기에서 로그아웃"을 일괄 보낸다.

  POST /v1/organizations/users/{user_id}/sign_out   (베타 헤더 admin-user-sign-out-2026-10-08, 키 범위 write:members)
  GET  /v1/organizations/users?email=...            (이메일 → user_id, 키 범위 read:members)

기본은 계획만 보여 주는 dry-run(네트워크 안 씀). 실제로 보내려면 --apply 와 ANTHROPIC_ADMIN_KEY 환경변수.
표준 라이브러리만 쓴다. 키는 인자로 받지 않고 어디에도 출력하지 않는다.
"""
import argparse, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

BETA = "admin-user-sign-out-2026-10-08"
VERSION = "2023-06-01"
DEFAULT_BASE = "https://api.anthropic.com"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# 로그아웃으로 끝나지 않는 것 (공식 문서 "What the request doesn't end")
NOT_ENDED = [
    "API 키 — 계속 동작한다. Admin API 키도 마찬가지. 필요하면 콘솔 Keys에서 삭제",
    "Claude Code 클라우드 세션·루틴 — 계속 돈다. 사람의 루틴은 새 세션을 계속 연다",
    "다른 조직의 OAuth 토큰 — 그 조직의 키로 같은 요청을 한 번 더 보낸다(user id는 조직 간 동일)",
    "Cowork에 연결된 컴퓨터 — 연결이 남는다",
    "진행 중이던 로그인 — 요청 중 또는 5분 뒤까지 끝날 수 있다. 감사 로그에 로그인이 보이면 다시 보낸다",
    "계정에서 내보낸 사람을 못 들어오게 하려면 로그아웃이 아니라 멤버 삭제가 필요하다(로그아웃 후 바로 재로그인 가능)",
]


class Fatal(Exception):
    pass


def read_targets(args):
    items = []
    for e in args.targets:
        items.append(e)
    if args.file:
        src = sys.stdin if args.file == "-" else open(args.file, encoding="utf-8")
        for line in src:
            line = line.split("#", 1)[0].strip()
            if line:
                items.append(line)
    seen, out = set(), []
    for t in items:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


def classify(t):
    if t.startswith("user_"):
        return "id"
    if EMAIL_RE.match(t):
        return "email"
    return "bad"


def http(method, base, path, key, query=None, beta=False):
    url = base.rstrip("/") + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    headers = {"x-api-key": key, "anthropic-version": VERSION, "user-agent": "signout-sweep/1"}
    if beta:
        headers["anthropic-beta"] = BETA
    data = b"{}" if method == "POST" else None
    if data:
        headers["content-type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, dict(r.headers), body
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, {}, str(getattr(e, "reason", e))


def error_code(body):
    try:
        d = json.loads(body)
        err = d.get("error", {})
        return (err.get("details") or {}).get("error_code") or err.get("type") or "", err.get("message", "")
    except Exception:
        return "", body[:120]


def with_retry(fn, tries, wait_cap, sleep):
    """429는 retry-after(상한 wait_cap초), 503·연결 실패는 1초씩 늘려 다시. 마지막 응답을 돌려준다."""
    for n in range(tries):
        status, headers, body = fn()
        if status not in (429, 503, 0) or n == tries - 1:
            return status, headers, body, n + 1
        if status == 429:
            try:
                w = float(headers.get("retry-after") or headers.get("Retry-After") or 1)
            except ValueError:
                w = 1.0
        else:
            w = float(n + 1)
        sleep(min(w, wait_cap))
    return status, headers, body, tries


def resolve(email, a, key, sleep):
    st, h, body, _ = with_retry(
        lambda: http("GET", a.base_url, "/v1/organizations/users", key, {"email": email, "limit": 20}),
        a.tries, a.wait_cap, sleep)
    if st in (401, 403):
        raise Fatal("멤버 조회 %d — 키가 잘못됐거나 read:members 범위가 없다" % st)
    if st != 200:
        return None, "lookup_failed", "조회 HTTP %s" % st
    try:
        data = json.loads(body).get("data", [])
    except Exception:
        return None, "lookup_failed", "조회 응답을 읽지 못함"
    if not data:
        return None, "not_member", "이 조직에 그 이메일 멤버 없음"
    if len(data) > 1:
        return None, "ambiguous", "조회 결과 %d명 — 자동으로 고르지 않음" % len(data)
    m = data[0]
    note = ""
    if (m.get("email") or "").lower() != email.lower():
        note = "이메일 변형으로 일치: %s" % m.get("email")
    return m, "", note


def sign_out(uid, a, key, sleep):
    st, h, body, tries = with_retry(
        lambda: http("POST", a.base_url, "/v1/organizations/users/%s/sign_out" % urllib.parse.quote(uid), key, beta=True),
        a.tries, a.wait_cap, sleep)
    code, msg = error_code(body) if st != 200 else ("", "")
    if st == 200:
        return "signed_out", "", tries
    if st == 400 and code == "cannot_sign_out_primary_owner":
        return "primary_owner", "주 소유자는 로그아웃시킬 수 없다 — 본인이 계정 설정에서 해야 한다", tries
    if st == 400 and code == "organization_not_enrolled_in_beta":
        raise Fatal("이 조직은 로그아웃 베타에 등록되지 않았다(organization_not_enrolled_in_beta). 콘솔 Members 화면의 Sign out everywhere를 쓴다")
    if st in (401, 403):
        raise Fatal("로그아웃 %d — 키가 잘못됐거나 write:members 범위가 없다(부모 조직 키는 쓸 수 없다)" % st)
    if st == 404:
        return "not_member", "이 조직에 그 user id 없음", tries
    if st == 400:
        return "failed", "HTTP 400 %s %s" % (code, msg[:80]), tries
    if st == 429:
        return "failed", "429 한도 초과(재시도 %d회 뒤 포기)" % tries, tries
    if st == 503:
        return "failed", "503 — 일부만 끝났을 수 있다, 다시 보내면 나머지를 끝낸다", tries
    return "failed", "HTTP %s %s" % (st, (msg or body)[:80]), tries


def plan_lines(targets, a):
    lines = []
    for t in targets:
        kind = classify(t)
        if kind == "email":
            lines.append("GET  %s/v1/organizations/users?email=%s" % (a.base_url, urllib.parse.quote(t)))
            lines.append("POST %s/v1/organizations/users/<조회된 id>/sign_out  [anthropic-beta: %s]" % (a.base_url, BETA))
        elif kind == "id":
            lines.append("POST %s/v1/organizations/users/%s/sign_out  [anthropic-beta: %s]" % (a.base_url, t, BETA))
        else:
            lines.append("건너뜀(이메일도 user_ id도 아님): %s" % t)
    return lines


def main(argv=None):
    p = argparse.ArgumentParser(prog="signout_sweep", description=__doc__.split("\n")[0])
    p.add_argument("targets", nargs="*", help="이메일 또는 user_… id")
    p.add_argument("-f", "--file", help="한 줄에 하나(#은 주석). '-'면 표준입력")
    p.add_argument("--apply", action="store_true", help="실제로 보낸다(없으면 dry-run)")
    p.add_argument("--base-url", default=os.environ.get("SIGNOUT_BASE_URL", DEFAULT_BASE))
    p.add_argument("--recheck-after", type=float, default=0, metavar="SEC",
                   help="이 초 뒤 로그아웃된 사람에게 같은 요청을 한 번 더(문서 권장 300). 0이면 안 함")
    p.add_argument("--tries", type=int, default=3, help="429·503 재시도 포함 최대 시도 횟수")
    p.add_argument("--wait-cap", type=float, default=30, help="retry-after를 기다리는 최대 초")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)

    targets = read_targets(a)
    if not targets:
        p.error("이메일이나 user id를 하나 이상 주세요 (인자 또는 --file)")
    bad = [t for t in targets if classify(t) == "bad"]

    if not a.apply:
        out = {"mode": "dry-run", "targets": targets, "plan": plan_lines(targets, a), "not_ended": NOT_ENDED}
        if a.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print("DRY-RUN — 네트워크를 쓰지 않았다. 실제로 보내려면 ANTHROPIC_ADMIN_KEY를 두고 --apply")
            print("대상 %d명" % len(targets))
            for l in out["plan"]:
                print("  " + l)
            print("\n로그아웃으로 끝나지 않는 것:")
            for n in NOT_ENDED:
                print("  - " + n)
        return 2 if bad else 0

    key = os.environ.get("ANTHROPIC_ADMIN_KEY", "")
    if not key:
        print("ANTHROPIC_ADMIN_KEY 환경변수가 없다 (Admin API 키, write:members·read:members 범위)", file=sys.stderr)
        return 2
    sleep = time.sleep
    rows = []
    fatal = None
    try:
        for t in targets:
            kind = classify(t)
            row = {"target": t, "user_id": "", "result": "", "note": ""}
            if kind == "bad":
                row.update(result="invalid", note="이메일도 user_ id도 아님")
            else:
                if kind == "email":
                    m, res, note = resolve(t, a, key, sleep)
                    if m is None:
                        row.update(result=res, note=note)
                        rows.append(row)
                        continue
                    row.update(user_id=m["id"], note=note)
                else:
                    row["user_id"] = t
                res, note, tries = sign_out(row["user_id"], a, key, sleep)
                row["result"] = res
                row["note"] = "; ".join(x for x in (row["note"], note) if x)
            rows.append(row)
        if a.recheck_after > 0:
            done = [r for r in rows if r["result"] == "signed_out"]
            if done:
                print("%d명 대기 %.0f초 후 한 번 더 보낸다 (진행 중이던 로그인 정리)" % (len(done), a.recheck_after), file=sys.stderr)
                sleep(a.recheck_after)
                for r in done:
                    res, note, _ = sign_out(r["user_id"], a, key, sleep)
                    r["recheck"] = res
                    if res != "signed_out":
                        r["note"] = "; ".join(x for x in (r["note"], "재확인 실패: " + (note or res)) if x)
    except Fatal as e:
        fatal = str(e)

    summary = {}
    for r in rows:
        summary[r["result"]] = summary.get(r["result"], 0) + 1
    if a.json:
        print(json.dumps({"mode": "apply", "rows": rows, "summary": summary, "fatal": fatal,
                          "not_ended": NOT_ENDED}, ensure_ascii=False, indent=2))
    else:
        print("%-28s %-30s %-14s %s" % ("대상", "user id", "결과", "메모"))
        for r in rows:
            print("%-28s %-30s %-14s %s" % (r["target"][:28], r["user_id"][:30], r["result"], r["note"]))
        print("\n요약: " + (", ".join("%s %d" % kv for kv in sorted(summary.items())) or "처리한 대상 없음"))
        remaining = len(targets) - len(rows)
        if fatal:
            print("중단: %s (아직 처리 못한 대상 %d명)" % (fatal, remaining), file=sys.stderr)
        if any(r["result"] == "signed_out" for r in rows):
            print("\n끝나지 않은 것 — 사람별로 따로 확인:")
            for n in NOT_ENDED:
                print("  - " + n)
    if fatal:
        return 2
    return 0 if all(r["result"] == "signed_out" for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())

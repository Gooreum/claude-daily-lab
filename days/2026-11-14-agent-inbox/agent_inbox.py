#!/usr/bin/env python3
"""agent-inbox — 항상 켜진 에이전트의 "이벤트 인박스 + 타이머 + 단일 일꾼" 뼈대.

Anthropic 11-13 "Building always-on agents"의 설계를 SQLite 한 파일로 옮긴 작은 CLI.
  - 이벤트 원천은 에이전트를 직접 부르지 않고 인박스에 쓴다 (push)
  - (source, event_id)로 중복을 거른다
  - 타이머는 인박스와 다른 테이블에 두고, tick이 만기를 이벤트로 바꾼다 (실행을 직접 시작하지 않음)
  - 일꾼은 인박스당 하나: 임대(lease) 잠금. 죽은 일꾼의 이벤트는 임대가 끝나면 되살린다
  - 짧은 간격으로 들어온 이벤트는 세션 키별로 묶어 한 번의 실행(run)으로 넘긴다 (debounce)
표준 라이브러리만 쓴다. 모델 호출은 없다: --handler 가 없으면 dry-run(무엇을 실행할지만 출력).
"""
import argparse, json, os, re, sqlite3, subprocess, sys, time
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL, event_id TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'event',
  session TEXT NOT NULL DEFAULT 'main', payload TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'pending',   -- pending | running | done | dead
  attempts INTEGER NOT NULL DEFAULT 0, received_at REAL NOT NULL, run_id TEXT, last_error TEXT,
  UNIQUE(source, event_id));
CREATE TABLE IF NOT EXISTS timers(
  name TEXT PRIMARY KEY, due_at REAL NOT NULL, every REAL,        -- every 가 있으면 반복 스케줄
  session TEXT NOT NULL DEFAULT 'main', payload TEXT NOT NULL DEFAULT '{}',
  done INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS lease(inbox TEXT PRIMARY KEY, worker TEXT NOT NULL, expires_at REAL NOT NULL);
"""

UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_dur(s):
    m = re.fullmatch(r"(\d+)([smhd])", s.strip())
    if not m:
        raise SystemExit(f"error: 기간 형식이 아님: {s!r} (예: 30s, 5m, 2h, 1d)")
    return int(m.group(1)) * UNITS[m.group(2)]


def parse_time(s):
    """epoch 숫자 또는 ISO-8601(타임존 없으면 UTC)."""
    try:
        return float(s)
    except ValueError:
        pass
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise SystemExit(f"error: 시각 형식이 아님: {s!r}")
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def fmt(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path):
    db = sqlite3.connect(path, timeout=10, isolation_level=None)  # 명시적 BEGIN 사용
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def now_of(args):
    return parse_time(args.now) if getattr(args, "now", None) else time.time()


def check_json(s):
    try:
        json.loads(s)
    except ValueError as e:
        raise SystemExit(f"error: --payload 가 JSON이 아님: {e}")
    return s


# ---------------------------------------------------------------- push
def add_event(db, source, event_id, kind, session, payload, now):
    cur = db.execute(
        "INSERT OR IGNORE INTO events(source,event_id,kind,session,payload,received_at) VALUES(?,?,?,?,?,?)",
        (source, event_id, kind, session, payload, now))
    return cur.rowcount == 1


def cmd_push(args):
    db = connect(args.db)
    added = add_event(db, args.source, args.id, args.kind, args.session, check_json(args.payload), now_of(args))
    print(("queued" if added else "duplicate") + f" {args.source}/{args.id}")
    return 0


# ---------------------------------------------------------------- timers
def cmd_timer(args):
    db = connect(args.db)
    now = now_of(args)
    if args.action == "add":
        if bool(args.at) == bool(args.in_):
            raise SystemExit("error: --at 또는 --in 중 하나만 준다")
        due = parse_time(args.at) if args.at else now + parse_dur(args.in_)
        every = parse_dur(args.every) if args.every else None
        db.execute("INSERT OR REPLACE INTO timers(name,due_at,every,session,payload,done) VALUES(?,?,?,?,?,0)",
                   (args.name, due, every, args.session, check_json(args.payload)))
        print(f"timer {args.name}: {'schedule' if every else 'follow-up'} due {fmt(due)}")
    else:
        for t in db.execute("SELECT * FROM timers ORDER BY due_at"):
            kind = "schedule" if t["every"] else "follow-up"
            print(f"{t['name']}\t{kind}\tdue {fmt(t['due_at'])}\t{'done' if t['done'] else 'active'}")
    return 0


def tick(db, now):
    """만기 타이머를 이벤트로 바꾼다. 실행은 시작하지 않는다. 반환: [(이름, 이벤트 추가 여부, 놓친 횟수)]"""
    out = []
    db.execute("BEGIN IMMEDIATE")
    try:
        for t in db.execute("SELECT * FROM timers WHERE done=0 AND due_at<=? ORDER BY due_at", (now,)).fetchall():
            due = t["due_at"]
            payload = json.loads(t["payload"])
            missed = 0
            if t["every"]:
                # 놓친 주기는 이벤트 하나로 합친다: 다음 만기를 now 이후로 당긴다
                k = int((now - due) // t["every"]) + 1
                missed = k - 1
                db.execute("UPDATE timers SET due_at=? WHERE name=?", (due + k * t["every"], t["name"]))
            else:
                db.execute("UPDATE timers SET done=1 WHERE name=?", (t["name"],))
            payload.update({"timer": t["name"], "due_at": fmt(due)})
            if missed:
                payload["missed_runs"] = missed
            # 같은 만기를 두 번 넣지 않도록 만기 시각을 이벤트 id에 넣는다
            added = add_event(db, "timer", f"{t['name']}@{fmt(due)}", "schedule" if t["every"] else "follow-up",
                              t["session"], json.dumps(payload, ensure_ascii=False), due)  # 도착 시각=만기: 사용자 연타가 아니므로 debounce 를 기다리지 않는다
            out.append((t["name"], added, missed))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return out


def cmd_tick(args):
    db = connect(args.db)
    res = tick(db, now_of(args))
    for name, added, missed in res:
        print(f"timer {name} → event {'queued' if added else 'duplicate'}" + (f" (놓친 {missed}회 합침)" if missed else ""))
    if not res:
        print("no due timers")
    return 0


# ---------------------------------------------------------------- worker
def acquire_lease(db, inbox, worker, ttl, now):
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute("SELECT * FROM lease WHERE inbox=?", (inbox,)).fetchone()
        if row and row["worker"] != worker and row["expires_at"] > now:
            db.execute("ROLLBACK")
            return False, row["worker"]
        db.execute("INSERT OR REPLACE INTO lease(inbox,worker,expires_at) VALUES(?,?,?)", (inbox, worker, now + ttl))
        db.execute("COMMIT")
        return True, worker
    except Exception:
        db.execute("ROLLBACK")
        raise


def release_lease(db, inbox, worker):
    db.execute("DELETE FROM lease WHERE inbox=? AND worker=?", (inbox, worker))


def ready_groups(db, now, window, max_batch):
    """세션별로 pending 을 묶고, 가장 새 이벤트가 window 초 이상 묵었을 때만 내보낸다(debounce)."""
    groups = {}
    for e in db.execute("SELECT * FROM events WHERE status='pending' ORDER BY seq"):
        groups.setdefault(e["session"], []).append(e)
    out = []
    for sess, evs in groups.items():
        if now - max(e["received_at"] for e in evs) >= window:
            out.append((sess, evs[:max_batch]))
    return out


def run_handler(handler, batch_doc, dry):
    if dry or not handler:
        ids = ", ".join(f"{e['source']}/{e['id']}" for e in batch_doc["events"])
        print(f"[dry-run] run {batch_doc['run_id']} session={batch_doc['session']} events={len(batch_doc['events'])}: {ids}")
        return 0, ""
    p = subprocess.run(handler, shell=True, input=json.dumps(batch_doc, ensure_ascii=False),
                       capture_output=True, text=True)
    if p.stdout:
        sys.stdout.write(p.stdout)
    return p.returncode, (p.stderr.strip()[-300:] if p.returncode else "")


def cmd_work(args):
    db = connect(args.db)
    now = now_of(args)
    ok, holder = acquire_lease(db, "main", args.worker, args.lease, now)
    if not ok:
        print(f"busy: 다른 일꾼({holder})이 인박스를 잡고 있다")
        return 3
    try:
        if args.tick:
            for name, added, _ in tick(db, now):
                print(f"timer {name} → event {'queued' if added else 'duplicate'}")
        # 죽은 일꾼이 남긴 running 이벤트: 임대를 우리가 새로 얻었다는 건 이전 임대가 끝났다는 뜻
        lost = db.execute("UPDATE events SET status='pending', run_id=NULL, last_error='worker lost' "
                          "WHERE status='running'").rowcount
        if lost:
            print(f"recovered {lost} event(s) from a lost worker")
        runs = 0
        for sess, evs in ready_groups(db, now, parse_dur(args.window) if args.window != "0" else 0, args.max_batch):
            run_id = f"run-{sess}@{now:.0f}"
            ids = [e["seq"] for e in evs]
            q = ",".join("?" * len(ids))
            db.execute(f"UPDATE events SET status='running', run_id=?, attempts=attempts+1 WHERE seq IN ({q})", [run_id] + ids)
            doc = {"run_id": run_id, "session": sess,
                   "events": [{"seq": e["seq"], "source": e["source"], "id": e["event_id"], "kind": e["kind"],
                               "payload": json.loads(e["payload"]), "attempts": e["attempts"] + 1} for e in evs]}
            rc, err = run_handler(args.handler, doc, args.dry_run)
            for e in evs:
                if rc == 0:
                    db.execute("UPDATE events SET status='done', last_error=NULL WHERE seq=?", (e["seq"],))
                elif e["attempts"] + 1 >= args.max_attempts:
                    db.execute("UPDATE events SET status='dead', last_error=? WHERE seq=?", (f"exit {rc}: {err}", e["seq"]))
                else:
                    db.execute("UPDATE events SET status='pending', last_error=? WHERE seq=?", (f"exit {rc}: {err}", e["seq"]))
            if rc != 0:
                print(f"run {run_id} failed (exit {rc})")
            runs += 1
            # 실행 중 들어온 이벤트는 건드리지 않는다: pending 으로 남아 다음 run 으로 간다
            if args.once:
                break
            db.execute("UPDATE lease SET expires_at=? WHERE inbox='main' AND worker=?", (now + args.lease, args.worker))
        if runs == 0:
            print("nothing ready")
        return 0
    finally:
        release_lease(db, "main", args.worker)


# ---------------------------------------------------------------- status
def cmd_status(args):
    db = connect(args.db)
    c = {r["status"]: r["n"] for r in db.execute("SELECT status, COUNT(*) n FROM events GROUP BY status")}
    t = db.execute("SELECT COUNT(*) n FROM timers WHERE done=0").fetchone()["n"]
    ls = db.execute("SELECT worker, expires_at FROM lease").fetchone()
    print(f"events: pending={c.get('pending',0)} running={c.get('running',0)} done={c.get('done',0)} dead={c.get('dead',0)}")
    print(f"timers: active={t}")
    print(f"lease: {ls['worker'] + ' until ' + fmt(ls['expires_at']) if ls else 'free'}")
    for e in db.execute("SELECT * FROM events WHERE status='dead' ORDER BY seq"):
        print(f"dead: {e['source']}/{e['event_id']} — {e['last_error']}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="agent_inbox", description=__doc__.split("\n")[0])
    p.add_argument("--db", default=os.environ.get("AGENT_INBOX_DB", "inbox.db"))
    p.add_argument("--now", help="현재 시각 고정(테스트용). epoch 또는 ISO-8601")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("push", help="이벤트를 인박스에 쓴다 (같은 source+id 는 중복으로 거른다)")
    s.add_argument("--source", required=True); s.add_argument("--id", required=True)
    s.add_argument("--kind", default="event"); s.add_argument("--session", default="main")
    s.add_argument("--payload", default="{}"); s.set_defaults(fn=cmd_push)
    s = sub.add_parser("timer", help="타이머 추가·목록")
    s.add_argument("action", choices=["add", "list"]); s.add_argument("--name")
    s.add_argument("--at"); s.add_argument("--in", dest="in_"); s.add_argument("--every")
    s.add_argument("--session", default="main"); s.add_argument("--payload", default="{}")
    s.set_defaults(fn=cmd_timer)
    s = sub.add_parser("tick", help="만기 타이머를 이벤트로 바꾼다 (실행은 시작하지 않는다)"); s.set_defaults(fn=cmd_tick)
    s = sub.add_parser("work", help="일꾼 한 번 돌리기: 임대 → 묶음 실행")
    s.add_argument("--worker", default=f"w{os.getpid()}"); s.add_argument("--lease", type=int, default=300)
    s.add_argument("--window", default="10s", help="가장 새 이벤트가 이만큼 묵어야 실행(debounce). 0 이면 즉시")
    s.add_argument("--max-batch", type=int, default=20); s.add_argument("--max-attempts", type=int, default=3)
    s.add_argument("--handler", help="묶음 JSON 을 stdin 으로 받는 명령. 없으면 dry-run")
    s.add_argument("--dry-run", action="store_true"); s.add_argument("--once", action="store_true", help="run 한 번만")
    s.add_argument("--tick", action="store_true", help="실행 전에 tick 도 한다")
    s.set_defaults(fn=cmd_work)
    s = sub.add_parser("status", help="요약"); s.set_defaults(fn=cmd_status)
    args = p.parse_args(argv)
    if args.cmd == "timer" and args.action == "add" and not args.name:
        p.error("timer add 에는 --name 이 필요하다")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

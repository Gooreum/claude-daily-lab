#!/usr/bin/env python3
"""loop-caps — 무인 반복 실행에 상한을 거는 래퍼 (표준 라이브러리만 사용).

명령을 반복 실행하다가 다음 중 하나가 먼저 오면 멈추고, 멈춘 이유를 JSONL로 남긴다.
  done / stop_file / quota / max_failures / max_calls / max_hours

종료 코드: 0=정상 종료(done·stop_file) · 1=사용법 오류 · 2=한도/지출 소진(quota)
           3=상한 도달(max_calls·max_hours) · 4=연속 실패 상한(max_failures)
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

DEFAULT_QUOTA = (r"enforced_spend_limit_reached|spend limit|session limit|weekly limit"
                 r"|usage limit reached|credit balance")
EXIT = {"done": 0, "stop_file": 0, "quota": 2, "max_calls": 3, "max_hours": 3, "max_failures": 4}


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def positive(kind):
    def conv(s):
        v = kind(s)
        if v <= 0:
            raise argparse.ArgumentTypeError("0 이하는 쓸 수 없다 — 상한은 끌 수 없다")
        return v
    return conv


def build_parser():
    p = argparse.ArgumentParser(
        prog="loop_caps.py",
        usage="loop_caps.py [옵션] -- 명령 [인자...]",
        description="명령을 반복 실행하되 연속 실패·총 호출·경과 시간 상한을 코드로 강제한다. "
                    "한도/지출 소진 문구가 보이면 즉시 멈춘다. 종료 코드: 0=done/stop_file, 1=사용법 오류, "
                    "2=quota, 3=max_calls/max_hours, 4=max_failures.")
    p.add_argument("--max-failures", type=positive(int), default=3, help="연속 실패 상한 (기본 3)")
    p.add_argument("--max-calls", type=positive(int), default=200, help="총 호출 상한 (기본 200)")
    p.add_argument("--max-hours", type=positive(float), default=3.0, help="경과 시간 상한(시간) (기본 3)")
    p.add_argument("--call-timeout", type=positive(float), default=1800.0, help="호출 1회 제한 시간(초) (기본 1800)")
    p.add_argument("--interval", type=float, default=0.0, help="호출 사이 대기 초 (기본 0)")
    p.add_argument("--stop-on-success", action="store_true", help="처음 성공(종료 코드 0)하면 done으로 멈춘다")
    p.add_argument("--done-regex", help="성공한 호출의 출력이 이 정규식에 맞으면 done으로 멈춘다")
    p.add_argument("--stop-file", help="이 파일이 생기면 다음 호출 전에 stop_file로 멈춘다")
    p.add_argument("--quota-regex", default=DEFAULT_QUOTA, help="실패 출력에서 한도/지출 소진으로 볼 정규식")
    p.add_argument("--log", help="JSONL 로그 경로 (호출마다 한 줄 + 마지막 stop 한 줄)")
    p.add_argument("--dry-run", action="store_true", help="명령을 실행하지 않고 적용될 상한만 출력한다")
    p.add_argument("--quiet", action="store_true", help="자식 출력을 전달하지 않는다")
    return p


def is_error_json(text):
    """claude -p --output-format json 은 오류여도 종료 코드 0일 수 있어 is_error를 본다."""
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                obj = json.loads(line)
            except ValueError:
                return False
            return isinstance(obj, dict) and obj.get("is_error") is True
    return False


def run_once(cmd, timeout):
    t0 = time.monotonic()
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           stdin=subprocess.DEVNULL, timeout=timeout)
        out = r.stdout.decode("utf-8", "replace")
        return r.returncode, out, time.monotonic() - t0, False
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode("utf-8", "replace")
        return 124, out, time.monotonic() - t0, True
    except OSError as e:
        return 127, f"{e}\n", time.monotonic() - t0, False


class Log:
    def __init__(self, path):
        self.path = path

    def write(self, rec):
        if not self.path:
            return
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--" not in argv:
        print("loop_caps.py: 명령 앞에 `--`가 필요하다. 예: loop_caps.py --max-calls 5 -- claude -p ...", file=sys.stderr)
        return 1
    i = argv.index("--")
    opts, cmd = argv[:i], argv[i + 1:]
    if not cmd:
        print("loop_caps.py: `--` 뒤에 실행할 명령이 없다", file=sys.stderr)
        return 1
    try:
        a = build_parser().parse_args(opts)
    except SystemExit as e:
        return 0 if e.code == 0 else 1
    try:
        quota_re = re.compile(a.quota_regex, re.I)
        done_re = re.compile(a.done_regex) if a.done_regex else None
    except re.error as e:
        print(f"loop_caps.py: 정규식 오류: {e}", file=sys.stderr)
        return 1

    if a.dry_run:
        print("loop-caps dry-run (명령은 실행하지 않음)")
        print(f"  명령: {' '.join(cmd)}")
        print(f"  연속 실패 {a.max_failures}회 · 총 호출 {a.max_calls}회 · 경과 {a.max_hours}시간 · 호출당 {a.call_timeout:g}초")
        print(f"  한도 소진 정규식: {a.quota_regex}")
        print(f"  멈춤 조건 추가: stop-on-success={a.stop_on_success} done-regex={a.done_regex} stop-file={a.stop_file}")
        print(f"  로그: {a.log or '(없음)'}")
        return 0

    log = Log(a.log)
    start = time.monotonic()
    deadline = start + a.max_hours * 3600
    calls = fails = consec = 0
    reason = None
    while True:
        if a.stop_file and os.path.exists(a.stop_file):
            reason = "stop_file"
            break
        if calls >= a.max_calls:
            reason = "max_calls"
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            reason = "max_hours"
            break
        calls += 1
        rc, out, secs, timed_out = run_once(cmd, min(a.call_timeout, remaining))
        if not a.quiet and out:
            sys.stdout.write(out if out.endswith("\n") else out + "\n")
            sys.stdout.flush()
        failed = rc != 0 or is_error_json(out)
        cls = "ok"
        if failed:
            fails += 1
            consec += 1
            cls = "timeout" if timed_out else ("quota" if quota_re.search(out) else "fail")
        else:
            consec = 0
        log.write({"ts": now_iso(), "event": "call", "call": calls, "rc": rc,
                   "seconds": round(secs, 2), "class": cls, "consecutive_failures": consec})
        if cls == "quota":
            reason = "quota"
            break
        if timed_out and time.monotonic() >= deadline:
            reason = "max_hours"
            break
        if not failed and (a.stop_on_success or (done_re and done_re.search(out))):
            reason = "done"
            break
        if consec >= a.max_failures:
            reason = "max_failures"
            break
        if a.interval > 0:
            time.sleep(min(a.interval, max(0.0, deadline - time.monotonic())))

    elapsed = round(time.monotonic() - start, 2)
    log.write({"ts": now_iso(), "event": "stop", "reason": reason, "calls": calls,
               "failures": fails, "elapsed_s": elapsed})
    print(f"loop-caps: stop={reason} calls={calls} failures={fails} elapsed={elapsed}s", file=sys.stderr)
    return EXIT[reason]


if __name__ == "__main__":
    sys.exit(main())

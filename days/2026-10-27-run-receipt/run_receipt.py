#!/usr/bin/env python3
"""run-receipt — 무인(야간) 실행이 끝난 뒤 "결과가 진짜 있는가"를 확인하는 영수증 검사기.

종료 코드만 믿으면 놓치는 것들을 본다: 결과 파일 없음·어제 것·빈 파일·헤더만 있는 CSV,
`---`로 시작해 CLI 옵션으로 오해되는 프롬프트 파일, 비어 있는 REPORT.md, 사람을 기다리는 BLOCKED.md.
표준 라이브러리만 쓰고 키·모델·네트워크가 필요 없다.

  python3 run_receipt.py check SPEC.json [--now ISO] [--json] [--write-receipt PATH]
  python3 run_receipt.py prompt FILE...        # 프롬프트 파일만 점검

종료 코드: 0=모두 통과, 1=실패 있음, 3=BLOCKED(사람이 볼 차례), 2=사용 오류
"""
import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timedelta

BLOCKED_EXIT = 3


def parse_now(s):
    if not s:
        return datetime.now().astimezone()
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.astimezone()


def fmt_path(p, now):
    return p.replace("{date}", now.strftime("%Y-%m-%d")).replace("{yesterday}", (now - timedelta(days=1)).strftime("%Y-%m-%d"))


def mtime(path):
    return datetime.fromtimestamp(os.path.getmtime(path)).astimezone()


def lint_prompt(path):
    """프롬프트 파일이 `claude -p "$(cat file)"`로 넘어갈 때 옵션으로 읽힐 문제를 찾는다. 문제 목록을 돌려준다."""
    problems = []
    try:
        raw = open(path, "rb").read()
    except OSError as e:
        return ["읽을 수 없음: %s" % e.strerror]
    if not raw.strip():
        return ["프롬프트 파일이 비어 있음"]
    if raw.startswith(b"\xef\xbb\xbf"):
        problems.append("UTF-8 BOM으로 시작함 — 첫 글자가 깨져 보일 수 있음")
        raw = raw[3:]
    first = raw.lstrip()[:1]
    if first == b"-":
        head = raw.lstrip().splitlines()[0][:20].decode("utf-8", "replace")
        problems.append("첫 글자가 '-'(%r) — CLI가 옵션으로 읽을 수 있음. 프롬프트 앞에 `--`를 붙이거나 첫 줄을 바꾸세요" % head)
    return problems


def check_output(spec, root, now):
    """결과 파일 하나를 점검해 (status, 메시지들)를 돌려준다."""
    path = os.path.join(root, fmt_path(spec["path"], now))
    msgs = []
    if not os.path.isfile(path):
        return "FAIL", ["파일 없음"], path
    size = os.path.getsize(path)
    if size < spec.get("min_bytes", 1):
        msgs.append("너무 작음: %d바이트 (최소 %d)" % (size, spec.get("min_bytes", 1)))
    age = now - mtime(path)
    max_age = spec.get("max_age_hours", 24)
    if age > timedelta(hours=max_age):
        msgs.append("오래된 파일: %.1f시간 전 수정 (최대 %s시간)" % (age.total_seconds() / 3600, max_age))
    started = spec.get("run_started")
    if started and mtime(path) < parse_now(started):
        msgs.append("실행 시작(%s) 이전에 마지막으로 수정됨 — 이번 실행이 쓴 파일이 아님" % started)
    text = None
    needs_text = any(k in spec for k in ("min_data_rows", "min_lines", "must_contain", "json"))
    if needs_text:
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError as e:
            msgs.append("읽을 수 없음: %s" % e.strerror)
    if text is not None:
        if "min_lines" in spec:
            n = len([l for l in text.splitlines() if l.strip()])
            if n < spec["min_lines"]:
                msgs.append("내용 줄이 %d개 (최소 %d)" % (n, spec["min_lines"]))
        if "min_data_rows" in spec:
            rows = [r for r in csv.reader(text.splitlines()) if any(c.strip() for c in r)]
            data = max(len(rows) - 1, 0)
            if data < spec["min_data_rows"]:
                msgs.append("헤더 아래 데이터 줄이 %d개 (최소 %d) — 헤더만 있는 파일일 수 있음" % (data, spec["min_data_rows"]))
        for needle in spec.get("must_contain", []):
            if needle not in text:
                msgs.append("필수 문구 없음: %r" % needle)
        if spec.get("json"):
            try:
                val = json.loads(text)
                if val in ({}, [], None, "", 0):
                    msgs.append("JSON은 맞지만 비어 있음 (%s)" % json.dumps(val))
            except ValueError as e:
                msgs.append("JSON 파싱 실패: %s" % e)
    return ("FAIL" if msgs else "OK"), msgs, path


def section_bodies(text):
    """`#` 제목 줄 → 그 아래 본문(다음 제목 전까지)."""
    out, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"^#{1,6}\s+(.*\S)\s*$", line)
        if m:
            cur = m.group(1)
            out[cur] = ""
        elif cur is not None:
            out[cur] += line + "\n"
    return out


def check_report(spec, root, now):
    path = os.path.join(root, fmt_path(spec["path"], now))
    if not os.path.isfile(path):
        return "FAIL", ["보고서 없음"], path
    msgs = []
    age = now - mtime(path)
    if age > timedelta(hours=spec.get("max_age_hours", 24)):
        msgs.append("오래된 보고서: %.1f시간 전 수정" % (age.total_seconds() / 3600))
    bodies = section_bodies(open(path, encoding="utf-8", errors="replace").read())
    for want in spec.get("sections", []):
        hit = [t for t in bodies if want.lower() in t.lower()]
        if not hit:
            msgs.append("보고서에 '%s' 절이 없음" % want)
        elif not any(re.sub(r"[\s\-*_`>]|TODO|TBD", "", bodies[t]) for t in hit):
            msgs.append("보고서의 '%s' 절이 비어 있음" % want)
    return ("FAIL" if msgs else "OK"), msgs, path


def run_check(spec_path, now):
    spec = json.load(open(spec_path, encoding="utf-8"))
    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(spec_path)), spec.get("root", ".")))
    results = []

    def add(kind, status, msgs, path):
        results.append({"kind": kind, "status": status, "path": os.path.relpath(path, root), "messages": msgs})

    for p in spec.get("prompt_files", []):
        full = os.path.join(root, fmt_path(p, now))
        problems = lint_prompt(full)
        add("prompt", "FAIL" if problems else "OK", problems, full)

    blocked = spec.get("blocked")
    blocked_path = os.path.join(root, fmt_path(blocked, now)) if blocked else None
    if blocked_path and os.path.isfile(blocked_path) and os.path.getsize(blocked_path) > 0:
        first = open(blocked_path, encoding="utf-8", errors="replace").read().strip().splitlines()[0][:120]
        add("blocked", "BLOCKED", ["사람이 볼 차례: %s" % first], blocked_path)
        return results, "BLOCKED"          # 막힌 밤은 결과 파일이 없는 게 정상이라 더 보지 않는다

    for o in spec.get("outputs", []):
        add("output", *check_output(o, root, now))
    if "report" in spec:
        add("report", *check_report(spec["report"], root, now))

    return results, ("FAIL" if any(r["status"] == "FAIL" for r in results) else "OK")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("check", help="스펙 JSON대로 영수증 검사")
    c.add_argument("spec")
    c.add_argument("--now", help="현재 시각 ISO8601 (테스트용)")
    c.add_argument("--json", action="store_true")
    c.add_argument("--write-receipt", metavar="PATH", help="결과 JSON을 파일로도 남김")
    p = sub.add_parser("prompt", help="프롬프트 파일만 점검")
    p.add_argument("files", nargs="+")
    a = ap.parse_args(argv)

    if a.cmd == "prompt":
        bad = 0
        for f in a.files:
            probs = lint_prompt(f)
            bad += bool(probs)
            print(("❌ %s: %s" % (f, "; ".join(probs))) if probs else "✅ %s" % f)
        return 1 if bad else 0
    if a.cmd != "check":
        ap.print_usage(sys.stderr)
        return 2
    try:
        results, overall = run_check(a.spec, parse_now(a.now))
    except (OSError, ValueError, KeyError) as e:
        print("run-receipt: 스펙을 읽을 수 없음: %s" % e, file=sys.stderr)
        return 2
    receipt = {"overall": overall, "checked_at": parse_now(a.now).isoformat(timespec="seconds"), "results": results}
    if a.write_receipt:
        with open(a.write_receipt, "w", encoding="utf-8") as fh:
            json.dump(receipt, fh, ensure_ascii=False, indent=2)
    if a.json:
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
    else:
        icon = {"OK": "✅", "FAIL": "❌", "BLOCKED": "⏸"}
        for r in results:
            print("%s [%s] %s%s" % (icon[r["status"]], r["kind"], r["path"], (" — " + "; ".join(r["messages"])) if r["messages"] else ""))
        print("영수증: %s (%d건 중 실패 %d)" % (overall, len(results), sum(r["status"] == "FAIL" for r in results)))
    return {"OK": 0, "FAIL": 1, "BLOCKED": BLOCKED_EXIT}[overall]


if __name__ == "__main__":
    sys.exit(main())

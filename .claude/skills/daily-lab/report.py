#!/usr/bin/env python3
"""report.py — /daily-lab이 끝난 뒤 오늘 결과 요약(제목·본문)을 만든다 (표준 라이브러리만).

GitHub Actions의 "요약 알림" 단계가 이 출력으로 이슈를 올리고 @멘션한다 → GitHub 알림 메일로 도착한다.
  python3 report.py --part title
  python3 report.py --part body --status failed --note "작업 상태 failure: <run URL>"
  python3 report.py                # 제목과 본문을 함께 출력
"""
import argparse
import datetime as dt
import glob
import os
import re
import subprocess
import sys

REPO_URL_DEFAULT = "https://github.com/Gooreum/claude-daily-lab"


def sh(*args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return ""


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def section(md, n):
    m = re.search(rf"^## {n}\..*?$(.*?)(?=^## \d+\.|\Z)", md, re.S | re.M)
    return m.group(1).strip() if m else ""


def build(root, date, status, note):
    days = sorted(glob.glob(os.path.join(root, "days", f"{date}-*")))
    news_path = os.path.join(root, "news", f"{date}.md")
    news = read(news_path)
    repo = os.environ.get("DAILY_LAB_REPO_URL", REPO_URL_DEFAULT)
    lines, subject_bits = [], []

    if days:
        d = days[0]
        slug = os.path.basename(d)[len(date) + 1:]
        readme_root = read(os.path.join(root, "README.md"))
        row = next((ln for ln in readme_root.splitlines() if f"days/{date}-{slug}/" in ln), "")
        cols = [c.strip() for c in row.strip("|").split("|")] if row else []
        kind = cols[2] if len(cols) > 2 else "?"
        oneliner = cols[4] if len(cols) > 4 else ""
        incomplete = oneliner.startswith("⚠")
        md = read(os.path.join(d, "README.md"))
        tests = section(md, 5)
        tally = re.findall(r"^.*(?:통과|passed|PASS).*$", tests, re.M)
        what = section(md, 1).split("\n\n")[0]
        subject_bits.append(f"{'⚠ 미완 ' if incomplete else ''}{slug}")
        lines += [
            f"■ 만든 것: [{slug}]({repo}/tree/main/days/{date}-{slug}) ({kind})",
            f"  {oneliner}" if oneliner else "",
            "",
            what,
            "",
            "■ 테스트: " + (tally[0].strip("` ") if tally else "README 5절 참고")
            + f" ([README]({repo}/blob/main/days/{date}-{slug}/README.md))",
        ]
    else:
        subject_bits.append("결과물 없음")
        lines.append("■ 오늘 날짜의 days/ 폴더가 없다. 루틴이 중간에 멈췄거나 --no-build로 돌았다.")

    if news:
        items = re.findall(r"^## \d+\. (.+)$", news, re.M)
        pick = re.search(r"^## 오늘의 선정\s*$(.*?)(?=^## |\Z)", news, re.S | re.M)
        lines += ["", f"■ 소식 {len(items)}건 ([news/{date}.md]({repo}/blob/main/news/{date}.md))"]
        lines += [f"  - {t}" for t in items[:12]]
        if pick:
            lines += ["", "■ 오늘의 선정", "  " + pick.group(1).strip()]
    else:
        lines += ["", "■ 오늘 news 파일 없음"]

    head = sh("git", "-C", root, "log", "-1", "--format=%H %s")
    pushed = sh("git", "-C", root, "status", "-sb").splitlines()[:1]
    if head:
        sha, msg = (head.split(" ", 1) + [""])[:2]
        lines += ["", f"■ 마지막 커밋: [{sha[:7]}]({repo}/commit/{sha}) {msg}"]
    else:
        lines += ["", "■ 마지막 커밋: ?"]
    if pushed:
        lines.append(f"  브랜치 상태: {pushed[0]}" + (" (푸시 안 됨)" if "ahead" in pushed[0] else ""))
    if note:
        lines += ["", f"■ 메모: {note}"]
    lines += ["", f"■ 저장소: [{repo.split('github.com/')[-1]}]({repo}) · [결과물 목록]({repo}#결과물-목록)"]

    tag = {"ok": "", "failed": "❌ 실패 · ", "skipped": "건너뜀 · "}[status]
    subject = f"[daily-lab] {date} {tag}{' / '.join(subject_bits)}"
    body = "\n".join((l + "  ") if l and not l.lstrip().startswith("- ") else l for l in lines if l is not None)
    return subject, body.strip() + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="daily-lab 요약")
    ap.add_argument("--date", default=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d"))
    ap.add_argument("--root", default=sh("git", "rev-parse", "--show-toplevel") or ".")
    ap.add_argument("--status", choices=["ok", "failed", "skipped"], default="ok")
    ap.add_argument("--note", default="")
    ap.add_argument("--part", choices=["title", "body", "all"], default="all")
    a = ap.parse_args(argv)

    subject, body = build(a.root, a.date, a.status, a.note)
    if a.part == "title":
        print(subject)
    elif a.part == "body":
        print(body, end="")
    else:
        print(f"{subject}\n\n{body}", end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""report.py — /daily-lab이 끝난 뒤 "한눈에 보는" 요약 알림(제목·본문)을 만든다 (표준 라이브러리만).

재료는 그날 폴더의 SUMMARY.md(스킬이 4·5단계에서 쓴다). 형식:
  - 한 줄: <무엇을 만들었나, 쉬운 말 한 문장>
  - 왜: <계기 한 문장>
  - 쓰는 법: <한 문장>
  - 결과: <✅/⚠/❌로 시작하는 한 문장>
SUMMARY.md가 없으면 루트 README 표의 한 줄 설명으로 대신한다.

GitHub Actions의 "요약 알림" 단계가 이 출력으로 이슈를 올리고 @멘션한다 → GitHub 알림 메일로 도착한다.
  python3 report.py --part title
  python3 report.py --part body --status failed --run-url <URL>
"""
import argparse
import datetime as dt
import glob
import os
import re
import subprocess
import sys

REPO_URL_DEFAULT = "https://github.com/Gooreum/claude-daily-lab"
FIELDS = {"한 줄": "line", "왜": "why", "쓰는 법": "how", "결과": "result"}


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def summary_fields(folder):
    out = {}
    for m in re.finditer(r"^\s*-\s*(한 줄|왜|쓰는 법|결과)\s*:\s*(.+)$", read(os.path.join(folder, "SUMMARY.md")), re.M):
        out[FIELDS[m.group(1)]] = m.group(2).strip()
    return out


def fallback_line(root, date, slug):
    row = next((ln for ln in read(os.path.join(root, "README.md")).splitlines()
                if f"days/{date}-{slug}/" in ln), "")
    cols = [c.strip() for c in row.strip("|").split("|")]
    text = cols[4] if len(cols) > 4 else slug
    text = re.split(r"[(.。]", text)[0].strip()  # 괄호·마침표 앞까지만
    return text[:60]


def build(root, date, status, run_url):
    repo = os.environ.get("DAILY_LAB_REPO_URL", REPO_URL_DEFAULT)
    md = dt.date.fromisoformat(date)
    tag = f"[Daily Lab {md.month}/{md.day}]"
    days = sorted(glob.glob(os.path.join(root, "days", f"{date}-*")))
    run = f"[실행 기록]({run_url})" if run_url else ""

    if not days:
        title = f"{tag} ❌ 오늘은 못 만들었어요"
        body = ["### 오늘은 결과물이 없어요",
                "루틴이 중간에 멈췄습니다." + (f" 원인은 {run}에서 볼 수 있어요." if run else "")]
        return title, "\n\n".join(body) + "\n"

    folder = days[0]
    slug = os.path.basename(folder)[len(date) + 1:]
    f = summary_fields(folder)
    line = f.get("line") or fallback_line(root, date, slug)
    result = f.get("result", "")
    warn = "❌ " if status == "failed" else ("⚠ " if result.startswith(("⚠", "❌")) else "")
    title = f"{tag} {warn}{line}"

    body = ["### 오늘 만든 것", f"**{line}**", ""]
    for key, label in (("why", "왜"), ("how", "쓰는 법"), ("result", "결과")):
        if f.get(key):
            body.append(f"- **{label}:** {f[key]}")
    if status == "failed":
        body.append(f"- **주의:** 루틴이 끝까지 가지 못했습니다. {run}".rstrip())
    body += ["", f"[자세히 보기 →]({repo}/tree/main/days/{date}-{slug})"]
    return title, "\n".join(body).strip() + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="daily-lab 한눈 요약")
    ap.add_argument("--date", default=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d"))
    ap.add_argument("--root", default=subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                                     capture_output=True, text=True).stdout.strip() or ".")
    ap.add_argument("--status", choices=["ok", "failed"], default="ok")
    ap.add_argument("--run-url", default="")
    ap.add_argument("--part", choices=["title", "body", "all"], default="all")
    a = ap.parse_args(argv)

    title, body = build(a.root, a.date, a.status, a.run_url)
    if a.part == "title":
        print(title)
    elif a.part == "body":
        print(body, end="")
    else:
        print(f"{title}\n\n{body}", end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())

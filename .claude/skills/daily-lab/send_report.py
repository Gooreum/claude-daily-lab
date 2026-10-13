#!/usr/bin/env python3
"""send_report.py — /daily-lab이 끝난 뒤 오늘 결과를 요약해 메일로 보낸다 (표준 라이브러리만).

설정은 환경변수로만 받는다. 저장소가 공개라 주소·비밀번호를 파일로 커밋하지 않는다.
  DAILY_LAB_SMTP_USER   보내는 계정 (예: Gmail 주소)
  DAILY_LAB_SMTP_PASS   SMTP 비밀번호 (Gmail은 앱 비밀번호)
  DAILY_LAB_MAIL_TO     받는 주소 (없으면 SMTP_USER에게)
  DAILY_LAB_SMTP_HOST   기본 smtp.gmail.com
  DAILY_LAB_SMTP_PORT   기본 465 (SSL)
로컬에서는 ~/.config/daily-lab/mail.env(KEY=VALUE 줄)도 읽는다. 이미 있는 환경변수가 우선한다.

설정이 없으면 "메일 건너뜀"만 찍고 exit 0 (루틴을 실패시키지 않는다). 보내기에 실패하면 exit 1.
  python3 send_report.py --dry-run              # 보내지 않고 제목·본문만 출력
  python3 send_report.py --date 2026-10-12
  python3 send_report.py --status failed --note "CI 작업 실패: <run URL>"
"""
import argparse
import datetime as dt
import glob
import os
import re
import smtplib
import ssl
import subprocess
import sys
from email.message import EmailMessage

REPO_URL_DEFAULT = "https://github.com/Gooreum/claude-daily-lab"


def load_env_file(path=os.path.expanduser("~/.config/daily-lab/mail.env")):
    if not os.path.isfile(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


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
            f"■ 만든 것: {slug} ({kind})",
            f"  {oneliner}" if oneliner else "",
            "",
            what,
            "",
            "■ 테스트: " + (tally[0].strip("` ") if tally else "README 5절 참고"),
            f"■ 폴더: {repo}/tree/main/days/{date}-{slug}",
        ]
    else:
        subject_bits.append("결과물 없음")
        lines.append("■ 오늘 날짜의 days/ 폴더가 없다. 루틴이 중간에 멈췄거나 --no-build로 돌았다.")

    if news:
        items = re.findall(r"^## \d+\. (.+)$", news, re.M)
        pick = re.search(r"^## 오늘의 선정\s*$(.*?)(?=^## |\Z)", news, re.S | re.M)
        lines += ["", f"■ 소식 {len(items)}건 ({repo}/blob/main/news/{date}.md)"]
        lines += [f"  - {t}" for t in items[:12]]
        if pick:
            lines += ["", "■ 오늘의 선정", "  " + pick.group(1).strip()]
    else:
        lines += ["", "■ 오늘 news 파일 없음"]

    head = sh("git", "-C", root, "log", "-1", "--format=%h %s")
    pushed = sh("git", "-C", root, "status", "-sb").splitlines()[:1]
    lines += ["", f"■ 마지막 커밋: {head or '?'}"]
    if pushed:
        lines.append(f"  브랜치 상태: {pushed[0]}" + (" (푸시 안 됨)" if "ahead" in pushed[0] else ""))
    if note:
        lines += ["", f"■ 메모: {note}"]

    tag = {"ok": "", "failed": "❌ 실패 · ", "skipped": "건너뜀 · "}[status]
    subject = f"[daily-lab] {date} {tag}{' / '.join(subject_bits)}"
    return subject, "\n".join(l for l in lines if l is not None).strip() + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="daily-lab 요약 메일")
    ap.add_argument("--date", default=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d"))
    ap.add_argument("--root", default=sh("git", "rev-parse", "--show-toplevel") or ".")
    ap.add_argument("--status", choices=["ok", "failed", "skipped"], default="ok")
    ap.add_argument("--note", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    subject, body = build(a.root, a.date, a.status, a.note)
    if a.dry_run:
        print(f"Subject: {subject}\n\n{body}")
        return 0

    load_env_file()
    user, pw = os.environ.get("DAILY_LAB_SMTP_USER"), os.environ.get("DAILY_LAB_SMTP_PASS")
    if not user or not pw:
        print("메일 건너뜀: DAILY_LAB_SMTP_USER/PASS 설정 없음")
        return 0
    to = os.environ.get("DAILY_LAB_MAIL_TO") or user
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.set_content(body)
    host = os.environ.get("DAILY_LAB_SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("DAILY_LAB_SMTP_PORT", "465"))
    try:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as s:
            s.login(user, pw)
            s.send_message(msg)
    except Exception as e:
        print(f"메일 전송 실패: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(f"메일 보냄: {subject}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

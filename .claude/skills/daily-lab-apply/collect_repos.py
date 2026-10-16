#!/usr/bin/env python3
"""collect_repos.py — 최근 활동한 내 저장소의 "적용 판단용 스냅샷"을 받아 둔다 (표준 라이브러리만).

Claude는 이 스냅샷만 읽고 토큰·네트워크 없이 적용안을 쓴다. 저장소마다 <out>/<이름>/ 아래에:
  meta.json   이름·공개 여부·설명·언어·최근 푸시·최근 커밋 제목
  tree.txt    파일 경로 목록(앞 400개)
  files/      README·CLAUDE.md·의존성 파일·워크플로 같은 핵심 파일(파일당 8KB까지)
<out>/index.json 에 저장소 목록을 남긴다.

  GH_TOKEN=<읽기 전용 토큰> python3 collect_repos.py --out .apply/repos [--days 21] [--max 15]
"""
import argparse
import base64
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"
SELF = "claude-daily-lab"
KEY_FILES = re.compile(
    r"^(README(\.\w+)?|CLAUDE\.md|AGENTS\.md|package\.json|pyproject\.toml|requirements\.txt|Package\.swift|"
    r"Cargo\.toml|go\.mod|Gemfile|Podfile|app\.json|\.claude/settings\.json|\.claude/(skills|agents|commands)/.+\.md|"
    r"\.mcp\.json|\.github/workflows/[^/]+\.ya?ml)$", re.I)
MAX_FILE = 8000
MAX_KEY_FILES = 25


def get(path, token):
    req = urllib.request.Request(API + path, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "daily-lab-apply"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def active_repos(token, days, limit):
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    repos = get("/user/repos?affiliation=owner&sort=pushed&per_page=100", token)
    out = []
    for r in repos:
        pushed = dt.datetime.fromisoformat(r["pushed_at"].replace("Z", "+00:00"))
        if r["name"] == SELF or r["fork"] or r["archived"] or pushed < cutoff:
            continue
        out.append(r)
    return out[:limit]


def snapshot(r, token, out_dir):
    full, branch = r["full_name"], r["default_branch"]
    d = os.path.join(out_dir, r["name"])
    os.makedirs(os.path.join(d, "files"), exist_ok=True)
    try:
        commits = [c["commit"]["message"].splitlines()[0] for c in get(f"/repos/{full}/commits?per_page=15", token)]
    except urllib.error.HTTPError:
        commits = []  # 빈 저장소는 409
    try:
        tree = [t["path"] for t in get(f"/repos/{full}/git/trees/{branch}?recursive=1", token)["tree"] if t["type"] == "blob"]
    except urllib.error.HTTPError:
        tree = []
    with open(os.path.join(d, "tree.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(tree[:400]) + ("\n… (생략)\n" if len(tree) > 400 else "\n"))
    saved = []
    for path in [p for p in tree if KEY_FILES.match(p)][:MAX_KEY_FILES]:
        try:
            blob = get(f"/repos/{full}/contents/{path}?ref={branch}", token)
            text = base64.b64decode(blob.get("content", "")).decode("utf-8", "replace")[:MAX_FILE]
        except (urllib.error.HTTPError, ValueError):
            continue
        dest = os.path.join(d, "files", path.replace("/", "__"))
        with open(dest, "w", encoding="utf-8") as f:
            f.write(text)
        saved.append(path)
    meta = {"name": r["name"], "visibility": "private" if r["private"] else "public",
            "description": r["description"] or "", "language": r["language"] or "",
            "pushed_at": r["pushed_at"], "recent_commits": commits, "files": saved}
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser(description="활성 저장소 스냅샷")
    ap.add_argument("--out", required=True)
    ap.add_argument("--days", type=int, default=21)
    ap.add_argument("--max", type=int, default=15)
    a = ap.parse_args(argv)
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        print("GH_TOKEN이 없습니다.", file=sys.stderr)
        return 2
    os.makedirs(a.out, exist_ok=True)
    index = []
    for r in active_repos(token, a.days, a.max):
        m = snapshot(r, token, a.out)
        index.append({k: m[k] for k in ("name", "visibility", "pushed_at")})
        print(f"{m['visibility']:7s} {m['name']} (파일 {len(m['files'])}개, 커밋 {len(m['recent_commits'])}개)")
    with open(os.path.join(a.out, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())

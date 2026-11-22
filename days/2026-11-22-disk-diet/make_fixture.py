#!/usr/bin/env python3
"""test.sh용 가짜 홈 폴더를 만든다. 사용: make_fixture.py DIR  (DIR은 비어 있어야 한다)"""
import json
import os
import sys
import time

root = sys.argv[1]
DAY = 86400
now = time.time()


def w(rel, data, age_days=0, mode="w"):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, mode) as f:
        f.write(data)
    t = now - age_days * DAY
    os.utime(p, (t, t))
    return p


def img(n, media="image/png"):
    return {"type": "image", "source": {"type": "base64", "media_type": media, "data": "A" * n}}


def line(obj):
    return json.dumps(obj, ensure_ascii=False) + "\n"


# 세션 A: 최상위 content의 이미지 2장(300000 + 200000자), 한글 텍스트 포함
a = line({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "화면 봐 줘"}, img(300000)]}})
a += line({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "봤어요"}]}})
# tool_result 안쪽에 중첩된 이미지
a += line({"type": "user", "message": {"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": "t1", "content": [img(200000, "image/jpeg")]}]}})
# 이미지 표시는 있지만 JSON이 깨진 줄(잘린 기록)
a += '{"type":"user","message":{"content":[{"type":"image","source":{"type":"base64","data":"AAAA\n'
w("home/.claude/projects/-repo-a/aaaa.jsonl", a)

# 세션 B: 이미지 없음
w("home/.claude/projects/-repo-b/bbbb.jsonl", line({"type": "user", "message": {"role": "user", "content": "hi"}}) * 50)
# 세션 C: 작은 이미지 1장
w("home/.claude/projects/-repo-b/cccc.jsonl", line({"type": "user", "message": {"role": "user", "content": [img(1000)]}}))

# 설정·인증: 정리 후보로 나오면 안 된다
w("home/.claude/settings.json", '{"permissions":{"deny":["Bash(rm -rf *)"]}}\n', age_days=100)
w("home/.claude/.credentials.json", '{"token":"not-a-real-token"}\n', age_days=100)

# worktree: old는 40일 전(node_modules 100000바이트), new는 오늘
w("home/.claude/worktrees/old-wt/src/app.py", "x" * 2000, age_days=40)
w("home/.claude/worktrees/old-wt/node_modules/pkg/index.js", "y" * 100000, age_days=40)
w("home/.claude/worktrees/new-wt/src/app.py", "z" * 3000, age_days=0)

# 옛 실행 파일 4개(각 50000바이트), 오래된 순 1.0.1 → 1.0.4
for i, age in ((1, 40), (2, 30), (3, 20), (4, 1)):
    w(f"home/.local/share/claude/versions/1.0.{i}", "b" * 50000, age_days=age)

# 심볼릭 링크: 밖의 큰 파일을 가리키는 링크와 자기 자신을 가리키는 순환 링크 — 크기에 들어가면 안 되고 멈추면 안 된다
outside = w("outside/big.bin", "q" * 900000)
wt = os.path.join(root, "home/.claude/worktrees/old-wt")
os.symlink(outside, os.path.join(wt, "link-to-big"))
os.symlink(wt, os.path.join(wt, "loop"))

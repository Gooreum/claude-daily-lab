#!/usr/bin/env bash
# status.sh — /daily-lab 스킬이 시작할 때 읽는 현재 상태. 단일 명령으로 호출되도록 스크립트로 뺐다
# (스킬 본문의 !`…` 안에 $(…)나 ||가 있으면 헤드리스(-p)에서 권한 검사에 걸려 스킬 전체가 중단된다).
set -u
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
today="$(TZ=Asia/Seoul date +%F)"
echo "- 오늘(Asia/Seoul): $today"
echo "- 저장소 루트: $(pwd)"
echo "- 브랜치: $(git branch --show-current 2>/dev/null || echo '?')"
echo "- 오늘 폴더: $(ls -d days/$today-* 2>/dev/null | tr '\n' ' ' || true)$( [ -z "$(ls -d days/$today-* 2>/dev/null)" ] && echo '(없음)')"
echo "- 오늘 news: $( [ -f news/$today.md ] && echo news/$today.md || echo '(없음)')"
echo "- 최근 결과물 5개: $(grep -oE '^\| [0-9-]+ \| \[[a-z0-9-]+\]' README.md | sed -E 's/^\| ([0-9-]+) \| \[([a-z0-9-]+)\]/\2(\1)/' | head -5 | tr '\n' ' ')"
echo "- 도구: claude $(claude --version 2>/dev/null | head -1 || echo 없음) · $(python3 --version 2>&1) · node $(node --version 2>&1)"
echo "- git 사용자: $(git config user.name || echo '(비어 있음)') <$(git config user.email || echo '비어 있음')>"

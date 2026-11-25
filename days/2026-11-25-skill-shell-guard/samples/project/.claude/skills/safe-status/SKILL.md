---
name: safe-status
description: 저장소 상태를 요약한다. 읽기 전용 명령만 쓴다.
---

# 상태 요약

현재 브랜치와 변경 파일:

!`git status --short`

최근 커밋 다섯 개: !`git log --oneline -5`

```!
git diff --stat HEAD
ls -la 2>/dev/null
```

위 출력을 보고 한 문단으로 요약한다.

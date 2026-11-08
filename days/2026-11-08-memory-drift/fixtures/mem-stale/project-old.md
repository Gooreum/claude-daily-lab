---
name: project-old
description: 낡은 주장이 섞인 노트
metadata:
  type: project
---

설정 로딩은 `lib/app.py` 에서 한다.
재시도는 `retry_with_backoff()` 가 맡는다.
환경 변수 `APP_CACHE_DIR` 로 캐시 위치를 바꾼다.
예전 문서는 `docs/old-setup.md` 에 있다.
릴리스 스크립트는 `scripts/release.sh` 이고 옵션은 `--dry-run` 이다.
수정 커밋은 `__FAKESHA__` 이다.

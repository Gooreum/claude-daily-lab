---
name: project-config
description: 설정 로딩 코드의 위치와 재시도 상한
metadata:
  type: project
---

설정은 `src/app.py` 의 `load_config()` 가 읽는다. 재시도 상한은 `MAX_RETRIES` 상수다.
실행은 `scripts/run.sh` 이고 설치 안내는 `docs/setup.md` 에 있다. 옵션은 `--verbose` 하나다.
외부 서비스 `legacy_gateway` 는 이 저장소 밖이라 표시를 붙인다. `legacy_gateway` <!-- drift:ignore -->
```
`not/in/code.py` 는 코드 펜스 안이라 검사하지 않는다
```

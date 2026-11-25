---
name: mixed
description: 허용·되묻기·거절이 섞인 예시.
---

의존성: !`npm install`

테스트 통과 확인: !`npm test`

프로젝트 스크립트(본문이 안전): !`bash scripts/ok.sh`

프로젝트 스크립트(본문에 위험한 줄): !`bash scripts/bad.sh`

없는 스크립트: !`bash scripts/nope.sh`

인자로 받은 명령: !`$ARGUMENTS`

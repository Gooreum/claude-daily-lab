---
name: feedback-testing
description: 통합 테스트는 목 대신 실제 데이터베이스에 붙어 돌린다
metadata:
  type: feedback
---

테스트에서 DB를 목으로 바꾸지 않는다.

**Why:** 지난 분기 목 테스트는 통과했는데 마이그레이션이 운영에서 깨졌다.
**How to apply:** 통합 테스트를 쓸 때 테스트 컨테이너 DB를 쓴다.

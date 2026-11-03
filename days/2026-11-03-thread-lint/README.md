# thread-lint

Messages API message threads(베타) 요청 로그를 문서의 규칙으로 점검하는 CLI. 키·네트워크 없이 돈다.

## 1. 무엇을 만들었나
CLI 스크립트(`thread_lint.py`, 표준 라이브러리만). 요청·응답을 한 줄씩 적은 JSONL 로그를 읽어 message threads 규칙 위반 11가지(TL01~TL11)를 찾아 `파일:줄: 수준 코드: 메시지`로 보여 준다. `--stats`는 thread로 보낸 요청 바이트와 "매번 전체 대화를 다시 보냈다면"의 추정치를 비교하고, `--json`은 기계가 읽는 출력을, `--fail-on warn`은 경고도 실패로 취급한다.

## 2. 왜 만들었나
- 계기: 「Messages API message threads 베타 공식 공지」(platform.claude.com 릴리스 노트, 2026-11-02). 10-24에 SDK 지원은 다뤘지만, 이번에 공식 문서가 나왔다.
- `thread` 한 줄로 요청이 작아지지만, 어기면 400·404가 나는 규칙이 많다: continue에 `system`·`tools` 금지, 고정 필드(`model`·`thinking` 등)는 매 요청 동일, 응답 id는 한 번만 이어가기, 5분 만료, 중단점 4개 상한. 문서가 "앱이 원본 대화를 직접 보관하고 replay 경로를 처음부터 만들라"고 하는 만큼, 실제 호출 전에 로그로 걸러 주는 도구가 쓸모 있다고 판단했다. news/2026-11-03.md 1번의 첫 적용안.

## 3. 어떻게 만들었나
1. 문서(message-threads 페이지)의 "What to send on each request", 스트리밍, 복구 절을 읽고 코드로 옮길 수 있는 규칙만 골랐다. 서버 내부 사정(저장 여부 등)은 로그로 알 수 없어 제외했다.
2. 응답 id → 대화(chain) 표를 만들어 각 continue가 어느 create에 속하는지 따라간다. create 때의 고정 필드 지문(`model`, `tool_choice`, `thinking`, `mcp_servers`(인증 토큰 제외), `context_management`, `output_config`, `container.skills`, 최상위 `cache_control`, 베타 헤더 집합)을 저장해 두고 continue마다 비교한다.
3. 중단점 수는 요청 안의 `cache_control`을 재귀로 세고, continue에서는 문서 설명대로 create의 `system`·`tools` 몫을 더한다.
4. 시간 규칙(5분 만료, `message_stop` 이전 continue)은 로그의 선택 필드 `ts`·`message_stop_ts`가 있을 때만 켠다. 없으면 건너뛴다.
5. 결정: 만료·replay 관련은 서버 상태를 모르니 error가 아니라 warn으로 둔다(404가 날 "수 있는" 상황). 형식·필드 규칙은 400이 확실하니 error.
6. 막힌 점: 처음에는 404 응답을 받은 continue도 "이어진 것"으로 셌다. 성공(2xx)한 continue만 `continued`에 기록하도록 고쳤다.

## 4. 사용법
```bash
python3 thread_lint.py LOG.jsonl [--stats] [--json] [--fail-on warn]
```
로그 한 줄의 형식(요청 본문은 Messages API 그대로):
```json
{"ts": 0, "betas": ["message-threads-2026-08-12"],
 "request": {"model": "...", "max_tokens": 1024, "messages": [...], "thread": {"type": "create"}},
 "response": {"id": "msg_1", "status": 200, "stop_reason": "end_turn", "message_stop_ts": 2, "content": [...]}}
```
종료 코드: 0 통과 / 1 지적 있음 / 2 입력 오류. 규칙 코드: TL01 베타 헤더 없음, TL02 continue에 system·tools, TL03 고정 필드 불일치, TL04 id·type 오류, TL05 이미 이어진 id 재사용, TL06 5분 초과, TL07 중단점 4개 초과, TL08 continue가 assistant로 시작, TL09 pause_turn 뒤 새 메시지, TL10 404 받은 id 재시도, TL11 message_stop 전에 continue.

## 5. 테스트 결과
`bash test.sh` (키·모델 불필요; 이 도구는 모델을 부르지 않아 e2e.sh 없음):
```
ok   good: exit 0
ok   good: create 1 / continue 2, 지적 0
ok   good: --stats 가 절감 바이트를 보여 줌
ok   bad: exit 1
ok   TL01 베타 헤더 없음
ok   TL02 continue 에 system
ok   TL03 고정 필드(model, betas) 불일치
ok   TL04 thread.type 오류
ok   TL05 이미 이어진 id 재사용
ok   TL06 5분 초과 경고
ok   TL07 중단점 5개
ok   TL08 assistant 로 시작하는 continue
ok   TL09 pause_turn 뒤 새 메시지
ok   TL10 404 받은 id 재시도
ok   TL11 message_stop 전 continue
ok   요약 줄: error 10 · warn 4
ok   --json: 파싱 가능하고 findings 14건
ok   MCP authorization_token 변경, max_tokens 변경은 허용
ok   MCP 서버 URL 변경은 mcp_servers 불일치
ok   경고만 있으면 기본은 exit 0
ok   --fail-on warn 이면 exit 1
ok   thread 없는 요청은 점검 대상이 아님
ok   깨진 JSON → exit 2
ok   없는 파일 → exit 2
---
통과 24 / 실패 0
```
나쁜 로그의 출력 일부(`python3 thread_lint.py fixtures/bad.jsonl`):
```
fixtures/bad.jsonl:1: error TL07: cache_control 중단점 5개 (상한 4, thread_unsupported_request)
fixtures/bad.jsonl:2: error TL01: thread 요청인데 베타 헤더 message-threads-2026-08-12 가 없다
fixtures/bad.jsonl:2: error TL02: continue 요청에 system 가 있다 (null 도 400)
fixtures/bad.jsonl:2: error TL03: 고정 필드가 create 와 다르다 (thread_fingerprint_mismatch): model, betas
fixtures/bad.jsonl:4: error TL05: 응답 msg_1 는 이미 3줄에서 이어졌다 (thread_already_continued) — 항상 최신 응답 id 에서 이어야 한다
fixtures/bad.jsonl:5: error TL08: continue 의 첫 메시지가 assistant 다 — 이전 응답을 다시 보내면 안 된다 (새 메시지만)
fixtures/bad.jsonl:6: warn  TL11: 직전 응답의 message_stop 보다 먼저 continue 를 보냈다 (404 위험)
fixtures/bad.jsonl:6: error TL09: pause_turn 응답 뒤에는 messages 를 비워 보내야 한다 (새 user 메시지는 거절된다)
fixtures/bad.jsonl:7: warn  TL06: 직전 요청 뒤 875초 — 5분을 넘어 만료됐을 수 있다 (404 → create 로 replay 필요)
fixtures/bad.jsonl:7: error TL05: 응답 msg_3 는 이미 5줄에서 이어졌다 (thread_already_continued) — 항상 최신 응답 id 에서 이어야 한다
fixtures/bad.jsonl:8: warn  TL06: 직전 요청 뒤 880초 — 5분을 넘어 만료됐을 수 있다 (404 → create 로 replay 필요)
fixtures/bad.jsonl:8: error TL05: 응답 msg_3 는 이미 5줄에서 이어졌다 (thread_already_continued) — 항상 최신 응답 id 에서 이어야 한다
fixtures/bad.jsonl:8: warn  TL10: 7줄에서 404 를 받은 id 로 다시 continue 했다 — 전체 대화를 create 로 다시 보내야 한다
fixtures/bad.jsonl:9: error TL04: thread.type 은 create 또는 continue 여야 한다 (받은 값: 'continuee')
thread 요청 9건 (create 1, continue 7) · error 10 · warn 4
```
CI에서는 위 `test.sh`만 돈다.

## 6. 한계와 다음 아이디어
- 로그는 직접 남겨야 한다. 실제 SDK 호출을 감싸 이 형식으로 기록하는 어댑터(`client.beta.messages.create` 래퍼)는 만들지 않았다. 다음 후보.
- 규칙은 2026-11-03 시점 문서 기준이다. 베타라 바뀔 수 있다. 폴백 모델(`fallbacks`) 규칙과 thinking 블록 무효화(`system`·`tools` 변경 시)는 점검하지 않는다.
- 유료 호출 없이 만든 합성 로그로만 검증했다. 실제 API의 `thread_fingerprint_mismatch`가 비교하는 필드와 정확히 같은지는 확인하지 않았다.
- `--stats`의 "전체 재전송 추정"은 로그에 응답 `content`가 있어야 정확하다.
- 이어서: `cost-top`(10-30)과 합쳐 "thread로 바꾸면 줄어드는 토큰·바이트" 보고서.

## 7. 출처
- https://platform.claude.com/docs/en/release-notes/overview — 2026-11-02 message threads 베타 공지
- https://platform.claude.com/docs/en/build-with-claude/message-threads — 규칙 상세
- https://github.com/anthropics/anthropic-sdk-python/releases/tag/v2.4.0 — 같은 날 나온 SDK

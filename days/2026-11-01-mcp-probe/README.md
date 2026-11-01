# mcp-probe

## 1. 무엇을 만들었나
stdio MCP 서버를 실제로 띄워 JSON-RPC 메시지를 보내 보고, 프로토콜 최소 요건 12가지(P01~P12)를 지키는지 검사하는 CLI 스크립트(`mcp_probe.py`, 표준 라이브러리만 사용)다. 서버 명령을 `--` 뒤에 주면 error/warn 목록과 종료 코드(error 있으면 1)를 돌려줘 CI에도 넣을 수 있다. 키·모델·네트워크가 필요 없다.

## 2. 왜 만들었나
- 계기: dev.to 10-31 "A zero-dependency MCP server in one file: what the protocol actually needs" (news/2026-11-01.md 3번). `initialize`·`tools/list`·`tools/call`·`ping` 넷이면 도구 서버가 되지만, 모르는 도구를 `isError` 결과로 답하는 실수나 stdout에 로그를 섞는 실수를 흔히 한다는 내용이다.
- 이 저장소의 앞선 MCP 결과물(`secret-envoy` 10-11, `mcp-rule-audit` 10-17)은 서버를 만들거나 허용 규칙을 점검했을 뿐 서버가 명세를 지키는지는 보지 않았다. 그 빈자리를 채운다.

## 3. 어떻게 만들었나
1. 글이 짚은 함정과 JSON-RPC 기본 규칙에서 검사 12개를 뽑았다 (아래 표).
2. `Server` 클래스가 서버를 서브프로세스로 띄우고, 읽기 스레드가 stdout 줄을 JSON이면 큐에, 아니면 `bad_lines`에 쌓는다. 요청은 `pending` 사전으로 id를 추적해 응답을 짝짓고, 짝이 없는 응답은 `spurious`에 모아 P03·P10 판단에 쓴다.
3. 검사는 한 서버에 한 번 순서대로 흘려보낸다: initialize → 알림 → ping → tools/list → 모르는 메서드 → 모르는 도구 → 필수 인자 누락 → 연달아 두 요청 → 깨진 JSON → stdin 닫기.
4. 설계 결정:
   - 필수 인자 누락(P08)은 프로토콜 오류와 `isError` 결과 **둘 다 허용**하고 "성공으로 답하면" 실패로 본다. 입력 검증 오류를 도구 실행 오류로 돌려 모델이 고치게 하는 쪽을 권하는 명세 판본이 있어, 글의 단정(-32602 필수)을 그대로 따르지 않았다. 반면 모르는 도구(P07)는 글대로 -32602를 기대하되 isError면 error가 아니라 warn으로 둔다.
   - 시간 초과·서버 종료는 "검사 실패"로 기록하고 나머지 검사를 접는다(initialize 실패 시 1개에서 중단).
5. 픽스처: `good_server.py`·`good_server.js`(정상), 결함 서버 4개(`bad`·`crash`·`silent`·`strid`). `bad_server.py`는 코드마다 결함을 하나씩 심었다.

| 코드 | 검사 | 등급 |
|---|---|---|
| P01 | initialize 결과에 protocolVersion·capabilities·serverInfo | error |
| P02 | stdout에 JSON이 아닌 줄 없음 | error |
| P03 | 알림·요청 안 한 id에 응답 안 함 | error |
| P04 | ping이 `{}`로 답 | warn |
| P05 | tools/list의 name·inputSchema(type=object) | error |
| P06 | 모르는 메서드에 오류 (-32601 아니면 warn) | error/warn |
| P07 | 모르는 도구에 -32602 (isError면 warn) | error/warn |
| P08 | 필수 인자 빠진 호출이 성공으로 끝나지 않음 | error |
| P09 | 연달아 보낸 두 요청의 응답이 id로 짝지어짐 | error |
| P10 | 응답의 jsonrpc 값·id 타입 일치 | error |
| P11 | 깨진 JSON 한 줄 뒤에도 서버가 살아 있음 | error |
| P12 | stdin을 닫으면 종료 | warn |

## 4. 사용법
```bash
cd days/2026-11-01-mcp-probe
python3 mcp_probe.py -- node my-server.js            # 서버 명령을 -- 뒤에
python3 mcp_probe.py --timeout 10 --strict -- python3 my_server.py   # warn도 실패로
python3 mcp_probe.py --json -- <명령>                  # CI·스크립트용
python3 mcp_probe.py --list                          # 검사 12개 목록
```
종료 코드: 0 통과, 1 error(또는 --strict에서 warn), 2 사용법 오류.

## 5. 테스트 결과
`bash test.sh` (키·모델 없이 실행, CI에서도 돈다):
```
ok   good: exit 0
ok   good: 지적 0건 (검사 12개)
ok   node good: exit 0, 지적 0건 (도구에 required 없으면 P08 건너뜀 → 11개)
ok   bad: exit 1
ok   P01 capabilities·serverInfo 누락
ok   P02 stdout 오염 (시작 메시지 줄)
ok   P03 알림에 응답
ok   P04 ping 결과가 빈 객체 아님 (warn)
ok   P05 inputSchema.type 틀림
ok   P05 name 없는 도구
ok   P06 모르는 메서드에 성공 응답
ok   P07 모르는 도구를 isError로 (warn)
ok   P08 필수 인자 없이 성공
ok   P12 stdin 닫아도 종료 안 함 (warn)
ok   bad: 요약이 error 7 · warn 3
ok   crash: P11 (깨진 JSON에 죽음) exit 1
ok   silent: P01 시간 초과 exit 1, 검사 1개에서 중단
ok   strid: P10 id 타입 불일치
ok   없는 스크립트: P01 error로 끝남 (예외 없음)
ok   없는 실행 파일: P00 error, exit 1
ok   --strict: 정상 서버는 여전히 exit 0
ok   --json: 파싱되고 errors=7, warnings=3
ok   --list: 검사 12개 나열
ok   명령 없이 실행하면 exit 2

통과 24 · 실패 0
```
`bash e2e.sh` (claude CLI 필요, 모델 호출은 없음. 이 세션에서 직접 실행; CI에서는 e2e 미실행):
```
warn  P07: 모르는 도구의 오류 코드가 -32603 (기대 -32602)
warn  P12: stdin을 닫은 뒤 20.0초가 지나도 종료하지 않음
검사 12개 · error 0 · warn 2
exit=0
```

## 6. 한계와 다음 아이디어
- 실제 서버 `claude mcp serve`의 warn 2건은 진단 결과일 뿐이고 서버 쪽 결함이라고 단정하지 않는다. P07의 -32603은 내부 오류 코드이고, P12는 stdin을 닫아도 20초 안에 끝나지 않았다(종료 정리에 시간이 걸리는지, 닫힘을 무시하는지는 가려내지 않았다).
- stdio 전송만 본다. HTTP/SSE 서버, `resources`·`prompts`, 진행 알림, 취소, 로그 알림은 검사하지 않는다.
- P08·P07의 기대값은 명세 판본마다 다를 수 있어 warn/허용 범위로 두었다. 판본별 프로파일(`--spec 2025-06-18`)을 두는 것이 다음 과제다.
- 도구 인자는 필수 항목을 비운 호출만 해 보므로, 인자 타입 검증이나 실제 도구 동작은 확인하지 않는다.
- 다음 아이디어: 통과한 서버의 응답 시간 측정, GitHub Actions용 한 줄 설정 예시, 서버 한 파일을 받아 검사 실패 줄을 가리키는 `--explain`.

## 7. 출처
- https://dev.to/skibuff/a-zero-dependency-mcp-server-in-one-file-what-the-protocol-actually-needs-khj

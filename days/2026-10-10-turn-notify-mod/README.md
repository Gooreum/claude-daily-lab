# turn-notify — 턴 소요 시간·토큰을 보여주고 긴 턴은 네이티브 알림을 보내는 모드

## 1. 무엇을 만들었나
Claude Code 모드(mod) 하나다. 매 턴이 끝나면 답변 아래에 `⏱ 5.3s · in 1.2k · out 300 · cache read 10.0k · claude-haiku-5-5` 같은 한 줄을 붙이고, 턴이 30초 이상 걸렸으면 2.1.295에서 모드에 새로 열린 `$.ui.notify`로 OS 네이티브 알림을 보낸다. `/turnstats` 명령은 세션 누계(턴 수, 중단 횟수, 총 시간, 토큰 합계)를 출력한다. 서브에이전트의 턴은 집계에서 뺀다. `claude plugin test`용 훅 테스트 6개, node 단위 테스트 10개, 실제 세션 e2e 3개가 들어 있다.

## 2. 왜 만들었나
2026-10-08 Claude Code 2.1.295 changelog에 "Added `$.ui.notify` for mods: raises a native notification through your own notification setting"이 들어갔다 ([changelog](https://code.claude.com/docs/en/changelog)). 모드 자체도 10월 1일에 나온 신기능이라 아직 직접 써 본 적이 없었고, "긴 작업이 끝나면 알려 달라"는 건 매일 쓰는 요구라 작게 만들어 보기 좋았다. 같은 날 오전에 만든 훅 프로젝트(onfailure-secret-guard)와 겹치지 않도록 settings 훅이 아닌 모드로 접근했다.

## 3. 어떻게 만들었나
1. **문서 읽기**: mods의 create / events / api / test / reference 페이지에서 파일 구조(`.claude-plugin/plugin.json`, `hooks/hooks.json`의 `modules`, 훅 모듈의 `register(on)`), `turn.complete` 이벤트 필드(`durationMs`, `usage`, `agentId`, `isAborted`), 테스트 킷(`claude-code/testing`의 `test($, on)`, 스텁은 `{ value }`를 돌려줌)을 확인했다.
2. **`$.ui.notify` 확인**: 문서 reference 표(2.1.290 기준)와 GitHub의 `claude-code.d.ts`에는 아직 `notify`가 없었다. 설치된 바이너리에서 `ui.notify` 문자열을 찾아 존재를 확인하고, `claude plugin validate`가 `calls: $.command.register, $.ui.notify`로 인식하는 것으로 최종 확인했다. 시그니처는 `toast(text)`와 같은 형태로 가정했고 테스트 스텁은 `e.text`를 읽는다.
3. **설계 결정**: 순수 함수(포맷·누계·임계값 판단)를 `hooks/format.mjs`로 분리했다. 이유는 CI(ubuntu)에 `claude` CLI가 없어도 node만으로 핵심 로직을 테스트하기 위해서다. 훅 모듈은 상대 경로 import만 허용되므로 `.mjs`를 쓰고 `hooks.json`도 `./register.mjs`를 가리킨다. `turn.complete` 훅은 `await next(e)` 뒤에 `{ ...result, text }`를 돌려줘 다른 모드의 처리를 막지 않는다. `session.start`의 `$.command.register`는 이름 충돌 시 던지므로 try/catch로 감쌌다.
4. **막힌 지점**: `claude -p`로 e2e를 돌리면 "no stdin data received in 3s" 경고가 나왔다. `< /dev/null`을 붙여 해결했다. 또 e2e 도중 Claude Code가 2.1.295에서 2.1.296으로 자동 업데이트됐다. 동작 차이는 없었다.
5. **사용 도구**: Claude Code 2.1.295→2.1.296, `claude plugin validate`, `claude plugin test`, node 22, 모델 claude-haiku-5-5(e2e).

## 4. 사용법
한 세션에만 싣기:
```bash
claude --plugin-dir ./turn-notify
```
그 다음 아무 작업이나 시키면 답변 아래에 `turn-notify: ⏱ …` 줄이 붙는다. 30초 넘게 걸린 턴이 끝나면 OS 알림이 온다(Claude Code의 알림 설정을 따름). `/turnstats`를 치면:
```
turn-notify: 2 turns (1 interrupted) · total 3.5s · in 1.5k · out 300 · cache read 5.0k · cache write 0
```
비대화형으로 확인:
```bash
claude -p "/turnstats" --plugin-dir ./turn-notify < /dev/null
# turn-notify: No turns yet in this session
```
임계값은 `hooks/format.mjs`의 `NOTIFY_AFTER_MS`(기본 30000)로 바꾼다. 모드는 `--plugin-dir`로 실행 중 저장하면 핫 리로드된다.

## 5. 테스트 결과
`bash test.sh` (node 단위 10개 + validate + plugin test 6개):
```
== 1) node 단위 테스트: hooks/format.mjs
  ✅ fmtTokens 경계값 … ✅ notifyText 중단 표시
  node 단위 테스트: 10/10 통과
== 2) claude plugin validate / test
  ✅ claude plugin validate
  (pass) a short turn shows its line and sends no notification
  (pass) a long turn sends one native notification
  (pass) an interrupted turn is marked and still notifies past the threshold
  (pass) a subagent turn is ignored
  (pass) /turnstats sums the main conversation turns
  (pass) session.start registers /turnstats
   6 pass / 0 fail
== 결과: PASS
```
`bash e2e.sh` (실제 Claude Code 2.1.296, 2026-10-10):
```
== 1) claude -p '/turnstats' → 모드의 명령 응답
   | turn-notify: No turns yet in this session
  ✅ /turnstats 응답
== 2) 모드 없이 /turnstats → 알 수 없는 명령 (대조군)
   | `/turnstats` is not installed in this session, so nothing ran.
  ✅ 모드 없을 땐 응답 없음
== 3) 실제 턴 1회 + stream-json으로 turn.complete 결과 텍스트 확인
   | {"type":"system","subtype":"informational","content":"turn-notify+cc-plugin-agents-md: ⏱ 1.3s · in 2 · out 4 · cache read 10.6k · claude-haiku-5-5","level":"notice",...}
  ✅ 턴 요약 줄(⏱) 출력됨
== 결과: pass=3 fail=0
```
stream-json에서 턴 요약 줄이 `system/informational` 이벤트로 나오며, 내장 모드(`cc-plugin-agents-md`)와 합쳐져 `turn-notify+cc-plugin-agents-md:` 접두어가 붙는 것을 볼 수 있다.

## 6. 한계와 다음 아이디어
- `$.ui.notify`의 정확한 옵션(제목, 채널 등)은 이 버전의 타입 선언(대화형 세션에서 `.claude-plugin/types/`에 생성됨)을 읽어 확인해야 한다. 지금은 문자열 하나만 넘긴다.
- 실제 OS 알림이 뜨는 것은 사람이 대화형 세션에서 봐야 한다. 테스트는 스텁 호출까지만 검증한다.
- 누계는 모듈 변수라 핫 리로드나 `/clear` 뒤에 0으로 돌아간다. `$.store`나 `$.state`로 옮기면 유지된다.
- 비용(USD)은 계산하지 않는다. 모델별 단가 표를 `format.mjs`에 두면 `$.session.usage()` 없이도 추정할 수 있다.
- 다음: 임계값을 `userConfig`로 노출하고 `/config` 행으로 바꾸기, `AbovePrompt` 밴드에 현재 턴의 경과 시간을 실시간 표시하기.

## 7. 출처
- Claude Code changelog 2.1.295 (`$.ui.notify` for mods): https://code.claude.com/docs/en/changelog
- Create a mod: https://code.claude.com/docs/en/plugins/mods/create
- React to events (`turn.complete`): https://code.claude.com/docs/en/plugins/mods/events
- Mods API / reference / test: https://code.claude.com/docs/en/plugins/mods/api , https://code.claude.com/docs/en/plugins/mods/reference , https://code.claude.com/docs/en/plugins/mods/test
- 타입 선언(GitHub, 구버전일 수 있음): https://github.com/anthropics/claude-code/blob/main/mods/types/claude-code.d.ts

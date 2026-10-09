# claude-tamagotchi — Claude Code 안에 사는 토큰 펫 모드

## 1. 무엇을 만들었나
Claude Code 모드(`token-pet/`)다. 세션을 열면 오른쪽 pane에 펫이 나타나고, 턴마다 쓴 토큰(입력+출력+캐시 읽기)이 밥이 되어 포만감이 오른다. 1분마다 배가 꺼지고, 5분 넘게 아무 일 없으면 졸고, 도구 호출이 3번 실패하면 앓고, 30초 넘는 턴이 끝나면 자랑스러워하며 `$.ui.notify`로 네이티브 알림을 보낸다. `/pet`은 상태 한 줄, `/pet reset`은 새 펫. 펫은 `$.store`에 저장되어 세션을 닫아도 살아 있다.

## 2. 왜 만들었나
Claude Code 2.1.295 체인지로그의 모드용 `$.ui.notify`([changelog](https://code.claude.com/docs/en/changelog))를 어제 turn-notify 모드로 한 번 다뤘는데, 그 결과물은 "유용하지만 재미없다"는 평을 들었다. 같은 모드 API(`ui.render` pane, `$.state`로 pane 다시 그리기, `$.clock.every`, `$.store`, `tool.call`의 `isError`)를 전부 써 보면서도 결과가 웃긴 걸 만들고 싶었다. 펫은 토큰 사용량·소요 시간·도구 실패라는 세션의 숫자들을 표정 하나로 보여 주는 가장 작은 대시보드이기도 하다.

## 3. 어떻게 만들었나
1. **순수 로직 분리** (`hooks/pet.ts`): 펫 상태(`Pet`)와 `feed/hurt/tick/drained/moodOf` 함수를 모드 런타임 없이 node로 테스트할 수 있게 뺐다. 모든 함수는 새 객체를 돌려주고 원본을 바꾸지 않는다.
2. **훅 모듈** (`hooks/register.tsx`): `session.start`에서 `/pet` 등록, 저장소에서 펫 로드, pane 열기, 60초 타이머. `turn.complete`에서 밥 주기(서브에이전트 턴 제외). `tool.call`은 `next(e)` 뒤 `isError`면 상처. `ui.render { component: 'Pane' }`가 얼굴·게이지·대사를 그린다. 상태 변경은 `change()` 한 함수로 모아 `$.state`(pane 재렌더)와 `$.store`(영구)를 같이 갱신한다.
3. **타입 계약** (`types/index.d.ts`): `PluginState['token-pet'].pet`을 선언해 `claude plugin validate`가 `$.state` 키를 계약과 대조하게 했다.
4. **막힌 지점 1 — 이름 거부**: 처음 이름 `claude-pet`은 validate가 "Anthropic 자체 플러그인처럼 보이는 이름"이라며 거부했다(`claude-` 접두어 금지). `token-pet`으로 바꿨다.
5. **막힌 지점 2 — 배고픔 이중 차감**: 틱마다 `lastEventAt` 기준으로 감소량을 계산해서 5분 뒤 포만감이 0이 됐다. 마지막으로 차감한 시각 `drainedAt`을 따로 두어 해결했고, 단위 테스트로 고정했다.
6. **막힌 지점 3 — proud가 바로 풀림**: `/pet`이 `tick`을 호출하면 기분이 다시 계산돼 `proud`가 사라졌다. `tick`이 `happy`로 떨어질 때만 `proud`를 유지하게 했다.
7. **세션 간 지속**: 처음엔 `$.state`만 썼는데 `--resume`한 세션에서도 펫이 초기화됐다(`$.state`는 프로세스 수명). `$.store`를 붙이고 e2e를 "세션 A에서 턴 → 세션 B의 /pet에 1끼"로 바꿨다. 실제 저장소를 쓰므로 e2e는 시작과 끝에 `/pet reset`을 한다.
8. **검증 세 겹**: node 단위 테스트, `claude plugin test`(mock clock으로 5분 경과, `mock.store`로 세션 간 상태, `$.ui.mount`로 terminal/desktop 두 surface의 pane 트리 검사), 번들된 API 타입에 대한 `tsc`, 그리고 실제 `claude -p` e2e.

## 4. 사용법
```bash
cd days/2026-10-10-claude-tamagotchi
claude --plugin-dir ./token-pet          # 세션을 열면 pane에 펫이 나타난다 (터미널 폭 144열 이상에서 자동 배치)
```
세션 안에서:
```
/pet            # Claudie · happy · fullness 72/100 · 3 meals · 0 bruises
/pet reset      # A new pet hatched. ...
```
터미널이 좁으면 pane은 대기하고 `/pet`으로 열 수 있다. 상수는 `hooks/pet.ts` 맨 위에 모여 있다(400토큰=1점, 분당 4점 감소, 5분 idle에 졸음, 30초 턴에 proud, 에러 3번에 sick).

## 5. 테스트 결과
오프라인 (`bash test.sh`, 2026-10-10):
```
== 1) node 단위 테스트: hooks/pet.ts
  node 단위 테스트: 15/15 통과
== 2) claude plugin validate / test
  ✅ claude plugin validate
  (pass) a turn feeds the pet and /pet reports it
  (pass) a long turn makes the pet proud and sends one notification
  (pass) three failing tool calls make it sick; the next meal heals it
  (pass) five idle minutes: the pet drains and dozes off
  (pass) the pane draws the face, the bar and the line on terminal / desktop
  (pass) the pet is kept in $.store between sessions, and /pet reset hatches a new one
  (pass) a corrupt store value is ignored and a new pet starts
   11 pass / 0 fail
== 결과: PASS
```
타입 검사: 번들 `claude-code.d.ts` 기준 `tsc` 오류 0건.

실제 Claude Code e2e (`bash e2e.sh`, 2.1.296):
```
== 0) /pet reset
   | token-pet: A new pet hatched. Claudie · happy · fullness 60/100 · 0 meals · 0 bruises
== 1) claude -p '/pet'
   | token-pet: Claudie · happy · fullness 60/100 · 0 meals · 0 bruises
== 2) 모드 없이 /pet → "이 세션에는 /pet 명령이 없어서…" (대조군) ✅
== 3) 실제 턴 1회(세션 A) → 다음 세션(B)
   | 세션 A 토큰: 10590
   | token-pet: Claudie · happy · fullness 85/100 · 1 meals · 0 bruises
== 결과: pass=4 fail=0
```
세션 A에서 Haiku 5.5가 "OK" 한 마디 하는 데 쓴 10,590토큰이 세션 B의 펫에게 26점짜리 한 끼로 남았다.

## 6. 한계와 다음 아이디어
- `-p`(헤드리스) 세션에서는 pane이 안 보이므로 e2e는 `/pet` 텍스트로만 확인했다. 대화형 세션의 실제 그림은 손으로 봤다.
- 도구 실패를 `isError`로만 본다. 사용자가 거부한 권한, 모델의 refusal은 상처로 치지 않는다.
- 펫은 한 마리, 이름 고정. `userConfig`로 이름·식성 조절, `/pet name <x>`.
- 다음: `$.audio.play`로 밥 먹는 소리, 포만감 100에서 진화, `AbovePrompt` 밴드에 한 줄 얼굴, 여러 세션이 같은 펫을 두고 경쟁하는 `$.store` 리더보드.

## 7. 출처
- Claude Code changelog 2.1.295 (`$.ui.notify` 등): https://code.claude.com/docs/en/changelog
- 모드 API 타입과 예제: Claude Code 2.1.296 `plugin-authoring` 스킬의 `claude-code.d.ts`, `examples/pane.tsx`, `examples/band.tsx`, `examples/tool-call.ts`
- 어제의 turn-notify 모드: ../2026-10-10-turn-notify-mod/

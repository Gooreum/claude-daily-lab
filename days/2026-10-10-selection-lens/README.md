# selection-lens — 선택한 텍스트를 /lens 한 번으로 번역·설명하는 모드

## 1. 무엇을 만들었나

Claude Code 모드(플러그인) `selection-lens`. 트랜스크립트에서 마우스로 드래그한 텍스트를 `/lens`가 `$.ui.selection()`으로 받아, 세션의 자격 증명 그대로 `$.model.complete(haiku)`에 물어보고 답을 pane에 쌓는다. API 키도, 별도 `claude -p` 호출도 없다.

| 명령 | 하는 일 |
|------|---------|
| `/lens` | 선택 영역을 한국어로 번역 (기본 모드 `ko`) |
| `/lens en` | 영어로 번역 |
| `/lens explain` | 코드든 문장이든 한국어 5문장 이내로 설명 |
| `/lens tldr` | 한 줄 요약 |
| `/lens ko -- <text>` | 선택 대신 인라인 텍스트 (`-p`처럼 선택이 없는 자리용) |

- 응답은 명령 결과 한 줄(`[→ 한국어] … (77→37 tok, <$0.0001)`)과 `lens` pane(최근 5건, 세션 누적 비용) 두 곳에 나온다.
- 선택이 없으면 모델을 부르지 않고 사용법만 말한다. 4,000자 넘는 선택은 앞부분만 보내고 잘랐다고 적는다.
- API 오류·빈 응답·타임아웃(30초)은 `✗ api-error 529 (overloaded)`처럼 결과로 보여 주고 예외를 던지지 않는다.

## 2. 왜 만들었나

Claude Code 2.1.288 changelog에 모드용 `$.ui.selection()`이 들어갔다. 10월 수집(`news/2026-10-october-all.md` 18번)의 현실 적용 1·2번이 "드래그한 코드만 받아 설명·테스트 생성", "선택한 영어 답변을 한국어로 pane에"였고 다음 주제 2순위로 적어 둔 것을 그대로 만들었다. 긴 영어 답변을 전부 번역시키지 않고 필요한 줄만 보는 용도다.

같이 쓴 API: `$.model.complete`는 세션 자신의 클라이언트로 도구·히스토리 없이 완성 한 번을 돌린다. 모드 안에서 작은 모델을 쓰는 가장 싼 길이라 Haiku 5.5·`effort: low`·시스템 프롬프트 캐시 표시로 고정했다.

## 3. 어떻게 만들었나

```
selection-lens/
  .claude-plugin/plugin.json   # name, types
  hooks/hooks.json             # modules: ["./register.tsx"]
  hooks/lens.ts                # 순수 함수: parseArgs, clipSource, buildRequest, costOf, summarize, pushLookup
  hooks/register.tsx           # session.start(명령 등록) / command.run lens / ui.render Pane
  types/index.d.ts             # Lookup, Mode, PluginState 'selection-lens': { lookups }
  tests/lens.test.ts           # claude plugin test 9건 (ui.selection·model.complete 스텁)
test.sh  e2e.sh
```

- `command.run lens`: 인자를 `parseArgs`로 모드·인라인 텍스트로 나누고, 인라인이 없으면 `$.ui.selection()`을 읽는다. 둘 다 없으면 `exitCode: 1`과 안내문. 있으면 `$.model.complete({ model: 'haiku', system: [{ text, cache: true }], prompt, effort: 'low', maxTokens, timeoutMs: 30000 })`.
- 결과는 `$.state` atom `lookups`에 앞으로 붙여 5개 유지. 값이 바뀌면 pane이 다시 그려진다(세션 안에서만, `$.store`에는 남기지 않는다. 번역 이력은 다음 세션에 필요 없다).
- 비용은 플러그인 자체 Haiku 5.5 단가표로 추정한다(입력 0.10 / 출력 0.50 / 캐시 읽기 0.01 / 캐시 쓰기 0.125 USD/MTok). `$.model.complete` 결과에 비용 필드가 없어서다.
- 테스트 스텁: `on('ui.selection', () => ({ value: { text } }))`, `on('model.complete', () => ({ value: { isAnswered, text, usage } }))`. 노운 이벤트는 `{ value }`로 답하면 된다.
- 배운 것 두 가지. `$.ui.mount`의 surface는 `terminal|desktop|vscode|mobile`뿐이라 `remote`는 TypeError. `$.ui.selection()`은 문서대로 fullscreen 아님·`-p`·선택 없는 surface에서 `undefined`라, `-p` e2e는 인라인 텍스트 경로로만 모델 호출을 검증한다.

## 4. 사용법

```bash
# 이 폴더에서
claude --plugin-dir ./selection-lens
# 트랜스크립트에서 텍스트를 드래그한 뒤
/lens            # 한국어 번역
/lens explain    # 설명
/lens tldr       # 한 줄 요약
/lens en -- 캐시가 깨졌다   # 선택 없이 인라인

bash test.sh     # node 단위 14건 + claude plugin validate/test 9건
bash e2e.sh      # 실제 claude -p로 /lens 4가지 (haiku 실호출 2회, 합쳐서 $0.0001 미만)
```

## 5. 테스트 결과

`bash test.sh` (2026-10-10, Claude Code 2.1.296, Node 24):

```
== 1) node 단위 테스트: hooks/lens.ts
  ✅ parseArgs: 빈 인자 → ko, 텍스트 없음
  ✅ parseArgs: 모드만
  ✅ parseArgs: 모드 + -- 텍스트
  ✅ parseArgs: -- 텍스트만 → ko
  ✅ parseArgs: 모드 아닌 단어들 → 전부 텍스트
  ✅ clipSource: 4000자 초과만 자르고 CRLF 정리
  ✅ buildRequest: haiku·low·캐시 표시 system·모드별 maxTokens
  ✅ costOf: Haiku 단가 (1M 입력 = $0.10, 캐시 읽기 $0.01)
  ✅ inputTokensOf: 캐시 읽기·쓰기 포함
  ✅ preview: 공백 접고 60자 말줄임
  ✅ fmtCost: 아주 작은 값은 <$0.0001
  ✅ summarize: 성공은 라벨·답·토큰·비용
  ✅ summarize: 실패는 ✗ 이유
  ✅ pushLookup: 앞에 붙이고 5개 유지
  node 단위 테스트: 14/14 통과
== 2) claude plugin validate / test
  ✅ claude plugin validate
  (pass) /lens with a selection translates it to Korean with haiku and opens the pane
  (pass) /lens explain sends the explain system prompt
  (pass) inline text after -- wins over the selection
  (pass) with nothing selected it explains how to use it and asks the model nothing
  (pass) an API error is reported, not thrown, and stays in the pane history
  (pass) a very long selection is cut to 4000 chars before it is sent
  (pass) the pane lists lookups newest first on terminal
  (pass) the pane lists lookups newest first on desktop
  (pass) an empty pane says what to do
   9 pass
   0 fail
  ✅ claude plugin test
== 결과: PASS
```

`bash e2e.sh` (실제 Claude Code, Haiku 실호출):

```
== 1) /lens (선택 없음) → 사용법 안내, 모델 호출 없음
   | selection-lens: Nothing is selected. Drag over text in the transcript, then run /lens again — or pass text inline: /lens ko -- <text>
  ✅ 선택 없음 안내
== 2) /lens ko -- <영어> → 실제 haiku 번역 (세션 자격 증명으로 $.model.complete)
   | selection-lens: [→ 한국어] 캐시는 시스템 프롬프트가 변경되었기 때문에 무효화되었습니다.  (77→37 tok, <$0.0001)
  ✅ 한국어 번역 + 토큰·비용
== 3) /lens tldr -- <긴 문단> → 한 줄 요약
   | selection-lens: [한 줄 요약] 프롬프트 캐싱은 첫 호출 때 1.25배 가격으로 캐시를 쓰고, 접두사가 동일하고 만료되지 않으면 이후 호출에서 10분의 1 가격으로 읽는다.  (120→86 tok, <$0.0001)
  ✅ 요약
== 4) 모드 없이 /lens → 응답 없음 (대조군)
   | `/lens` isn't installed in this session, so it didn't run. …
  ✅ 모드 없을 땐 /lens가 없다
== 결과: pass=4 fail=0
```

타입 검사: `plugin-authoring` 스킬이 내려 준 `claude-code.d.ts`에 대해 `tsc --noEmit` 오류 0.

처음 돌렸을 때 실패 2건은 테스트 쪽 문제였다. `$0.0000`을 기대했는데 구현이 `<$0.0001`로 표기했고(의도한 쪽은 후자), `$.ui.mount({ surface: 'remote' })`가 허용 목록에 없어 TypeError가 났다. 둘 다 테스트를 고쳤다.

## 6. 한계와 다음 아이디어

- **진짜 마우스 선택 경로는 자동화로 못 본다.** `-p`에는 선택이 없고 plugin test는 스텁이다. 대화형 세션에서 드래그 후 `/lens`를 사람이 한 번 확인해야 한다. 스텁은 `UiSelection` 타입(`text`, `requestId`) 그대로라 모양은 맞다.
- `tldr`는 "40자 이내 한 문장"을 시켰는데 e2e에서 86 토큰짜리 긴 문장이 왔다. Haiku `effort: low`가 길이 제한을 느슨하게 지킨다. `maxTokens`를 더 낮추거나 문장 수를 세어 잘라야 한다.
- 비용은 추정치다. `$.model.complete`가 `usage`만 주므로 모델을 바꾸면 단가표도 바꿔야 한다.
- 다음: `requestId`가 있으면 그 행 아래에 Band로 답을 인라인 표시, `explain`에서 선택이 코드일 때 테스트 초안 생성 모드 추가, token-pet과 결합해 번역도 "밥"으로 치기.

## 7. 출처

- Claude Code changelog 2.1.288 (`$.ui.selection()`): https://code.claude.com/docs/en/changelog
- 10월 수집 18번 항목과 다음 주제 2순위: ../../news/2026-10-october-all.md
- 모드 API 타입(`$.ui.selection`, `$.model.complete`, `claude-code/testing`): Claude Code 2.1.296 `plugin-authoring` 스킬의 `claude-code.d.ts`
- Haiku 5.5 단가: https://platform.claude.com/docs/en/about-claude/pricing
- 같은 날의 모드 두 개: ../2026-10-10-claude-tamagotchi/ , ../2026-10-10-turn-notify-mod/

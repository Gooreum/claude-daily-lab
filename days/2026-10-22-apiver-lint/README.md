# apiver-lint — Claude API 버전 `2026-10-21` 업그레이드 사전 점검 린터

## 1. 무엇을 만들었나
코드 저장소를 훑어서 Claude API 버전 `2023-06-01`에서 `2026-10-21`로 올릴 때(또는 SDK 메이저를 올릴 때) 깨지는 곳을 미리 보고하는 CLI 스크립트(`apiver_lint.py`, Python 표준 라이브러리만). `temperature`·`top_p`·`top_k` 제거, assistant 메시지의 `document` 블록, user 메시지의 `citations`, SDK 핀과 플랫폼 패키지 짝, `X-Api-Key`를 읽는 프록시, `MessageParam(...)` 호출, Text Completions·`compactionControl` 제거, Admin API 옛 필드 이름까지 13개 규칙으로 잡는다. 키·네트워크가 필요 없고 CI에서 `--min-level error` 한 줄로 게이트가 된다.

## 2. 왜 만들었나
계기: [API 릴리스 노트 10-21 "API version 2026-10-21"과 마이그레이션 가이드](https://platform.claude.com/docs/en/api/migration-2026-10-21) (`news/2026-10-22.md` 1번). 새 버전은 샘플링 파라미터 세 개를 **모든 모델에서** 400으로 만들고, 새 SDK(Python 2.0 · TypeScript 1.0 · `ant` 2.0 …)는 이 버전을 기본으로 보내며 키를 `Authorization: Bearer`로 바꿔 보낸다. 어제까지의 `haiku-migrate-lint`는 *모델* 이전용이라 이 변화를 못 본다. 가이드가 "영향이 있으면" 식으로 항목을 나열하는데, 실제 저장소에서 "내 코드가 몇 군데 해당하나"는 grep으로 세어야 하므로 도구로 만들 가치가 있다고 봤다. 같은 날 Claude Code 2.1.307도 `/claude-api api-version`으로 코드 변환을 해 주는데, 그 전에 *범위를 보는* 정적 점검이 있으면 변환 결과를 검토하기 쉽다.

## 3. 어떻게 만들었나
1. 마이그레이션 가이드 전체(Breaking changes · SDK and CLI changes)를 읽고 **정적으로 잡히는 것만** 규칙으로 옮겼다. 런타임 동작이 바뀌는 것(라이선스, 증가한 반환 필드 등)은 뺐다.

| 규칙 | 레벨 | 잡는 것 |
|---|---|---|
| V01 | error / warn | `temperature`·`top_p`·`top_k` (코드는 error, 설정 파일·`def` 래퍼 인자는 warn) |
| V02 | warn | 가장 가까운 `role`이 assistant인 `{"type": "document"}` (휴리스틱) |
| V03 | warn | 가장 가까운 `role`이 user인 비어 있지 않은 `citations: [` (`{"enabled": true}`는 통과) |
| V04 | error / warn / info | SDK 핀. requirements·pyproject(PEP 508/poetry)·package.json·go.mod·Gemfile·pom/gradle·csproj·composer. TS는 `sdk`와 플랫폼 패키지(bedrock·vertex·foundry·aws·google-cloud) 메이저가 어긋나면 error, 핀이 2.x를 막으면 info, 핀이 없으면 warn |
| V05 | info | `anthropic-version: 2023-06-01`을 직접 보냄 |
| V06 | error / warn | Text Completions (TS·Go·Java·Ruby·셸=error, 그 밖 언어=warn) |
| V07 | warn | nginx `$http_x_api_key`·`proxy_set_header x-api-key`, `req.headers["x-api-key"]`, `headers.get("x-api-key")` |
| V08 | error / warn | `Anthropic(api_key=…, auth_token=…)` (Python=ValueError, TS=warn) |
| V09 | error | `MessageParam(...)` 호출, `class X(MessageParam)` |
| V10 | error | `compactionControl` |
| V11 | error | `client.models.list/retrieve(betas=…)` (`beta.models`는 통과) |
| V12 | info | Go import·`go install …/ant` 경로에 `/v2` 없음 |
| V13 | warn | Admin·Analytics 옛 필드 (`roles`·`group_id`·`name`·`group_type`·`workspace_id`·`actor.email`·`summaries`) — 같은 줄이나 위 4줄에 해당 엔드포인트 이름이 있을 때만 |

2. **레벨의 뜻을 "업그레이드하면 어떻게 되나"로 고정**했다. error = 올리면 400·TypeError·ValueError 확정, warn = 코드를 보고 판단, info = 해야 할 일(핀 올리기). 그래서 SDK 핀이 아직 1.x인 것은 error가 아니라 info다 — 그건 고장이 아니라 작업 목록이다.
3. **Anthropic 문맥 게이트.** 파일에 `anthropic`·`claude`가 (주석이 아닌 줄에) 있을 때만 V01·V06~V13을 적용한다. 처음엔 주석 한 줄에 "Anthropic"이 있는 OpenAI 코드의 `temperature`가 잡혔고, `openai.chat.completions.create(`가 V06으로 잡혔다. 주석 줄을 문맥 판정에서 빼고 `client.completions`/`anthropic.completions`만 보게 고쳤다.
4. **이 저장소와 cookbooks에 돌려 오탐을 줄였다.** `claude-cookbooks`에서 (a) 이미 `key.scope.workspace_id`를 읽는 신형 코드가 V13으로 잡혔고 (b) 문서 본문이 들어 있는 JSON 데이터가 V06으로 잡혔다. (a)는 lookbehind로, (b)는 설정 확장자(.json·.yaml 등)에서 V06을 끄는 것으로 고쳤고 둘 다 `test.sh`에 회귀 테스트로 넣었다. 이 저장소의 `haiku_lint.py`는 백틱으로 감싼 설명 문자열(`` `temperature: 1` ``)이 V01로 잡혀서 백틱 앞은 제외했다.
5. 자동 수정(`--fix`)은 일부러 넣지 않았다. 샘플링 파라미터를 지우면 `temperature` 낮춰서 일관성을 얻던 호출의 동작이 바뀐다(가이드: "No other setting replaces it"). 사람이 보고 지우거나, 그 호출만 옛 버전으로 남겨야 해서 보고까지만 한다.

## 4. 사용법
```bash
python3 apiver_lint.py <경로>...                    # 사람용 보고. error가 있으면 exit 1
python3 apiver_lint.py src/ --json                  # 기계용
python3 apiver_lint.py src/ --min-level error       # 400/TypeError 확정만 (CI 게이트)
python3 apiver_lint.py . --ignore V05,V12           # 규칙 끄기
python3 apiver_lint.py . --exclude node_modules --exclude fixtures   # 폴더·파일 이름 건너뛰기
```
종료 코드: 0=error 없음, 1=error 있음, 2=사용법 오류(없는 경로, 모르는 규칙).
예시 출력(`fixtures/py_app/app.py`, 일부):
```
fixtures/py_app/app.py
      4  V08  ERROR 업그레이드 시 실패 확정  한 클라이언트에 `api_key`와 `auth_token`을 함께 넘기면 Python SDK 2.0은 `ValueError`. 하나만 넘긴다
         │ client = anthropic.Anthropic(api_key="x", auth_token="y")
      8  V09  ERROR 업그레이드 시 실패 확정  `MessageParam(...)`은 2.0에서 `TypeError`. 딕셔너리 리터럴로 쓴다: ...
     12  V01  ERROR 업그레이드 시 실패 확정  `temperature` — 2026-10-21에서 400 (기본값을 보내도). 제거하고 프롬프트로 유도
     17  V02  WARN  확인 필요  assistant 메시지에 직접 넣은 `document` 블록은 400. user 메시지로 옮긴다 ...
     20  V03  WARN  확인 필요  user 메시지 text 블록의 비어 있지 않은 `citations`는 400. 제거 ...
```
GitHub Actions에서는 `python3 apiver_lint.py . --min-level error` 한 줄이면 된다. 키 불필요. 사용 순서 제안: ① 린트로 범위 확인 → ② 필요하면 `/claude-api api-version`(Claude Code 2.1.307)으로 변환 → ③ 린트를 다시 돌려 남은 곳 확인 → ④ 핀과 헤더를 올림.

## 5. 테스트 결과
`bash test.sh` (키·네트워크·모델 호출 없음) — 54개 통과, 실패 0:
```
[1] 종료 코드
  ✓ error가 있으면 exit 1
  ✓ 깨끗한 폴더는 exit 0
  ✓ warn만 있으면 exit 0
  ✓ 없는 경로는 exit 2
  ✓ 모르는 규칙 --ignore는 exit 2
[2] py_app — 파이썬 규칙
  ✓ V08:4:error   ✓ V09:8:error   ✓ V01:12:error   ✓ V01:13:error
  ✓ V02:17:warn   ✓ V03:20:warn   ✓ V11:27:error   ✓ V05:30:info
  ...
[5] 오탐 방지
  ✓ clean 폴더: 검출 0
  ✓ 변수명·속성·주석·백틱 설명·user 문서·assistant citations·beta.models는 통과
  ✓ 이미 scope.workspace_id를 읽는 코드는 통과
  ✓ JSON 데이터 속 Text Completions 설명은 통과
[6] SDK 핀 판정 (V04)
  ✓ 핀 'anthropic>=1.16,<2' → info   ✓ 핀 'anthropic>=2.0,<3' → 검출 없음   ✓ 핀 'anthropic' → warn ...
통과 54 · 실패 0
```
`bash e2e.sh` (공개 저장소 실측, 네트워크 필요; 이 세션에서 실행함):
```
== anthropics/claude-cookbooks
파일 605 · error 62 · warn 44 · info 18
규칙별: V01×88, V05×18, V06×15, V13×3
== anthropics/claude-quickstarts
파일 648 · error 1 · warn 0 · info 18
규칙별: V01×1, V04×18
```
cookbooks의 V01 88건은 대부분 예제 노트북의 `temperature=…`(코드 error + `promptfooconfig.yaml` 설정 warn), V06 15건은 `client.completions.create`·`HUMAN_PROMPT`를 쓰는 옛 노트북(Pinecone·Wikipedia)이었다. 표본으로 열어 본 V06 5건·V13 4건은 모두 실제 해당 코드였다(전수 검토는 안 함). 이 저장소에 돌리면(`fixtures`·`news`·본인 폴더 제외) 10-10 `haiku-migrate-lint/test.sh`의 fixture 문자열 한 곳만 V01로 걸린다.

## 6. 한계와 다음 아이디어
- **정규식·줄 단위 휴리스틱이다.** V02·V03은 "위 14줄에서 가장 가까운 `role`"로 소유자를 추정하므로 role이 변수로 들어가거나 메시지를 함수로 조립하면 놓치거나 틀린다(그래서 warn). AST로 쪼개면 더 정확하지만 언어마다 파서가 필요해 오늘 크기를 넘는다.
- 문자열로 만든 예제 코드(`printf 'client.messages.create(... temperature=0.5 ...)'`)도 코드처럼 잡힌다. 백틱 설명만 제외했다.
- Python·TS·셸·Go·설정 파일 중심이다. Java·C#·Ruby·PHP는 의존성 핀(V04)과 Text Completions(V06)만 보고, `UserMessageParam` 분리·단일값 enum 상수화 같은 타입 변경은 보지 않는다. 컴파일러가 알려 주는 종류라 린터의 몫이 작다고 봤다.
- V07은 "읽는 줄"만 잡는다. 게이트웨이가 헤더를 다른 이름으로 감싸거나 Lua/Envoy 설정에서 읽는 경우는 놓친다.
- 라이선스 변경(MIT→Apache 2.0), 응답에 필드가 추가되는 변화는 범위 밖이다.
- 다음 아이디어: ① `--fix --dry-run`으로 V09(`MessageParam(`→딕셔너리)·V11(`models.`→`beta.models.`)처럼 의미가 안 바뀌는 치환만 diff로 보여 주기, ② Bedrock 구형 모델(Opus 4.6 이하) 호출이 있는 파일은 "SDK를 올리면 안 됨"으로 따로 표시, ③ `.github/workflows`가 `anthropic-version` 헤더를 환경 변수로 넣는 경우 따라가기.
- 이 세션(GitHub Actions)에는 `claude` CLI가 없어 `/claude-api api-version`과의 조합은 실행해 보지 못했다. 위 사용 순서는 릴리스 노트 문구에 근거한 제안이다.

## 7. 출처
- https://platform.claude.com/docs/en/api/migration-2026-10-21 — 마이그레이션 가이드 (규칙의 근거)
- https://platform.claude.com/docs/en/api/versioning — 버전 이력
- https://platform.claude.com/docs/en/release-notes/overview — 10-21 릴리스 노트
- https://github.com/anthropics/claude-code/releases/tag/v2.1.307 — `/claude-api api-version`
- https://github.com/anthropics/anthropic-sdk-python/releases/tag/v2.0.0 — Python SDK 2.0.0
- https://github.com/anthropics/claude-cookbooks · https://github.com/anthropics/claude-quickstarts — e2e 실측 대상

# prefix-guard

> 요청 로그를 이어 읽어, Claude Fable 5.2가 400을 낼 대화(이전 요청을 고쳐 다시 보낸 곳)와 그 밖의 400 사유를 미리 찾는 CLI 스크립트.

## 1. 무엇을 만들었나

CLI 스크립트(`prefix_guard.py`, 표준 라이브러리만 사용). Messages API 요청 본문을 한 줄에 하나씩 적은 JSONL 로그를 읽어 대화별로 묶고, 앞 요청과 다음 요청을 비교해 시스템 프롬프트·도구 목록·이전 메시지가 바뀐 곳을 찾는다. 바뀐 뒤에 Fable 5.2가 만든 thinking 블록을 돌려보내면 400이 나므로 ERROR로, 아직 블록이 없는 구간의 편집은 WARN으로 알린다. 요청 한 개만 봐도 알 수 있는 400 사유(thinking 끄기·`budget_tokens`, 강제 `tool_choice`, 옛 `computer_20251124`, advisor 모델 불일치)와 effort max 위험도 같이 본다. 키·모델·네트워크 없이 동작한다.

## 2. 왜 만들었나

- 계기: platform.claude.com 11-09 "What's new in Claude Fable 5.2" — https://platform.claude.com/docs/en/models/fable-5-2/whats-new-fable-5-2 (news/2026-11-10.md 2번)
- 이 글의 400 사유 중 prefix check는 소스 코드 검색으로 잡을 수 없다. 코드는 멀쩡해 보여도 대화 기록을 요약·삭제하거나, 시스템 프롬프트의 날짜를 매 턴 바꾸거나, 도중에 도구를 더하면 걸린다. 그래서 `apiver-lint`·`haiku-migrate-lint`처럼 소스를 훑지 않고 **실제로 오간 요청을 순서대로 비교**하는 쪽으로 만들었다.
- 문서가 모델을 올리기 전에 "코드가 앞부분을 고치는지 확인하라"고 하는데, 확인할 도구가 없으면 사람이 눈으로 로그를 읽어야 한다.

## 3. 어떻게 만들었나

1. 문서에서 400이 되는 조건을 뽑았다: 시스템·도구·이전 메시지 중 하나가 thinking 블록이 만들어진 뒤 바뀜, `thinking` enabled/disabled, `tool_choice` any/tool, `computer_20251124`(Bedrock 제외), advisor 모델 불일치.
2. **대화 묶기:** 로그에는 대화 ID가 없다. 첫 메시지가 같거나 첫 assistant 턴(API가 돌려준 그대로라 안 바뀐다)이 같으면 같은 대화로 봤다. 덕분에 첫 user 메시지를 매 턴 고쳐 쓰는 경우도 같은 대화로 묶인다.
3. **블록을 만든 요청 찾기:** thinking 블록이 든 assistant 턴이 `messages[k]`이면, 그 블록은 `messages`가 k개였던 가장 최근 요청의 응답이다. 그 요청의 시스템·도구·`messages[:k]`를 지금 요청과 비교한다. 해당 요청이 로그에 없으면(로그가 중간부터 시작) 비교를 건너뛰고 INFO로 알린다.
4. 비교에서 `cache_control` 표시는 뺐고, 문자열 content와 텍스트 블록 하나짜리 content는 같은 것으로 본다(내용이 아니라 표기 차이이기 때문이다).
5. 판정: Fable·Mythos 5.2끼리의 블록만 ERROR. Opus 같은 다른 모델이 만든 블록은 5.2가 읽을 수 있고, 5.2 블록을 다른 모델로 보내면 조용히 버려지므로(요청은 성공) INFO. `thinking.block_binding.prefix_mismatch_behavior: "drop_block"`이 켜져 있으면 ERROR를 WARN으로 낮춘다.
6. `{"request":…, "response":…}` 꼴이면 응답의 thinking 블록과 다음 요청이 되돌려 보낸 블록을 대조한다. **막힌 곳:** 처음에는 블록이 있는 턴만 비교해, 되돌려 보내면서 thinking 블록을 통째로 빼 버린 경우를 놓쳤다. 테스트(altered.jsonl)가 잡아 줘서, 블록이 없는 턴도 응답과 비교하도록 고쳤다.
7. `--model`로 "모든 요청이 이 모델로 갔다고 가정"하면, 지금은 Opus로 도는 로그가 5.2로 옮길 때 어떻게 되는지 시험할 수 있다(근사: 과거 블록도 5.2가 만든 것으로 본다).

개발 도구는 Claude Code(Sonnet 5.5)뿐이고, 스크립트 자체는 모델을 부르지 않는다.

## 4. 사용법

```bash
# 요청 로그(한 줄에 요청 본문 하나)를 점검
python3 prefix_guard.py LOG.jsonl

# 지금은 Opus 5.5로 도는 로그를 Fable 5.2로 옮기면 어떻게 되나
python3 prefix_guard.py LOG.jsonl --model claude-fable-5-2

# Amazon Bedrock이면 computer_20251124 를 허용 / 기계가 읽는 JSON 출력
python3 prefix_guard.py LOG.jsonl --bedrock
python3 prefix_guard.py LOG.jsonl --json
```

종료 코드: 0 = ERROR 없음, 1 = ERROR 있음(CI에 넣을 수 있다), 2 = 입력을 읽을 수 없음.
로그 항목은 요청 본문 그대로이거나 `{"request": {...}, "response": {...}}` 꼴이다. JSON 배열 파일도 읽는다.

예시(`examples/session.jsonl`: 쇼핑몰 상담 봇이 3번째 요청에서 시스템 프롬프트의 날짜를 "11월 9일"에서 "11월 10일"로 갱신한 로그):

```
prefix-guard: 요청 4개, 대화 2개

[대화 #0] 요청 3개(줄 1,2,3), 첫 메시지: "주문 1042 배송이 어디까지 왔는지 알려줘"
  ERROR 줄 3 [prefix-edit] thinking 블록이 든 assistant 턴 #1, #3이(가) 만들어진 뒤 앞부분이 바뀜 → 시스템 프롬프트가 바뀜. 이대로 보내면 400 "The block is bound to a different conversation". 고치는 법: 매 턴 바뀌는 값(날짜·사용자 이름 등)은 시스템 프롬프트 대신 마지막 user 메시지에 넣으세요.

[대화 #1] 요청 1개(줄 4), 첫 메시지: "안녕하세요"
  ERROR 줄 4 [thinking-enabled] thinking.type=enabled(budget_tokens)는 Fable 5.2에서 400. thinking을 빼거나 adaptive로 두고 effort로 깊이를 조절하세요.

요약: ERROR 2, WARN 0, INFO 0
```

## 5. 테스트 결과

`bash test.sh` (이 환경, 키·모델 없음). `e2e.sh`는 없다(스크립트가 모델을 부르지 않는다).

```
ok   - append-only 대화는 문제 없음(exit 0)
ok   - 시스템 프롬프트 편집 → ERROR prefix-edit, exit 1, 턴 번호와 해결책
ok   -   400 메시지를 그대로 안내
ok   - 이전 메시지 편집 → 메시지 번호와 compaction 안내
ok   - 첫 user 메시지를 고쳐도 같은 대화로 묶여 편집을 찾는다
ok   - 도구 추가 → '도구 1개 추가(get_time)'와 inline-tools 안내
ok   - 도구 제거 → '도구 목록이 바뀌거나 빠짐'
ok   - thinking 블록이 없는 대화의 편집은 WARN만(exit 0)
ok   - drop_block이 켜져 있으면 ERROR 대신 WARN(exit 0)
ok   - Opus 대화의 편집은 문제 없음(Fable 5.2 규칙 아님)
ok   - --model claude-fable-5-2로 가정하면 같은 로그가 ERROR
ok   - 정적 검사: ERROR 6개(enabled·disabled·any·tool·computer·advisor)
ok   -   각 코드가 나온다
ok   -   forced-tool은 any·tool 둘 다 잡는다
ok   -   effort=max는 WARN 1개
ok   -   exit 1
ok   - --bedrock이면 computer_20251124는 통과(ERROR 5개)
ok   - adaptive·auto·xhigh·Fable advisor는 문제 없음
ok   - Opus 요청의 정적 항목은 보지 않는다
ok   - --model claude-mythos-5-2 가정이면 정적 ERROR가 나온다
ok   - Fable 5.2 → Opus 전환은 INFO(블록이 조용히 버려짐), exit 0
ok   - 응답과 다르게 되돌려 보낸 thinking → ERROR turn-altered
ok   - 응답 그대로 되돌려 보내면 문제 없음({request,response} 꼴)
ok   - 섞인 두 대화를 나눈다(대화 2개)
ok   -   ERROR는 대화 #0에만
ok   - 깨진 JSON 줄은 ERROR bad-json으로 알리고 나머지는 계속 본다(exit 1)
ok   - JSON 배열 입력도 읽는다
ok   - messages가 비면 WARN no-messages로 건너뜀
ok   - cache_control 위치 변화·문자열/블록 content 차이는 편집으로 보지 않는다
ok   - 대화 중간부터 시작한 로그는 INFO producer-unknown(exit 0)
ok   - 없는 파일은 exit 2
ok   - --json 출력은 올바른 JSON 배열
ok   - 예시 로그: 시스템 날짜 갱신(줄 3)과 thinking enabled(줄 4)를 잡는다
ok   - 알 수 없는 옵션은 exit 2(argparse)

통과 34, 실패 0
```

34개 모두 통과. 시험한 것: append-only 정상, 시스템·메시지·첫 메시지·도구 추가·도구 제거 편집, 블록 없는 대화의 편집(WARN), `drop_block`, Opus 로그와 `--model` 가정, 정적 400 사유 일곱 가지와 `--bedrock`, 모델 전환, 응답 대조(블록 누락), 두 대화가 섞인 로그, 깨진 JSON·배열 입력·빈 messages, `cache_control`·표기 차이, 중간부터 시작한 로그, 없는 파일·잘못된 옵션.

## 6. 한계와 다음 아이디어

- **실제 API로 검증하지 못했다.** 400 조건은 11-09 문서의 서술을 따라 만든 것이고, 모델 호출 없이 합성 로그로만 시험했다. 문서가 말하지 않은 세부(예: `cache_control` 이동이 편집인지, 도구 순서 바꿈이 편집인지)는 추정이다. 특히 `cache_control`은 편집으로 보지 않도록 했는데, API가 다르게 판단하면 놓칠 수 있다.
- advisor 도구의 `type`이 `advisor`로 시작하고 `model` 필드를 가진다고 가정했다(문서에 도구 정의 예시가 없었다). effort 위치는 `output_config.effort` 또는 `effort`로 추정했다.
- 계정 간 thinking 블록 이동(`organization_binding_mismatch`)은 로그에 계정 정보가 없어 보지 못한다. 대화 묶기는 첫 메시지·첫 assistant 턴에만 의존해, 둘 다 고친 경우는 별개 대화로 갈라진다.
- 요청 로그를 남기는 방법은 다루지 않는다. 다음 아이디어: SDK의 `debug` 로그나 프록시 로그를 이 JSONL로 바꾸는 변환기, 앱 미들웨어로 요청을 자동 기록, 편집 위치를 diff로 보여 주기.
- Claude Code·Agent SDK가 요청을 만드는 경우는 문서상 해당이 없다. 이 도구는 Messages API를 직접 부르는 코드용이다.

## 7. 출처

- https://platform.claude.com/docs/en/models/fable-5-2/whats-new-fable-5-2 — 400 조건·drop_block·advisor·computer 도구
- https://platform.claude.com/docs/en/release-notes/overview — 11-09 Fable 5.2 API 출시 노트
- https://www.anthropic.com/claude-fable-and-mythos-5-2 — 모델 소개·가격
- https://simonwillison.net/2026/Nov/9/llm-anthropic/ — effort max가 128k 토큰을 다 쓴 사례

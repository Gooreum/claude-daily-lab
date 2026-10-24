# cache-break

> `days/2026-10-24-cache-break/` — Claude Code 트랜스크립트에서 프롬프트 캐시 재작성의 원인을 가르고 비용을 정가로 환산하는 CLI.

## 1. 무엇을 만들었나
Python 표준 라이브러리만 쓰는 CLI `cache_break.py`다. `~/.claude/projects/**/*.jsonl`의 assistant 줄에서 `usage`를 읽어 요청 단위로 합치고(스트리밍으로 한 요청이 여러 줄로 나뉘는 것을 `requestId`로 한 건으로), 메인·서브에이전트 스레드별로 시간순으로 놓은 뒤, 한 요청이 캐시에 10만 토큰 이상 쓴 경우를 **첫 호출 / 정상 증가(append) / 유휴 뒤 만료 / 도구 대기 중 만료 / 모델 전환 / 접두 변경 추정**으로 분류한다. 토큰 몫 대비 비용 몫, 원인별 건수·중앙값·비용·"캐시가 살아 있었다면 아낄 수 있던 금액", 비싼 재작성 상위 목록, 조치 제안을 Markdown 또는 JSON으로 낸다. 모델 호출도 네트워크도 없다.

## 2. 왜 만들었나
2026-10-23 dev.to 글 [I Read All 471 of My Claude Code Sessions: Where 6 Billion Tokens Actually Went](https://dev.to/danmercede/i-read-all-471-of-my-claude-code-sessions-where-6-billion-tokens-actually-went-1bde)는 일주일치 기록(61.5억 토큰, 정가 환산 약 2,500달러)에서 토큰의 97%가 캐시 읽기인데 비용의 38%는 토큰의 2.8%인 캐시 쓰기였고, 10만 토큰 넘는 재작성 223건 중 209건이 접두 변경이 아니라 **유휴 시간 뒤 캐시 만료**였다고 밝혔다. 그러나 그 분석은 글쓴이의 개인 스크립트라 따라 하기 어렵다. 이 저장소에는 호출 하나를 재는 `cache-meter`, 금액 상한을 거는 `spend-gate`·`loop-caps`가 있지만, 이미 쌓인 기록을 되짚어 "왜 비쌌나"를 가르는 도구는 없었다. 적용 아이디어 목록(news/2026-10-24.md 5번)의 마지막 항목이 이 빈칸이다.

## 3. 어떻게 만들었나
1. **기록 형식 확인**: 이 세션의 실제 트랜스크립트(`~/.claude/projects/<프로젝트>/<세션>.jsonl`)를 열어 필드를 봤다. assistant 줄에 `requestId`, `timestamp`, `isSidechain`, `agentId`, `message.model`, `message.stop_reason`, `message.usage.{input_tokens, cache_read_input_tokens, cache_creation_input_tokens, cache_creation.{ephemeral_5m,ephemeral_1h}_input_tokens, output_tokens}`가 있다. 한 요청이 content 블록마다 줄을 따로 만들어(같은 `requestId` 2~6줄, usage는 동일) 그대로 더하면 비용이 몇 배로 부풀므로 `requestId`로 합친다.
2. **분류 규칙**: 스레드(세션+에이전트)별로 시각 순서로 보고, 요청마다 직전 요청과 비교한다. ① 직전이 없으면 `first-call`. ② 모델이 바뀌면 `model-switch`(캐시는 모델별). ③ **직전 캐시 총량(읽기+쓰기)의 80% 이상을 읽었으면 `append`** — 접두가 살아 있고 새 내용만 덧붙은 정상 증가다. ④ 아니고 쉰 시간이 TTL(직전까지 1시간 쓰기를 했으면 1시간, 아니면 5분)을 넘으면 직전 `stop_reason`이 `tool_use`일 때 `tool-wait-expiry`, 아니면 `idle-expiry`. ⑤ TTL 안인데 못 읽었으면 `prefix-change`.
3. **막힌 지점 — 정상 증가를 낭비로 세던 것**: 처음 버전은 TTL 안의 큰 쓰기를 전부 `prefix-change`로 불렀다. 이 세션 기록에 돌리니 6건이 전부 "접두 변경"으로 나왔는데, 실제로는 도구 결과가 덧붙은 정상 증가였다. 읽기량으로 직전 캐시를 살렸는지 확인하는 ③을 넣어 `append`로 갈랐다. 이 기준(80%)은 경험값이라 `HIT_RATIO` 상수로 뺐다.
4. **비용**: 가격 페이지(platform.claude.com, 2026-10-24 확인)의 입력·5분 쓰기·1시간 쓰기·읽기·출력 단가를 모델별 표로 넣고 최장 접두로 모델 ID를 맞춘다(날짜 접미사 허용). Haiku 5.5는 프롬프트 10만 토큰 초과 구간 단가를 따로 쓴다. 표에 없는 모델은 비용에서 빼고 건수를 경고한다. "회피 가능"은 쓰기 비용에서 같은 토큰을 읽기 단가로 샀을 때의 비용을 뺀 값이다(첫 호출·append는 0).
5. **구간 자르기**: `--since`는 분류를 전체 기록으로 한 **뒤** 구간 밖을 버린다. 먼저 자르면 구간의 첫 요청이 전부 `first-call`로 오분류된다(테스트로 고정).
6. **테스트**: 실제 필드와 같은 모양의 합성 트랜스크립트를 `test.sh`가 만들어 숫자를 손으로 계산한 값과 대조한다. 스트리밍 중복 3줄, 깨진 줄, `<synthetic>` 모델, 별도 파일 서브에이전트(`/subagents/`), 가격표에 없는 모델을 일부러 넣었다.
7. **사용 도구**: Python 3.12, bash, Claude Code(Sonnet 5.5), WebFetch로 가격표 확인. 계획·승인 단계 없이 바로 만들었다.

## 4. 사용법
키가 필요 없다. 읽기 전용이다.
```bash
cd days/2026-10-24-cache-break
python3 cache_break.py                         # ~/.claude/projects 전체
python3 cache_break.py --since 7d              # 최근 일주일만 보고(분류는 전체 기록으로)
python3 cache_break.py ~/.claude/projects/-Users-me-myrepo --threshold 50000 --top 20
python3 cache_break.py --json | jq '.big, .breakdown'
echo $?                                        # 0=분석함, 2=usage 있는 기록 없음, 1=옵션 오류
```
출력 예(합성 기록 중 일부, 숫자는 `test.sh` fixture):
```
| 스레드 | 원인 | 건수 | 쓰기 토큰 | 중앙값 | 비용 | 회피 가능 |
| main | idle-expiry | 1 | 235.0K | 235.0K | $1.88 | $1.83 |
| subagent | idle-expiry | 1 | 178.0K | 178.0K | $0.45 | $0.43 |
## 조치 제안
- 서브에이전트 후속 메시지가 TTL을 넘겨 1건 재작성(중앙값 178.0K): 끝난 서브에이전트에는 5분 안에 보내거나, 새로 띄워 짧은 브리프를 준다.
```
조치 제안의 규칙: 메인 `idle-expiry`의 회피 가능 금액이 전체의 3% 이상이면 "새 세션 + 세 줄 인계", 서브에이전트 `idle-expiry`가 있으면 "5분 안 후속 또는 새로 띄우기", `tool-wait-expiry`가 있으면 "백그라운드 실행", `prefix-change`가 정상 증가를 뺀 큰 쓰기의 30% 이상이면 "압축·CLAUDE.md·MCP 변경 의심", 모델 전환이 있으면 "세션 중간 /model 전환 주의".

## 5. 테스트 결과
`bash test.sh` (키·네트워크·모델 없음, CI에서 실행, 2026-10-24):
```
[1] 읽기·중복 제거
  ✓ 요청 10건 (같은 requestId 3줄→1건, 깨진 줄·user·synthetic 무시)
  ✓ 폴더 재귀 탐색: 11건·파일 3·읽기 실패 1·메인 2·서브 2
  ✓ assistant 줄 수 > 요청 수 (스트리밍 중복)
[2] 원인 분류
  ✓ main / first-call 1건
  ✓ main / append 1건
  ✓ main / prefix-change 1건
  ✓ main / idle-expiry 1건
  ✓ main / tool-wait-expiry 1건
  ✓ main / model-switch 1건
  ✓ subagent / idle-expiry 1건
  ✓ subagent / first-call 1건
  ✓ subagent / tool-wait-expiry 1건
  ✓ 큰 쓰기 합계 9건 (A1 6만 토큰은 임계값 미만, U1은 1천)
  ✓ 서브에이전트 idle-expiry 중앙값 178000
[3] 비용 계산 (정가)
  ✓ Opus 5.5 1시간 쓰기 23.5만 × $8/MTok = $1.88
  ✓ 회피 가능 = 쓰기 비용 − 같은 토큰의 읽기 비용($0.20) = $1.833
  ✓ Sonnet 5.5 5분 쓰기 17.8만 × $2.5/MTok = $0.445
  ✓ append·first-call은 회피 가능 0
  ✓ 가격표에 없는 모델 1건 표시, 토큰은 합산(1시간 쓰기 936000)
  ✓ price_for: 최장 접두 일치·Haiku 5.5 10만 초과 구간
[4] --since / --threshold
  ✓ --since 3h: 분류는 전체 기록으로 하고 R4는 idle-expiry 유지, 구간 밖 first-call 제외
  ✓ --threshold 200000 → 20만 이상 3건(R3·R4·R5)
[5] Markdown·조치 제안
  ✓ 출력에 '## 토큰 몫과 비용 몫'
  ✓ 출력에 '## 큰 캐시 쓰기'
  ✓ 출력에 'idle-expiry'
  ✓ 출력에 '새 세션을 연다'
  ✓ 출력에 '5분 안에 보내거나'
  ✓ 출력에 'run_in_background'
  ✓ 출력에 '/model 전환'
  ✓ 출력에 '가격표에 없는 모델 요청 1건'
  ✓ --top 0은 목록 생략
  ✓ 접두 변경이 큰 쓰기의 30% 이상이면 /compact·CLAUDE.md 조언
  ✓ prefix-change 조언 문구
  ✓ --json top: append 제외 8건
[6] 종료 코드·기본 경로
  ✓ 기록 없음 → exit 2
  ✓ 잘못된 --since → exit 1
  ✓ --threshold 0 → exit 1
  ✓ 모르는 옵션 → exit 1
  ✓ 구간 안에 기록 없음 → exit 2
  ✓ 경로 생략 시 $HOME/.claude/projects
  ✓ 정상 분석 → exit 0

통과 41 · 실패 0
```
`bash e2e.sh` — 이 세션의 실제 트랜스크립트(`/daily-lab` 실행 중인 기록 1개, 요청 18건)에 돌린 결과. 모델 호출은 없다.
```
기록 파일 1개
검증: 요청 18건, 합계 $0.89, 큰 쓰기(10만+) 0건
```
(임계값 5천 토큰으로 낮춘 본 출력에서 큰 쓰기 9건은 첫 호출 1건과 `append` 8건으로 분류됐고 조치 제안은 "조치할 것이 없다"였다. 짧은 단일 세션이라 유휴 만료·서브에이전트는 실제 기록에서는 확인하지 못했다. 그 경로는 합성 기록으로만 검증했다.)

## 6. 한계와 다음 아이디어
- **실제 기록으로는 `append`만 확인했다.** 유휴 만료·도구 대기·서브에이전트 분류는 합성 기록 테스트로 검증했고, 며칠치 실제 기록에서의 분류 정확도는 확인하지 못했다.
- 쉰 시간은 요청 **시작** 시각의 차이라 응답 생성 시간이 포함된다. TTL 경계(5분 근처)에서는 오분류할 수 있다.
- TTL은 직전 요청이 1시간 쓰기를 했는지로 추정한다. 5분·1시간 캐시가 섞인 접두는 구분하지 못한다.
- 80% 읽기 기준(`HIT_RATIO`)은 경험값이다. 압축으로 접두가 크게 줄어든 경우를 `prefix-change`로 봐야 하는지, 서브에이전트가 부모 접두를 공유하는지는 검증하지 못했다.
- 비용은 정가 환산이며 구독 한도 소진량과는 다르다. 가격표는 코드에 박혀 있어 가격이 바뀌면 고쳐야 한다. 확장·할인 단가(batch, 지역 가산, fast mode)는 반영하지 않았다.
- 다음 아이디어: ① `Stop` 훅으로 세션 종료 때 이번 세션의 요약 한 줄을 남기기 ② `--compare 7d 7d`로 주간 비교 ③ 휴식 뒤 첫 프롬프트에 "새 세션으로 이어 쓸까요" 알림을 띄우는 모드.

## 7. 출처
- 계기: I Read All 471 of My Claude Code Sessions (dev.to, 2026-10-23) — https://dev.to/danmercede/i-read-all-471-of-my-claude-code-sessions-where-6-billion-tokens-actually-went-1bde
- 가격표(캐시 쓰기·읽기 단가): https://platform.claude.com/docs/en/about-claude/pricing
- 프롬프트 캐싱 문서: https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- Claude Code 비용 문서: https://code.claude.com/docs/en/costs
- Claude Code 2.1.310 릴리스: https://github.com/anthropics/claude-code/releases/tag/v2.1.310
- 이 저장소의 관련 결과물: `days/2026-10-10-cache-meter/`, `days/2026-10-13-spend-gate/`, `days/2026-10-20-loop-caps/`

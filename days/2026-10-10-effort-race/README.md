# effort-race — effort 다섯 레인의 시간·토큰·비용·정답률 경주

## 1. 무엇을 만들었나
Python CLI `race.py`. "급하게 답하면 틀리는" 짧은 문제 8개를 effort `low / medium / high / xhigh / max` 다섯 레인에 동시에 던져(`claude -p --effort <level>`, 동시 5개) 정답률·중앙값 소요 시간·생각(thinking) 토큰·출력 토큰·비용을 ASCII 막대그래프와 문제×레벨 격자로 보여 준다. 결과는 JSON으로 저장되고 `--from`으로 다시 그릴 수 있다. `--dry-run`은 시드 고정 가짜 결과로 그래프만 그린다.

## 2. 왜 만들었나
Claude Code 2.1.292에서 Agent 도구에 `effort` 파라미터가 생겼고([changelog](https://code.claude.com/docs/en/changelog)), 같은 손잡이가 `claude -p --effort`에도 있다. "effort를 올리면 정확히 무엇이 얼마나 늘어나나"를 숫자가 아니라 그림으로 보고 싶었다. 7일에 나온 Haiku 5.5가 기본 Haiku가 되면서(2.1.293) 40번을 돌려도 몇 센트라 실험 대상으로 딱 맞았다.

## 3. 어떻게 만들었나
1. **문제 고르기**: bat-and-ball($1.10), strawberry의 r 개수, 2·6·12·20·30 다음 수, (17×23)−4³, 요일 계산, 연꽃잎 48일, 문자열 뒤집기, Sally의 자매. 직관으로 답하면 틀리고 한 번 생각하면 맞는 고전들.
2. **호출**: 문제마다 `--json-schema {"answer": string}`로 답만 받고, `--tools ""`, `--no-session-persistence`, `--system-prompt "최종 답만"`. 응답 JSON에서 `duration_ms`, `usage.output_tokens`, `usage.output_tokens_details.thinking_tokens`, `total_cost_usd`를 뽑는다.
3. **채점**: 정답이 숫자면 답에서 첫 숫자만 꺼내 비교("5 cents" → 5, "1,000" → 1000), 아니면 소문자·구두점 제거 후 비교.
4. **막힌 지점 — `--max-turns 1`**: 첫 실제 실행에서 3건이 `error_max_turns`로 비었다. 구조화 출력은 "답 생성 → 스키마에 맞춰 내기"로 턴을 하나 더 쓴다(`num_turns: 2`). `--max-turns 3`으로 올리자 40/40. 같은 날 만든 haiku-mafia·motion-lite도 같은 플래그를 쓰고 있어 함께 고쳤다.
5. **그래프**: 레벨별 집계(`summarize`)를 지표마다 최댓값 기준으로 28칸 막대로 그린다. 문제×레벨 ✅/❌ 격자로 "어느 문제가 어느 레벨부터 풀리는지"가 보인다.

## 4. 사용법
```bash
cd days/2026-10-10-effort-race
python3 race.py                                  # Haiku 5.5, 5레벨 × 8문제 = 40회 (약 1분, 1센트대)
python3 race.py --levels low,max --tasks 4       # 일부만
python3 race.py --model claude-sonnet-5-5 --workers 3
python3 race.py --from sample-results.json       # 저장된 결과 다시 그리기
python3 race.py --dry-run --seed 3               # 모델 없이 모양만
```

## 5. 테스트 결과
오프라인 (`bash test.sh`, CI에서도 실행):
```
== 1) python3 -m unittest
  Ran 12 tests  OK   (채점 규칙, 문제 id 중복 없음, dry-run 재현성·완전성, 집계, 막대 스케일, 렌더 섹션·실패 목록,
                       백엔드 파싱·is_error·깨진 stdout, CLI 저장→--from 재로드, 모르는 레벨 거부)
== 2) dry-run 그래프
  ✅ 5레벨 × 8문제 그래프
== 결과: PASS
```
실제 Haiku 5.5 (`bash e2e.sh`, 2026-10-10, 40회 동시 5, 57초):
```
정답률
     low ████████████████████████░░░░  87.5%
  medium ████████████████████████████ 100.0%
    high ████████████████████████████ 100.0%
   xhigh ████████████████████████████ 100.0%
     max ████████████████████████████ 100.0%

중앙값 소요 시간
     low █████████████████████░░░░░░░   2.2s
  medium ███████████████████████████░   2.9s
    high █████████████████████████░░░   2.6s
   xhigh ████████████████████████████   3.0s
     max ████████████████████████████   3.0s

평균 생각(thinking) 토큰
     low ████████░░░░░░░░░░░░░░░░░░░░      96
  medium ███████████░░░░░░░░░░░░░░░░░     134
    high ███████████░░░░░░░░░░░░░░░░░     132
   xhigh ████████████████░░░░░░░░░░░░     193
     max ████████████████████████████     328

문제별 정답: low만 reverse('anthropic' 뒤집기)를 틀렸고 나머지 39칸 전부 ✅
  ✅ 40회 전부 응답
== 결과: pass=3 fail=0
```
읽히는 것: Haiku 5.5는 이 난이도에서 `medium`부터 전부 맞힌다. `max`는 `low`보다 생각 토큰을 3.4배 쓰지만 시간은 0.8초, 비용은 1센트 미만 차이다. 첫 실행(max-turns 1)에서는 low/medium이 75%였는데 그중 3건은 모델이 틀린 게 아니라 턴 제한에 걸려 답이 비었던 것이었다. "정답률이 낮다"가 보일 때 실패 원인을 따로 세는 게 중요하다는 걸 그래프 아래 `⚠ 실패 N건` 줄이 해 준다.

## 6. 한계와 다음 아이디어
- 문제가 쉬워 Haiku에선 `medium`에서 천장을 친다. 더 어려운 문제(여러 단계 산술, 코드 버그 찾기)와 Sonnet/Opus 비교가 다음 판.
- 한 번씩만 돌려 분산이 크다. `--repeat N`으로 문제당 여러 번 돌려 신뢰구간을 그리면 좋다.
- 비용은 Claude Code가 보고하는 `total_cost_usd`를 그대로 쓴다. 프롬프트 캐시 적중에 따라 같은 레벨도 달라진다.
- Agent 도구의 `effort`(서브에이전트) 경로는 안 쟀다. 같은 문제를 `--agents` 정의 + 효과 레벨별 서브에이전트로 돌리는 변형이 가능하다.

## 7. 출처
- Claude Code changelog 2.1.292 (Agent `effort`), 2.1.293 (기본 Haiku 5.5): https://code.claude.com/docs/en/changelog
- Claude Haiku 5.5: https://www.anthropic.com/claude-haiku-5-5
- 문제 출처: Cognitive Reflection Test(bat-and-ball, 연꽃잎), 널리 알려진 LLM 퀴즈(strawberry, Sally의 자매)
- 실제 실행 결과: sample-results.json

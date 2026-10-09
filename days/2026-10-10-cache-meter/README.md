# cache-meter — 프롬프트 캐시가 진짜 맞는지 재는 측정기

## 1. 무엇을 만들었나
Python CLI `cache_meter.py`. 약 2만 토큰짜리 가짜 사내 핸드북을 시스템 프롬프트로 두고 같은 질문을 `claude -p`로 N회 던지며, 응답 JSON의 `usage.cache_creation_input_tokens`(캐시 쓰기), `cache_read_input_tokens`(읽기), `input_tokens`(캐시 안 됨), `total_cost_usd`, `duration_ms`를 모은다. 시나리오 세 개를 같은 조건으로 비교한다. `stable`(매번 동일), `volatile-head`(프롬프트 맨 앞에 시각·난수 한 줄), `volatile-tail`(같은 줄을 맨 뒤에). 호출별 적중 기호 행, 2회차 이후 적중률, 캐시 쓰기 토큰 합, 비용, 누적 비용 곡선을 ASCII로 그린다. `--dry-run`은 가짜 결과, `--from`은 저장된 결과 재렌더.

## 2. 왜 만들었나
10월 7일 API 릴리스 노트에서 Sonnet 5.5의 캐시 읽기 가격이 $0.20에서 $0.10/MTok로 절반이 됐다([release notes](https://platform.claude.com/docs/en/release-notes/api)). 싸진 건 "캐시가 맞을 때"뿐이고, 시스템 프롬프트에 날짜나 세션 ID를 넣어 캐시를 조용히 깨는 서비스는 혜택을 못 받는다. 그게 내 프롬프트에서 일어나는지 숫자로 보는 도구가 필요했고, 키 없이 Claude Code 로그인만으로 되는지도 확인하고 싶었다.

## 3. 어떻게 만들었나
1. **긴 프롬프트**: 시드 고정 난수로 60개 섹션의 핸드북(23,034자, 약 1.2만 토큰)을 만들고 끝에 정답("환불 기한 45일")을 넣어 모델이 실제로 읽게 했다. 짧으면 캐시 최소 길이에 걸려 아무것도 안 보인다.
2. **호출**: `--system-prompt`로 핸드북을 넣고 `--tools ""`, `--effort low`, `--no-session-persistence`, `--output-format json`. 같은 접두사 호출이 겹치면 둘 다 "쓰기"가 되는 경쟁이 있어 호출 사이 0.5초 쉰다.
3. **집계**: 2회차 이후 평균 적중률(읽기 ÷ (읽기+쓰기+비캐시)), 2회차 이후 캐시 쓰기 토큰 합(0이 이상적), 비용, 시간. 호출마다 ■(읽기 90%↑)·▒(쓰기 90%↑)·◧(읽기 50%↑)··(그 외) 기호로 한 줄 요약.
4. **발견 1 — Claude Code의 접두사가 따로 있다**: volatile 시나리오에서도 매번 9,173토큰은 읽기로 잡혔다. `--system-prompt`를 줘도 Claude Code 자체의 앞부분(시스템 블록)이 먼저 캐시되고, 내가 준 프롬프트는 그 뒤에 한 덩어리로 붙는다.
5. **발견 2 — 꼬리에 넣어도 똑같이 깨진다**: head와 tail의 숫자가 토큰 단위까지 같았다(쓰기 11,77x, 읽기 9,173). Claude Code는 사용자 시스템 프롬프트를 캐시 블록 하나로 다루므로 어디를 바꾸든 그 블록 전체가 다시 쓰인다. "변하는 건 뒤에 두면 된다"는 API 직접 호출 때의 상식이 CLI에서는 안 통한다. dry-run의 가짜 결과는 이 발견 전에 만든 것이라 tail이 부분 적중하는 모양인데, 실제와 다르다는 점을 그대로 남겼다.
6. **발견 3 — 비용 2배**: 4회 기준 stable $0.0050, volatile $0.0100. 첫 호출은 셋 다 비슷하고 2회차부터 갈린다.
7. **구조화 출력 불필요**: 답은 안 쓰고 usage만 보므로 `--json-schema`를 안 썼다. 그래도 `--max-turns 3`은 유지했다(같은 날 effort-race에서 배운 것).

## 4. 사용법
```bash
cd days/2026-10-10-cache-meter
python3 cache_meter.py                       # Haiku 5.5, 3시나리오 × 4회 = 12회 (약 1분, 2센트)
python3 cache_meter.py -n 6 --scenarios stable,volatile-head
python3 cache_meter.py --model claude-sonnet-5-5   # 캐시 반값 모델로 (비용 약 20배)
python3 cache_meter.py --from sample-results.json  # 저장된 결과 다시 그리기
python3 cache_meter.py --dry-run             # 모델 없이 모양만
```
자기 서비스 프롬프트로 재려면 `handbook()`을 그 프롬프트로 바꾸고 `QUESTION`을 바꾸면 된다.

## 5. 테스트 결과
오프라인 (`bash test.sh`, CI에서도 실행):
```
== 1) python3 -m unittest
  Ran 14 tests  OK   (핸드북 결정성·길이, 시나리오별 프롬프트 위치·유일성, 적중률 수식, 2회차 제외 집계,
                       오류 집계, 막대, 렌더 섹션·기호 행·실패 표시, 백엔드 usage 파싱·is_error·깨진 stdout, CLI 저장→재로드, 인자 검증)
== 2) dry-run 그래프
  ✅ 3시나리오 × 4회 그래프
== 결과: PASS
```
실제 Haiku 5.5 (`python3 cache_meter.py -n 4`, 2026-10-10, 57초):
```
  stable         #1  write  20910  read      0  uncached    2  $0.00423   2.3s
  stable         #2  write      0  read  20910  uncached    2  $0.00028   1.5s
  stable         #3  write      0  read  20910  uncached    2  $0.00025   1.2s
  stable         #4  write      0  read  20910  uncached    2  $0.00027   1.4s
  volatile-head  #1  write  11775  read   9173  uncached    2  $0.00251   1.4s
  volatile-head  #2  write  11773  read   9173  uncached    2  $0.00252   1.6s
  volatile-tail  #1  write  11773  read   9173  uncached    2  $0.00252   1.5s
  volatile-tail  #2  write  11774  read   9173  uncached    2  $0.00248   1.2s
  (각 4회, 나머지 행 동일 패턴)

호출별 캐시 읽기 비율 (■ 읽기, ▒ 쓰기, · 캐시 안 됨)
  stable         ▒ ■ ■ ■
  volatile-head  · · · ·
  volatile-tail  · · · ·

2회차 이후 평균 캐시 적중률
  stable         ████████████████████████████ 100.0%
  volatile-head  ████████████░░░░░░░░░░░░░░░░  43.8%
  volatile-tail  ████████████░░░░░░░░░░░░░░░░  43.8%

2회차 이후 캐시 쓰기 토큰 합 (0이 이상적)
  stable                0
  volatile-head     35323
  volatile-tail     35321

총 비용
  stable         ██████████████░░░░░░░░░░░░░░ $0.00502
  volatile-head  ████████████████████████████ $0.01007
  volatile-tail  ████████████████████████████ $0.01003
```
`bash e2e.sh`는 같은 측정을 한 번 더 돌려 네 가지를 확인한다. 전부 응답, stable 행에 ■ 등장, stable 적중률 > volatile-head, 종료 코드 0. 결과는 pass=4 fail=0.

## 6. 한계와 다음 아이디어
- 측정 대상이 Claude Code CLI 경로다. API를 직접 부르며 `cache_control` 위치를 내가 정하는 경우는 tail 시나리오가 부분 적중할 수 있다. SDK 버전(키 필요)을 붙이면 둘을 나란히 비교할 수 있다.
- 캐시 TTL(Claude Code는 1시간 캐시를 쓴다)을 넘기는 간격 실험은 안 했다. `--interval`로 호출 간격을 벌리면 만료 곡선이 보인다.
- 비용은 Claude Code가 보고하는 `total_cost_usd`를 그대로 쓴다. 모델 가격표로 "캐시가 없었다면" 비용을 계산해 절감액을 함께 보여 주면 더 직관적이다.
- 프롬프트가 하나(핸드북)뿐이다. 길이를 2천·8천·3만 토큰으로 바꿔 캐시 최소 길이 경계를 찾는 변형이 다음 판.

## 7. 출처
- API 릴리스 노트 2026-10-07 (Sonnet 5.5 캐시 읽기 $0.10/MTok): https://platform.claude.com/docs/en/release-notes/api
- 프롬프트 캐싱 문서: https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- Claude Code CLI `-p` 출력의 `usage` 필드: `claude -p … --output-format json`
- 같은 날의 effort-race(`--max-turns 3` 교훈): ../2026-10-10-effort-race/
- 실제 측정 결과: sample-results.json

# otel-tap

## 1. 무엇을 만들었나
Claude Code가 내보내는 OpenTelemetry 로그·지표(·트레이스)를 내 컴퓨터에서 받아 JSONL로 쌓고, 비용·토큰·캐시 적중률·도구 실패·API 오류로 요약하는 **CLI 스크립트**(`otel_tap.py`, 표준 라이브러리만). `env`(켤 환경변수 출력) · `serve`(127.0.0.1 OTLP/HTTP JSON 수신) · `ingest`(저장해 둔 페이로드 추가) · `report`(Markdown/`--json` 요약) 네 명령이 전부다. 프롬프트·응답·도구 입력·계정 식별자는 저장 전에 지운다.

## 2. 왜 만들었나
- 10-14 Claude Platform이 Managed Agents·Messages API·SDK의 OpenTelemetry 트레이스 내보내기를 공개 베타로 열었다: [Agent observability on the Claude Platform](https://claude.com/resources/articles/agent-observability-on-the-claude-platform). 같은 날 Claude Code 2.1.300은 OTel 지표에 캐시 수명별 토큰 분리를 넣었다([변경 기록](https://code.claude.com/docs/en/changelog)).
- Grafana·Datadog·Langfuse 같은 수집기를 세우기 전에 "내 세션이 실제로 무엇을 내보내는지, 하루 비용이 얼마인지"를 5분 안에 보고 싶었다. 기존 `spend-gate`(트랜스크립트로 금액 어림)·`cache-meter`(API 호출 하나 측정)와 달리 **실제 세션의 텔레메트리**를 프롬프트·도구 단위로 쪼갠다. 오늘 news 1번 "현실 적용"의 첫 항목이다.

## 3. 어떻게 만들었나
1. 문서([monitoring-usage](https://code.claude.com/docs/en/monitoring-usage))에서 환경변수(`CLAUDE_CODE_ENABLE_TELEMETRY`, `OTEL_EXPORTER_OTLP_PROTOCOL=http/json` …)와 이벤트 이름·속성(`api_request`의 `cost_usd`·`cache_read_tokens`, `tool_result`의 `success`·`duration_ms` …)을 읽었다.
2. 수신기는 `http.server`로 `/v1/logs`·`/v1/traces`·`/v1/metrics`에 POST를 받는다. protobuf는 `415`와 함께 "http/json으로 바꿔라"를 돌려준다(protobuf 파서는 의존성이 필요해서 일부러 뺐다). gzip 본문은 풀고, 본문 10MB 상한, 기본 바인드는 루프백만 허용한다(`--allow-remote` 없이는 거부).
3. 저장은 레코드를 `event`/`span`/`metric` 세 종류로 정규화한 JSONL. OTLP JSON의 `intValue`가 문자열인 점과 `aggregationTemporality`(delta는 합, cumulative는 시리즈별 마지막 값)를 처리했다.
4. **실측으로 고친 것**: 이 러너의 Claude Code 2.1.300을 수신기에 물려 보니(로그인 전이라 모델 호출은 없음) 로그 속성의 숫자가 `prompt_length: '2'`처럼 **문자열**로 온다. 처음 구현은 이를 0으로 읽어 토큰·비용 합계가 0이 될 뻔했다. 숫자 문자열도 읽도록 고치고 회귀 테스트(`test_numbers_sent_as_strings`)를 넣었다. 또 모델 호출 전에는 `api_error`에 `status_code`가 없어서 오류 메시지 앞 70자로 묶도록 했다.
5. 도구: Claude Code(문서 확인·실측), Python 표준 라이브러리, curl. 모델 호출은 쓰지 않았다.

## 4. 사용법
```bash
cd days/2026-10-15-otel-tap
python3 otel_tap.py serve --out tap.jsonl      # 터미널 A: 수신 대기 (출력에 켤 환경변수도 나온다)
python3 otel_tap.py env                         # 터미널 B: 환경변수 확인 → eval "$(python3 otel_tap.py env)"
claude                                          # 같은 터미널 B에서 평소처럼 작업
python3 otel_tap.py report tap.jsonl            # 요약 (--json 으로 기계가 읽는 형태)
```
- 포트를 바꾸면 `serve --port 4999`와 `env --port 4999`를 맞춘다. 내보내기 주기는 로그 2초·지표 10초로 줄여 둔다(환경변수 `OTEL_*_EXPORT_INTERVAL`).
- 프롬프트 등을 남기고 싶으면 `serve --keep-content`. 트레이스 실험은 `env --traces`(문서 예시는 protobuf라 JSON이 되는지는 **미확인**).
- 이미 저장해 둔 OTLP JSON 페이로드는 `ingest 파일… --out tap.jsonl`. 데모 데이터는 `tests/fixtures/`.

예시 출력(`tests/fixtures`를 ingest한 결과, 일부):
```
- 4회 · 비용 $0.0855 · 입력 2,600 · 출력 1,950 · 캐시 읽기 33,000 · 캐시 생성 18,500 · **캐시 적중률 61.0%**
| 도구 | 호출 | 실패 | 평균 ms | 최대 ms |
| Bash | 2 | 1 | 2,575 | 4,300 |
```

## 5. 테스트 결과
`bash test.sh` (키·모델 없이 돈다):
```
Ran 34 tests in 4.073s

OK
OK: 서버 프로세스 스모크 (포트 37363, 25건 수신, 요약 일치, 프롬프트 미저장)
```
- 단위 34개: 파싱(OTLP 값 형식·이벤트 이름·스팬 길이·지표 시간성), 삭제(프롬프트·이메일·도구 입력 제거, 긴 문자열 자르기), 요약 숫자(비용·캐시 적중률·도구 실패·오류·TTFT·delta/cumulative), 서버(3개 신호, gzip, protobuf 415, 잘못된 입력 400/404, 동시 POST 8개가 줄을 섞지 않음), CLI(루프백 아닌 바인드 거부, 읽기 실패 exit 2).
- 스모크: 실제 서버 프로세스에 `curl`로 세 신호를 쏘고 요약 일치·프롬프트 미저장을 확인.

**실측 (로그인 없는 러너, 모델 호출 없음)**: 수신기에 `env` 출력을 적용하고 `claude -p "ok"`를 실행하자 Claude Code 2.1.300이 `http/json`으로 8건을 보냈다.
```
## 이벤트 종류
- plugin_loaded 3 · managed_settings_resolved 1 · user_prompt 1 · api_error 1
## 지표
- active_time.total: 0.116
- session.count: 1
```
`e2e.sh`(모델 호출 포함)는 이 러너에 로그인이 없어 **실행하지 못했다**(`claude에 로그인되어 있지 않다. e2e 미실행(exit 3)`). 따라서 `api_request`(비용·토큰)·`tool_result` 이벤트가 실제 세션에서 문서대로의 속성 이름으로 오는지는 픽스처(문서 기반) 수준에서만 검증됐다. CI에서는 e2e 미실행.

## 6. 한계와 다음 아이디어
- **실제 모델 호출 세션의 이벤트는 미확인.** 속성 이름은 문서를 따랐다. 로그인된 환경에서 `bash e2e.sh`를 돌려 `api_request`가 들어오는지 확인해야 한다.
- 수신은 JSON만. Claude Code 트레이스 기본값이 protobuf라면 받을 수 없다(415). protobuf 지원은 의존성 없이는 어렵다 — 폴더 안에 `opentelemetry-proto`를 두는 별도 판이 후보.
- Claude Platform(Managed Agents·Messages API)의 트레이스는 Console 목적지 설정이 필요하고 외부에서 도달 가능한 엔드포인트가 필요하다. 로컬 수신기는 대상이 아니다. GenAI 시맨틱 컨벤션(`gen_ai.*`) 스팬 요약은 아직 없다.
- 비용은 이벤트의 `cost_usd`를 그대로 합산한다. 가격표로 재계산하지 않는다.
- 다음: `--since 1h` 같은 시간 필터, 프롬프트별 타임라인, 캐시 적중률이 낮은 프롬프트 경고, 일별 JSONL 회전.

## 7. 출처
- [Agent observability on the Claude Platform (claude.com, 2026-10-14)](https://claude.com/resources/articles/agent-observability-on-the-claude-platform)
- [Claude Code Monitoring (OpenTelemetry 설정·이벤트·지표·트레이스)](https://code.claude.com/docs/en/monitoring-usage)
- [Claude Code 변경 기록 2.1.299·2.1.300](https://code.claude.com/docs/en/changelog)
- [Claude Platform API 릴리스 노트 10-14](https://platform.claude.com/docs/en/release-notes/api)
- [claude-cookbooks #922: OpenTelemetry 트레이싱 쿡북](https://github.com/anthropics/claude-cookbooks/commit/b2b0aa1ff7d8980b005b225d3802969c87bedad5)
- [OTLP 명세](https://opentelemetry.io/docs/specs/otlp/)

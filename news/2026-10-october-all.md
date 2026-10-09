# 2026년 10월 Claude 소식 전체 수집 (10-01 ~ 10-10)

수집 시각: 2026-10-10 07:00 KST. 피드 9개는 feed-bookmark(`--max-age-hours 400`)로, 피드가 없는 페이지는 직접 읽어 10월 1일 이후 항목만 모았다. 날짜는 KST.

## 소스 점검

| 소스 | 상태 | 10월 항목 |
|------|------|-----------|
| anthropic.com/news | 읽힘 | 7 |
| claude.com/blog | 읽힘 | 11 |
| anthropic.com/engineering | 읽힘, 10월 글 없음 (최신 4월 23일) | 0 |
| claude.dev/blog | 읽힘 | 3 |
| platform.claude.com API 릴리스 노트 | 읽힘 (docs.claude.com에서 301 리다이렉트) | 6일분 |
| support.claude.com 릴리스 노트 (Claude 앱) | 읽힘 | 2 |
| code.claude.com changelog | 읽힘 | 2.1.287~2.1.296 |
| GitHub 피드 9개 | 전부 읽힘 (조용함 1: cookbooks) | 48 |

## 1. 공식 발표 (anthropic.com/news)

- 10-08 [2026 Usage Policy update](https://www.anthropic.com/news/2026-usage-policy-update) — 기만적 캠페인·가짜 계정 조항 추가, 선거 조항 축소, 무기·감시 강화. 11월 12일 적용.
- 10-08 [Building on our commitment to American scientific discovery](https://www.anthropic.com/news/genesis-mission-commitment) — 미국 과학 연구 지원 약속.
- 10-08 [Introducing the Anthropic Cyber Mission](https://www.anthropic.com/news/anthropic-cyber-mission) — 사이버 보안 전담 이니셔티브.
- 10-07 [Introducing Claude Haiku 5.5](https://www.anthropic.com/claude-haiku-5-5) — 가장 빠르고 싼 소형 모델. 1M 컨텍스트, 128K 출력, 적응형 사고.
- 10-06 [Expanding the Cyber Verification Program](https://www.anthropic.com/news/cyber-verification-program) — 검증된 보안 전문가에게 고급 사이버 기능과 완화된 차단 분류기.
- 10-02 [Anthropic invests $100 million to train 10,000 engineers](https://www.anthropic.com/news/claude-frontier-academy) — 기업 AI 인력 격차 대응.
- 10-01 [Barclays scales Claude](https://www.anthropic.com/news/barclays-scales-claude) — Barclays 운영·고객 경험에 Claude 확대.

## 2. 제품·고객 글 (claude.com/blog)

- 10-08 [Build live dashboards and animate explainers with Claude](https://claude.com/resources/articles/dashboards-and-motion) — Dashboards·Motion 베타. Docs·Slides·Design은 베타 종료, 무료 플랜 포함 전체 제공.
- 10-08 [Building effective agent automations](https://claude.dev/blog/building-effective-agent-automations/) — 예약 Managed Agents 참조 구현과 실패 회피 규칙 6가지.
- 10-08 [How Block orchestrates Claude Fable across thousands of pull requests](https://claude.com/resources/articles/how-block-orchestrates-claude-fable-across-thousands-of-pull-requests) — Fable 5로 대규모 코드 마이그레이션 오케스트레이션.
- 10-07 [Automating eval design and hillclimbing with Claude](https://claude.dev/blog/automating-eval-design-and-hillclimbing/) — 편향 없이 eval을 설계·최적화하는 원칙과 claude-api 스킬의 `build-eval`·`hillclimb`.
- 10-06 [How Comcast and Booz Allen use Claude Mythos to secure their codebases](https://claude.com/resources/articles/how-comcast-booz-allen-use-claude-mythos-to-secure-their-codebases) — Project Glasswing으로 기존 스캐너가 놓친 취약점 발견·검증·수정.
- 10-06 [Claude now works with Google Docs, Sheets, and Slides](https://claude.com/resources/articles/claude-now-works-in-google-docs-sheets-and-slides) — Workspace 애드온과 베타 커넥터.
- 10-06 [Expanding the Claude Startups program](https://claude.com/resources/articles/were-expanding-the-claude-startups-program-to-help-founders-build)
- 10-06 [Claude Code in the cloud: a field guide to cloud sessions](https://claude.dev/blog/claude-code-in-the-cloud/) — 클라우드 세션 동작, 맞는 워크플로, GitHub 연결.
- 10-05 [How Cresta turned CX expertise into an agent builder on the Claude Agent SDK](https://claude.com/resources/articles/how-cresta-turned-cx-expertise-into-an-agent-builder-on-the-claude-agent-sdk) — 에이전트를 만드는 에이전트 Conductor.
- 10-01 [Getting started with Claude Code mods](https://claude.dev/blog/getting-started-with-claude-code-mods/) — 모드 입문 (claude.dev).

## 3. API 릴리스 노트 (platform.claude.com)

- 10-09 Managed Agents 동적 워크플로(베타): 에이전트가 여러 에이전트를 단계별로 돌리는 프로그램을 쓰고 서버가 백그라운드 실행.
- 10-08 Compliance API 채팅 엔드포인트가 통합 Claude 경험의 채팅도 반환(Enterprise 베타).
- 10-07 Sonnet 5.5 캐시 읽기 $0.20 → $0.10/MTok. Haiku 5.5 출시(1M 컨텍스트, 128K 출력, 적응형 사고). Haiku 4.5용 코드가 5.5에서 400 나는 경우: 수동 확장 사고, temperature/top_p/top_k, prefill, `computer_20250124`, system/tools/이전 턴 편집, Bedrock 구조화 출력. Python·TS SDK에 브라우저·컴퓨터 사용 도구 베타 클래스. Max·Team 월간 API 크레딧. Managed Agents `limited` 네트워킹이 web_search/web_fetch에도 `allowed_hosts` 적용, `web_fetch`는 세션에 이미 나온 URL만.
- 10-06 Models API에 `capabilities.server_tools`.
- 10-05 Models API에 `capabilities.thinking.types.disabled`.
- 10-01 Models API에 `line` 필드(opus 등). Dreams 연구 프리뷰가 Opus 5.5·Fable 5.1·Sonnet 5.5 지원.

## 4. Claude 앱 릴리스 노트 (support.claude.com)

- 10-07 Haiku 5.5 출시. Max·Team 플랜 월간 API 크레딧(Console 조직 연결).

## 5. Claude Code 체인지로그 (2.1.287 → 2.1.296, 10일간 10개 릴리스)

- 10-01 **2.1.287** — Claude Mods(플러그인이 더 깊은 동작 수정). 내장 모드 "You should know"(`/plugin enable cc-plugin-you-should-know@builtin`). Opus 4.7+·Fable이 Bedrock/Vertex/Foundry/게이트웨이에서 1M 컨텍스트 기본(`CLAUDE_CODE_DISABLE_1M_CONTEXT=1`).
- 10-02 **2.1.288** — 모드용 `$.ui.selection()`. 클라우드 세션 내장 `gh api`. Ctrl+C로 지운 프롬프트 복구.
- 10-03 **2.1.289** — 팀메이트용 `agent.spawn`. `claude auth status` 변경 되돌림. 플러그인 코드 pane 큰 파일 속도 개선.
- 10-05 **2.1.290** — `claude attach <name>`·`claude logs <name>`가 세션 이름 일부로 동작. Claude in Chrome을 프로젝트 설정 파일로 켤 수 없음. WebSearch 예산이 200회 후 끝나지 않고 시간에 따라 충전.
- 10-06 **2.1.291** — 2.1.290 클라우드 세션 권한 응답 누락, 2.1.288 종료 시 마지막 메시지 유실 회귀 수정.
- 10-06 **2.1.292** — `claude plugin install --marketplace <source>`. Agent 도구 `effort` 파라미터. 로컬 MCP 프로토콜 2026-07-28 기본.
- 10-07 **2.1.293** — Haiku 5.5가 기본 Haiku. `subagentStatusLine`에 `agentType`. 2.1.281 auto 모드 거부 메시지 변경 되돌림.
- 10-08 **2.1.294** — 지시문형 `prompt`/`agent` 훅이 막아야 할 것을 통과시키던 버그 수정. Stop/SubagentStop `prompt` 훅 판정 개선.
- 10-08 **2.1.295** — 훅 `onFailure: "block"`. Program Status Protocol(OSC 7501). claude.ai 커넥터 MCP 2026-07-28 기본.
- 10-09 **2.1.296** — 게이트웨이 `managed.policies[]`에 `code` 키. 서브에이전트 `autoCompactWindow`. `CLAUDE_CODE_WORKFLOW_SUBAGENT_MODEL`.

## 6. GitHub 피드 (48개)

- **claude-code 릴리스 10개**: v2.1.287(10-02) ~ v2.1.296(10-10). 위 5절과 동일.
- **claude-agent-sdk-typescript 10개**: v0.3.287 ~ v0.3.296. Claude Code와 같은 날 같은 번호로 따라감.
- **anthropic-sdk-python 5개**: v1.10.0(10-01), v1.11.0(10-01), v1.12.0(10-08), v1.12.1(10-08), v1.13.0(10-10).
- **anthropic-sdk-typescript 10개**: sdk-v0.132.0(10-08), v0.132.1, v0.133.0(10-10)과 google-cloud·vertex·aws·foundry·bedrock 플랫폼 SDK 패치.
- **claude-agent-sdk-python 3개**: v0.2.163(10-01), v0.2.164(10-07), v0.2.165(10-09).
- **anthropics/skills 커밋 3개**: claude-api 스킬 갱신 — Managed Agents 퀵스타트 온보딩(10-05), Haiku 5.5를 현재 Haiku로(10-09), 동적 워크플로와 워크플로 퀵스타트 4종(10-10).
- **claude-quickstarts 커밋 4개**: NVIDIA OpenShell 자체 호스팅 샌드박스 데모(10-01), Daily brief 퀵스타트를 Sonnet 5.5로(10-07), 현재 SDK·모델로 퀵스타트 재실행(10-07), computer/browser 툴셋(10-08).
- **claude-cookbooks**: 10월 커밋 없음.
- **Simon Willison 3개**: Quoting Felix Rieseberg(10-06), Scrimshaw Jukebox(10-07), Claude Haiku 5.5(10-08).

## 아직 이 저장소가 다루지 않은 10월 소재

- Managed Agents 동적 워크플로(10-09, API 베타)와 claude-api 스킬의 워크플로 퀵스타트 4종
- 내장 모드 "You should know"(2.1.287) — 옆에서 놓친 걸 짚어 주는 사이드 에이전트
- `$.ui.selection()`(2.1.288), `agent.spawn`(2.1.289), `autoCompactWindow`(2.1.296) 같은 모드·서브에이전트 API
- Models API의 `capabilities`·`line` 필드(10-01~06) — 모델 능력표를 자동으로 그리는 도구
- SDK의 브라우저·컴퓨터 사용 도구 베타 클래스(10-07)
- Sonnet 5.5 캐시 읽기 반값(10-07) — 캐시 적중률 측정 도구
- eval 설계·힐클라이밍 글(10-07)과 `build-eval`/`hillclimb` 서브커맨드
- Claude Code 클라우드 세션 가이드(10-06), Google Docs·Sheets·Slides 연동(10-06)

## 현실 적용 아이디어 (아직 다루지 않은 소재 8개, 항목당 5개 이상)

### A. Managed Agents 동적 워크플로 (10-09, API 베타)
- 데이터팀 → 수백 개 테이블의 스키마 문서화를 에이전트가 단계별 프로그램으로 분배 → 한 세션의 25개 자식 스레드 한계를 넘는 작업을 한 번에
- 보안팀 → 저장소 수십 개의 의존성 취약점 조사를 "저장소별 조사 → 중복 제거 → 우선순위" 3단계로 → 사람이 배치를 나누지 않아도 된다
- 이 저장소 → 매일 수집한 소식 N개를 각각 요약·적용처 작성하는 작업을 워크플로로 → 소식이 많은 날도 수집 시간이 늘지 않는다
- 고객 지원 → 티켓 1,000건을 분류 → 묶음별 답변 초안 → 검수 단계로 → 한 에이전트가 컨텍스트를 다 채우는 문제 회피
- 컨텐츠팀 → 블로그 글 하나를 다국어 5개로 번역하고 각 언어 검수자가 따로 보는 팬아웃 → 번역 품질 검수가 병렬
- 주의 → Managed Agents 전용(API 키·유료)이라 이 저장소에서는 dry-run 설계만 가능. Claude Code의 Workflow 도구와는 별개다

### B. 내장 모드 "You should know" (2.1.287)
- 리팩터링 세션 → 옆 에이전트가 "이 함수 다른 곳에서도 호출됨" 같은 놓친 영향 범위를 짚음 → 회귀를 PR 리뷰 전에 잡는다
- 온보딩 중인 개발자 → 낯선 레포에서 작업할 때 관례·금기(마이그레이션 순서 등)를 알려 줌 → 멘토 부담 감소
- 이 저장소 → 하루 결과물 만들 때 "루트 README 행 빼먹음", "출처 URL 깨짐"을 사이드 에이전트가 지적 → 푸시 전 재확인 규칙의 자동화 후보
- 비용 민감한 팀 → 사이드 에이전트가 턴마다 돈을 쓰므로 `/plugin disable`로 끄고 켜는 기준 정하기 → 효과 대비 비용 측정이 먼저
- 모드 작성자 → 내장 모드의 소스 구조를 읽어 자기 모드의 참고 구현으로 → 공식 모드가 어떻게 pane·notify를 쓰는지 배운다

### C. 모드·서브에이전트 API: `$.ui.selection()`(2.1.288), `agent.spawn`(2.1.289), `autoCompactWindow`(2.1.296)
- 코드 리뷰어 → 트랜스크립트에서 드래그한 코드 조각을 `$.ui.selection()`으로 받아 "이 부분만 설명/번역/테스트 생성" 명령 → 긴 답변에서 필요한 줄만 다룬다
- 외국어 사용자 → 선택한 영어 답변을 한국어로 pane에 띄우는 모드 → 전체 번역 없이 부분만
- 팀 리더 역할 모드 → `agent.spawn`으로 팀메이트를 띄우고 역할 분담 → 멀티 에이전트 실험을 설정 파일 없이 코드로
- 긴 조사 서브에이전트 → `autoCompactWindow`를 짧게 줘 서브에이전트만 자주 압축 → 부모 대화는 그대로 두고 자식 비용만 줄인다
- 이 저장소 → 다마고치 모드에 `$.ui.selection()`으로 "선택한 코드를 펫에게 먹이기" 같은 장난 기능 → 모드 API 세 개를 한 프로젝트에서 익힌다

### D. Models API `capabilities`·`line` 필드 (10-01 ~ 10-06)
- 플랫폼팀 → 모델 목록을 돌며 컨텍스트·최대 출력·thinking disabled 허용·server_tools 지원 여부 표를 자동 생성 → 문서가 아니라 API가 진실
- 라우터 만드는 팀 → `line`으로 opus/sonnet/haiku를 묶어 "가장 싼 최신 haiku" 같은 선택을 코드로 → 모델 ID 하드코딩 제거
- 마이그레이션 → 새 모델이 `thinking: disabled`를 거부하는지 미리 확인해 400을 예방 → 배포 후 장애 대신 배포 전 경고
- 이 저장소 → 매일 수집 때 모델 목록 diff를 찍어 새 모델·능력 변화를 소식으로 → 발표보다 API 반영이 먼저일 때가 있다
- 비용 대시보드 → 모델별 가격은 API에 없으므로 가격표와 능력표를 합친 한 장 → 선택 회의가 짧아진다

### E. SDK 브라우저·컴퓨터 사용 도구 베타 클래스 (10-07)
- QA팀 → 회귀 테스트 시나리오를 자연어로 쓰고 SDK의 browser 도구 루프로 실행 → Playwright 스크립트 유지 비용 감소
- 운영팀 → 관리자 콘솔의 반복 클릭 작업(월간 리포트 내려받기)을 승인 콜백과 함께 자동화 → 위험한 클릭은 사람이 승인
- 데이터 수집 → 피드가 없는 사이트(anthropic.com/news)를 브라우저 도구로 읽어 구조화 → feed-bookmark의 빈칸을 메운다
- 접근성 점검 → 페이지를 돌며 스크린리더 관점의 문제를 모델이 기록 → 수동 감사 전 1차 필터
- 이 저장소 → API 키가 없어 SDK 클래스는 못 돌리지만, 같은 일을 Claude in Chrome 도구로 재현해 비교 → "SDK vs 확장" 차이 기록

### F. Sonnet 5.5 캐시 읽기 반값 (10-07, $0.20 → $0.10/MTok)
- 긴 시스템 프롬프트를 쓰는 서비스 → 같은 접두사를 반복 호출해 `cache_read_input_tokens` 비율을 재는 측정기 → 실제 절감액을 숫자로
- 프롬프트 튜닝 → 시스템 프롬프트에 날짜·세션 ID를 넣어 캐시를 깨고 있는지 자동 탐지 → "조용한 캐시 무효화" 잡기
- 이 저장소 → `claude -p --output-format json`의 usage 캐시 필드로 같은 프롬프트 N회 호출 비용 곡선을 그리는 CLI → 키 없이도 측정 가능
- 비용 보고 → 모델별 캐시 적중률을 주간 리포트에 → 캐시 전략 변경의 효과를 추적
- 라우팅 → 캐시가 모델별로 분리되므로 "싼 모델로 바꾸면 캐시를 잃는다"를 수치로 보여 주는 계산기 → 모델 교체 결정에 근거

### G. eval 설계·힐클라이밍 (10-07, claude-api 스킬 `build-eval`/`hillclimb`)
- 고객 지원 봇 → 실제 대화 50건으로 eval 세트를 만들고 프롬프트 변경마다 점수 비교 → "느낌"이 아니라 숫자로 배포 결정
- 분류 파이프라인 → train/validation/test 분리로 과적합 없이 프롬프트 최적화 → 눈으로 고르던 예시가 체계화
- 이 저장소 → 수집 단계의 "적용 아이디어 품질"을 평가하는 작은 eval → 루틴이 쓰는 프롬프트를 힐클라이밍
- 번역 서비스 → LLM 판정자 편향을 피하는 채점 설계 → 자기 모델이 자기 답을 후하게 주는 문제 방지
- 신규 모델 출시 때 → 같은 eval을 돌려 교체 가능 여부를 하루 안에 판단 → 마이그레이션 리스크 축소

### H. Claude Code 클라우드 세션 가이드 (10-06)와 Google Docs·Sheets·Slides 연동 (10-06)
- 야간 배치 → 긴 마이그레이션을 클라우드 세션에 맡기고 `claude attach <name>`으로 아침에 확인 → 노트북을 켜 둘 필요 없음
- 이 저장소 → 06:45 루틴 자체가 클라우드 세션이므로 가이드의 권장(GitHub 연결, 워크플로 유형)을 점검 → 실패 원인 파악에 도움
- 기획팀 → 요구사항 Google Docs에서 바로 Claude로 요약·질문 → 문서 복붙 없이
- 재무팀 → Sheets 안에서 수식 설명과 이상치 점검 → 스프레드시트를 떠나지 않는다
- 발표 준비 → Slides에서 슬라이드별 발표 노트 생성 → 데크 제작 시간 단축

## 다음 주제 선정 (2절 기준)

**1순위: 프롬프트 캐시 측정기 (F)** — `claude -p --output-format json`의 `cache_read_input_tokens`·`cache_creation_input_tokens`·`total_cost_usd`로 같은 시스템 프롬프트를 N회 호출하며 캐시 적중률과 누적 비용 곡선을 ASCII로 그리는 CLI. 날짜·난수를 프롬프트에 섞어 캐시를 깨는 "조용한 무효화" 사례를 의도적으로 재현해 비교한다. 키 없이 돌아가고, 결과가 그래프라 보는 재미가 있으며, Sonnet 5.5 캐시 반값(10-07)이 계기다. 루트 표의 effort-race(토큰·시간)와 지표가 다르다.

**2순위: 선택 영역 모드 (C)** — `$.ui.selection()`으로 트랜스크립트에서 선택한 텍스트를 받아 한국어 번역·설명을 pane에 띄우는 모드. 모드 API 학습 가치가 크고 다마고치와 결합할 수 있다. 단, selection API 문서를 먼저 읽어야 하고 `-p` e2e가 어렵다.

**3순위: 모델 능력표 생성기 (D)** — Models API로 모델별 컨텍스트·출력·thinking·server_tools 표를 Markdown으로. 유용하지만 API 키가 필요해 dry-run이 주가 된다.

보류: A(Managed Agents 전용·유료), E(SDK 키 필요), G(세션 하나에 끝내기 어려움), H(측정·검증이 어려움).

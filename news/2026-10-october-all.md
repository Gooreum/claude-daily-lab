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

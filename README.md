# claude-daily-lab

매일 최신 Claude 소식을 바탕으로 AI가 스스로 만드는 작은 스킬·서비스 실험실입니다.
예약 작업이 매일 아침 Claude/Anthropic 소식을 수집하고, 그중 하나를 골라 그날 안에 만들 수 있는 작은 결과물을 제작해 쌓아 갑니다.
사람은 방향(RULES.md)만 정하고, 수집·선정·제작·테스트·문서화는 모두 AI가 수행합니다.

## 동작 방식

매일 **06:45 KST**에 예약 작업이 자동 실행되며 다음 순서로 진행합니다.

1. **수집** — 최근 48시간의 Claude/Anthropic 소식을 모아 `news/YYYY-MM-DD.md`에 정리. 항목마다 현실 적용 아이디어 5가지 이상을 함께 적는다
2. **주제 선정** — 오늘 직접 만들어볼 만한 것 하나를 고름
3. **제작·테스트** — `days/YYYY-MM-DD-<slug>/`에 만들고 실제로 실행해 동작 확인
4. **README 작성** — `_template/README.md`의 7개 섹션을 채움
5. **main 푸시** — 루트 README의 결과물 목록을 갱신하고 `main`에 바로 푸시

이 절차는 저장소 안의 스킬 **`/daily-lab`**(`.claude/skills/daily-lab/SKILL.md`)에 담겨 있어 어디서 불러도 같은 순서로 돈다.

| 어디서 | 어떻게 | 맥북이 꺼져 있어도 |
|---|---|---|
| 로컬 터미널 | 이 저장소에서 `claude` 실행 후 `/daily-lab` | ✗ |
| **Routine** (claude.ai/code/routines) | 저장소 `Gooreum/claude-daily-lab`, 프롬프트 `/daily-lab`, 매일 06:45, 환경 네트워크 **Full**. `/schedule`로 터미널에서도 만든다 | ✓ (구독 사용량) |
| GitHub Actions | `.github/workflows/daily-lab.yml`이 21:45 UTC(06:45 KST)에 실행. 시크릿 `CLAUDE_CODE_OAUTH_TOKEN`(`claude setup-token`으로 발급) 하나만 있으면 된다. 없으면 조용히 건너뛴다 | ✓ |

수집만 하려면 `/daily-lab --no-build`, 오늘 폴더가 있어도 다시 돌리려면 `/daily-lab --force`.

## 폴더 구조

```
claude-daily-lab/
├── README.md                 # 이 파일. 프로젝트 소개와 결과물 목록
├── RULES.md                  # 예약 작업이 매일 읽고 따르는 운영 규칙
├── _template/README.md       # 날짜별 프로젝트 README 템플릿
├── .claude/skills/daily-lab/ # 하루 루틴 스킬 (/daily-lab)
├── news/                     # 날짜별 소식 수집 결과 (YYYY-MM-DD.md)
├── days/                     # 날짜별 프로젝트 (YYYY-MM-DD-<slug>/)
├── .github/workflows/ci.yml  # 변경된 프로젝트 폴더의 test.sh 실행
└── .github/workflows/daily-lab.yml  # 06:45 KST에 /daily-lab 실행 (시크릿 있을 때)
```

## 모노레포 운영 원칙

- 폴더 하나 = 완결된 프로젝트 하나. 의존성 파일은 그 폴더 안에만 둔다.
- 자기 폴더 밖의 파일을 참조하지 않는다. 공유 유틸 폴더를 만들지 않는다.
- 다른 날짜 폴더는 수정하거나 삭제하지 않는다.
- 루트에 의존성 파일을 만들지 않는다.
- 키와 비밀값은 절대 커밋하지 않는다.

전체 규칙은 [RULES.md](RULES.md)를 참고하세요.

## 결과물 목록

<!-- 최신 항목이 위로 오도록 이 줄 아래에 행을 추가 -->
| 날짜 | 이름 | 종류 | 계기가 된 소식 | 한 줄 설명 |
|------|------|------|----------------|------------|
| 2026-10-10 | [haiku-migrate-lint](days/2026-10-10-haiku-migrate-lint/) | CLI 스크립트 | [Haiku 5.5 마이그레이션 가이드: Haiku 4.5 코드가 400을 내는 경우](https://platform.claude.com/docs/en/models/haiku-5-5/migration-guide) | Haiku 4.5 → 5.5 전환 시 400을 내는 패턴(모델 ID·`budget_tokens`·temperature/top_p/top_k·prefill·`computer_20250124`·Bedrock 구조화 출력 등 10규칙)을 키 없이 정적으로 찾고, 모델 ID·도구 버전은 `--fix`로 치환하는 린터. 플랫폼(API/Bedrock/Vertex) 자동 감지. 테스트 38건, 공개 저장소 quickstarts·cookbooks 실측 e2e(구 Haiku ID 21·82곳 잔존) |
| 2026-10-10 | [disaster-guard](days/2026-10-10-disaster-guard/) | 훅 묶음 | [dev.to 10-09: 재난을 막는 Claude Code 훅 3개](https://dev.to/luijhy_michaelguerraflo/3-claude-code-hooks-that-prevent-disasters-with-code-178b) | 파괴적 git·SQL·`curl\|sh`·`rm -rf`·kubectl/terraform/prod DB 명령을 규칙 파일 18줄로 막는 PreToolUse 훅(`onFailure: block`, fail-closed) + 자동 포맷 PostToolUse 훅 + `npm run` 허용/`npm install` 묻기 권한 예시 + install.sh. 단위 60건, 실제 세션 e2e 3건 |
| 2026-10-10 | [agent-radar](days/2026-10-10-agent-radar/) | Claude Code 모드 | [Claude Code 2.1.293: `subagentStatusLine`에 `agentType`](https://code.claude.com/docs/en/changelog) | Agent 도구가 띄우는 서브에이전트를 종류별로 pane에 실시간 표시(경과·도구 호출·오류·토큰). `/radar`, `/radar last`(세션 간 기록), 30초 넘는 에이전트 종료 알림. 실제 Explore 스폰이 훅에 잡히는 것까지 e2e로 확인. plugin test 8건 |
| 2026-10-10 | [idea-grader](days/2026-10-10-idea-grader/) | CLI 스크립트 (eval) | [claude.dev 블로그 10-07: eval 설계와 힐클라이밍 자동화](https://claude.dev/blog/automating-eval-design-and-hillclimbing/) | news 파일의 "현실 적용" 목록을 RULES 1절 기준(5개 이상·어디에→무엇을→왜 이득·막연한 말·맥락·변주)으로 채점하고 고칠 줄을 뽑는 작은 eval. `--judge`는 Haiku 판정, `--compare`는 전·후 힐클라이밍 판정. 실제 수집 파일 평균 95~98로 규칙은 포화, 여유는 판정 쪽에 있음을 실측. 테스트 17건 |
| 2026-10-10 | [model-caps](days/2026-10-10-model-caps/) | CLI 스크립트 | [API 릴리스 노트 10-01~06: Models API `line`·`thinking.types.disabled`·`server_tools`](https://platform.claude.com/docs/en/release-notes/api) | `GET /v1/models` 응답을 모델별 컨텍스트·출력·thinking 허용·effort·web/code 도구 Markdown 표로. 스냅샷 간 추가·퇴역·능력 변경 diff와 `--latest haiku`. 키 없으면 예시 데이터 dry-run. 테스트 19건. 실호출은 키가 없어 미검증 |
| 2026-10-10 | [selection-lens](days/2026-10-10-selection-lens/) | Claude Code 모드 | [Claude Code 2.1.288: 모드용 `$.ui.selection()`](https://code.claude.com/docs/en/changelog) | 트랜스크립트에서 드래그한 텍스트를 `/lens`로 받아 세션 자격 증명 그대로 `$.model.complete(haiku)`에 번역·설명·요약을 묻고 pane에 최근 5건과 비용을 쌓는 모드. 선택 없으면 `/lens ko -- <text>`. plugin test 9건·e2e 4건(실호출) 포함 |
| 2026-10-10 | [cache-meter](days/2026-10-10-cache-meter/) | CLI 스크립트 | [API 릴리스 노트 10-07: Sonnet 5.5 캐시 읽기 반값](https://platform.claude.com/docs/en/release-notes/api) | 2만 토큰 시스템 프롬프트를 N회 호출하며 캐시 읽기·쓰기·비용을 ASCII로. 시각·난수를 앞에 넣든 뒤에 넣든 Claude Code에서는 똑같이 캐시가 깨지고 비용 2배라는 걸 실측. dry-run·테스트 14건·실제 결과 포함 |
| 2026-10-10 | [effort-race](days/2026-10-10-effort-race/) | CLI 스크립트 | [Claude Code 2.1.292: Agent `effort` 파라미터](https://code.claude.com/docs/en/changelog) | 함정 문제 8개를 effort low~max 다섯 레인에 동시에 던져 정답률·시간·생각 토큰·비용을 ASCII 막대그래프로. Haiku 5.5 40회 57초. dry-run·테스트 12건·실제 결과 포함 |
| 2026-10-10 | [motion-lite](days/2026-10-10-motion-lite/) | CLI + 단일 HTML | [Claude Motion 베타](https://claude.com/resources/articles/dashboards-and-motion) | 한 줄 컨셉 → Haiku 5.5가 스토리보드 JSON → canvas가 재생하고 WebM으로 저장하는 단일 HTML. Motion의 동네 버전. dry-run·검증 테스트 14건·실제 생성물 스크린샷 포함 |
| 2026-10-10 | [haiku-mafia](days/2026-10-10-haiku-mafia/) | CLI 스크립트 | [Claude Haiku 5.5 출시](https://www.anthropic.com/claude-haiku-5-5) | Haiku 5.5 다섯 명이 서로 속이는 마피아 게임. 플레이어 한 발언 = `claude -p` 구조화 출력 한 번, 한 판 44초·$0.03. dry-run 대본 봇·엔진 테스트 14건·실제 판 기록 포함 |
| 2026-10-10 | [claude-tamagotchi](days/2026-10-10-claude-tamagotchi/) | Claude Code 모드 | [Claude Code 2.1.295: 모드 pane·`$.ui.notify`·`$.store`](https://code.claude.com/docs/en/changelog) | pane에 사는 토큰 펫. 턴마다 쓴 토큰이 밥, 1분마다 배가 꺼지고, 도구 실패 3번에 앓고, 30초 넘는 턴엔 자랑하며 알림. 세션 사이에도 살아 있음. plugin test·tsc·실제 세션 e2e 포함 |
| 2026-10-10 | [feed-bookmark](days/2026-10-10-feed-bookmark/) | CLI 스크립트 | [Building effective agent automations](https://claude.dev/blog/building-effective-agent-automations/) | 소스별 북마크로 Atom/RSS를 증분 읽고, 실패한 소스는 "조용함"이 아니라 "읽기 불가"로 보고하는 피드 리더. 기본 소스는 Claude Code·SDK 릴리스, 공식 플러그인 커밋, dev.to, GeekNews, Product Hunt 등 피드 14개(범용 피드는 제목 필터), fixture 테스트·실제 피드 e2e 포함 |
| 2026-10-10 | [turn-notify-mod](days/2026-10-10-turn-notify-mod/) | Claude Code 모드 | [Claude Code 2.1.295: 모드용 `$.ui.notify`](https://code.claude.com/docs/en/changelog) | 턴마다 소요 시간·토큰을 답변 아래 표시하고 30초 넘는 턴은 네이티브 알림. `/turnstats` 누계, plugin test·실제 세션 e2e 포함 |
| 2026-10-10 | [onfailure-secret-guard](days/2026-10-10-onfailure-secret-guard/) | Claude Code 훅 | [Claude Code 2.1.295: 훅 `onFailure: "block"`](https://code.claude.com/docs/en/changelog) | 비밀값 패턴을 막는 PreToolUse 훅. 훅이 죽어도 통과시키지 않는 fail-closed 설정과 실제 세션 e2e 포함 |

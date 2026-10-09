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

## 폴더 구조

```
claude-daily-lab/
├── README.md                 # 이 파일. 프로젝트 소개와 결과물 목록
├── RULES.md                  # 예약 작업이 매일 읽고 따르는 운영 규칙
├── _template/README.md       # 날짜별 프로젝트 README 템플릿
├── news/                     # 날짜별 소식 수집 결과 (YYYY-MM-DD.md)
├── days/                     # 날짜별 프로젝트 (YYYY-MM-DD-<slug>/)
└── .github/workflows/ci.yml  # 변경된 프로젝트 폴더의 test.sh 실행
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
| 2026-10-10 | [effort-race](days/2026-10-10-effort-race/) | CLI 스크립트 | [Claude Code 2.1.292: Agent `effort` 파라미터](https://code.claude.com/docs/en/changelog) | 함정 문제 8개를 effort low~max 다섯 레인에 동시에 던져 정답률·시간·생각 토큰·비용을 ASCII 막대그래프로. Haiku 5.5 40회 57초. dry-run·테스트 12건·실제 결과 포함 |
| 2026-10-10 | [motion-lite](days/2026-10-10-motion-lite/) | CLI + 단일 HTML | [Claude Motion 베타](https://claude.com/resources/articles/dashboards-and-motion) | 한 줄 컨셉 → Haiku 5.5가 스토리보드 JSON → canvas가 재생하고 WebM으로 저장하는 단일 HTML. Motion의 동네 버전. dry-run·검증 테스트 14건·실제 생성물 스크린샷 포함 |
| 2026-10-10 | [haiku-mafia](days/2026-10-10-haiku-mafia/) | CLI 스크립트 | [Claude Haiku 5.5 출시](https://www.anthropic.com/claude-haiku-5-5) | Haiku 5.5 다섯 명이 서로 속이는 마피아 게임. 플레이어 한 발언 = `claude -p` 구조화 출력 한 번, 한 판 44초·$0.03. dry-run 대본 봇·엔진 테스트 14건·실제 판 기록 포함 |
| 2026-10-10 | [claude-tamagotchi](days/2026-10-10-claude-tamagotchi/) | Claude Code 모드 | [Claude Code 2.1.295: 모드 pane·`$.ui.notify`·`$.store`](https://code.claude.com/docs/en/changelog) | pane에 사는 토큰 펫. 턴마다 쓴 토큰이 밥, 1분마다 배가 꺼지고, 도구 실패 3번에 앓고, 30초 넘는 턴엔 자랑하며 알림. 세션 사이에도 살아 있음. plugin test·tsc·실제 세션 e2e 포함 |
| 2026-10-10 | [feed-bookmark](days/2026-10-10-feed-bookmark/) | CLI 스크립트 | [Building effective agent automations](https://claude.dev/blog/building-effective-agent-automations/) | 소스별 북마크로 Atom/RSS를 증분 읽고, 실패한 소스는 "조용함"이 아니라 "읽기 불가"로 보고하는 피드 리더. 기본 소스는 Claude Code·SDK GitHub 릴리스 4개, fixture 테스트·실제 피드 e2e 포함 |
| 2026-10-10 | [turn-notify-mod](days/2026-10-10-turn-notify-mod/) | Claude Code 모드 | [Claude Code 2.1.295: 모드용 `$.ui.notify`](https://code.claude.com/docs/en/changelog) | 턴마다 소요 시간·토큰을 답변 아래 표시하고 30초 넘는 턴은 네이티브 알림. `/turnstats` 누계, plugin test·실제 세션 e2e 포함 |
| 2026-10-10 | [onfailure-secret-guard](days/2026-10-10-onfailure-secret-guard/) | Claude Code 훅 | [Claude Code 2.1.295: 훅 `onFailure: "block"`](https://code.claude.com/docs/en/changelog) | 비밀값 패턴을 막는 PreToolUse 훅. 훅이 죽어도 통과시키지 않는 fail-closed 설정과 실제 세션 e2e 포함 |

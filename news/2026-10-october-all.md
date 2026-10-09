# 2026년 10월 Claude 소식 수집 (10-01 ~ 10-10)

수집 범위: 2026-10-01 00:00 ~ 10-10 07:00 KST. 피드 9개는 feed-bookmark(`--max-age-hours 400`)로, 피드가 없는 페이지는 직접 읽었다. [2026-10-10.md](2026-10-10.md)에 이미 정리한 6건(Usage Policy, Cyber Mission·과학 지원, Dashboards·Motion, Building effective agent automations, 2.1.294, 2.1.295)은 여기서 다시 쓰지 않는다.

## 소스 점검

| 소스 | 상태 | 10월 항목 |
|------|------|-----------|
| anthropic.com/news | 읽힘 | 7 |
| claude.com/blog | 읽힘 | 11 |
| anthropic.com/engineering | 읽힘, 10월 글 없음 (최신 4월 23일) | 0 |
| claude.dev/blog | 읽힘 | 3 |
| platform.claude.com API 릴리스 노트 | 읽힘 (docs.claude.com에서 301) | 6일분 |
| support.claude.com 릴리스 노트 | 읽힘 | 2 |
| code.claude.com changelog | 읽힘 | 2.1.287~2.1.296 |
| GitHub 피드 9개 | 전부 읽힘 (조용함 1: cookbooks) | 48 |

## 1. Claude Haiku 5.5 출시
- 날짜: 2026-10-07
- 출처: https://www.anthropic.com/claude-haiku-5-5 , https://platform.claude.com/docs/en/release-notes/api , https://simonwillison.net/2026/Oct/7/claude-haiku-5-5/
- 요약: 가장 빠르고 싼 소형 모델. 1M 컨텍스트, 128K 출력, 적응형 사고가 기본이고 10만 토큰 이하 프롬프트 기준 입력 $0.10/출력 $0.50 per MTok, 그 이상은 5배다. Simon Willison의 실측으로는 effort low가 7초·0.09센트, max가 5분 9초·3.4센트였고, 새 토크나이저가 Haiku 4.5보다 토큰을 약 1.25배 쓰는 점을 "숨은 가격 인상"으로 지적했다. Claude Code 2.1.293부터 기본 Haiku다.
- 현실 적용:
  - 고객 지원 1차 분류 → 티켓 태깅·라우팅을 Haiku 5.5로 → 건당 0.1센트 미만이라 전량 처리 가능
  - 대량 문서 파이프라인 → 10만 토큰 넘는 입력은 청크로 나눠 넣기 → 5배 가격 구간을 피한다
  - 서브에이전트 → 조사·요약 같은 자식 작업을 Haiku 5.5 + effort low로 → 부모는 비싼 모델, 자식은 싼 모델
  - 이 저장소 → e2e와 실험 플레이어를 전부 Haiku 5.5로 (오늘의 haiku-mafia, effort-race, motion-lite) → 하루 실험 비용이 수 센트
  - Haiku 4.5 사용 서비스 → 토큰 수 1.25배를 감안해 비용을 다시 계산하고 `count_tokens`로 재측정 → 단가만 보고 교체하면 예산이 틀린다
  - 장시간 작업 → max effort는 5분까지 걸릴 수 있으니 타임아웃·스트리밍 설정 → 동기 호출이 끊기지 않게

## 2. Claude Frontier Academy — 엔지니어 1만 명 양성에 1억 달러
- 날짜: 2026-10-02
- 출처: https://www.anthropic.com/news/claude-frontier-academy
- 요약: 기업 안에서 Claude 기반 시스템을 설계·배포하는 "Frontier Deployed Engineer"를 키우는 프로그램에 1억 달러를 투자한다. 조직이 추천한 현업 엔지니어가 대상이고 첫 기수는 Accenture, Bain, Deloitte, McKinsey 등에서 샌프란시스코·뉴욕·런던에서 시작한다. 2027년 말까지 1만 명, 첫 자격증은 2027년 초가 목표다.
- 현실 적용:
  - 컨설팅·SI 회사 → 사내 Claude 도입 리드를 이 프로그램에 추천 → 외부 인증이 영업 자료가 된다
  - 개발팀 리더 → 커리큘럼 공개 여부를 추적해 사내 교육 과정의 뼈대로 → 처음부터 만들지 않는다
  - 이직 준비 개발자 → "Frontier Deployed Engineer"라는 직무명이 생겼으니 채용 공고 키워드로 모니터링 → 새 직군의 초기 수요 포착
  - 이 저장소 → 매일 실험물이 곧 포트폴리오. README 7섹션 형식을 자격 과정의 과제 형식과 비교해 보강 → 기록 방식 개선
  - 대학·부트캠프 → Anthropic Academy(anthropic.skilljar.com) 무료 강좌를 선수 과정으로 묶기 → 유료 프로그램 전 단계 제공

## 3. Barclays, Claude를 은행 전반으로 확대
- 날짜: 2026-10-01
- 출처: https://www.anthropic.com/news/barclays-scales-claude
- 요약: Barclays가 소프트웨어 개발, 레거시 현대화, 운영 효율에 Claude를 확대 적용한다. 2026년 말 개발자 50%, 2027년 다수가 Claude Code를 쓰는 것이 목표다. 영국 직원 1만 6천 명이 100만 회 넘게 쓴 RAG 기반 사내 지식 비서와, Global Markets에서 하루 약 12만 건의 고객 이메일을 분류·라우팅하는 모델이 구체적 사례다.
- 현실 적용:
  - 금융·규제 산업 IT → "강한 거버넌스와 사람의 감독" 아래 도입한 선례로 보안 심의 자료에 인용 → 승인 논의가 빨라진다
  - 레거시 코드 보유 팀 → COBOL·구형 Java 현대화 PoC를 Claude Code로 한 모듈만 먼저 → 성과를 수치로 만든 뒤 확대
  - 고객 이메일 많은 팀 → 분류·라우팅부터 자동화 → 답변 생성보다 리스크가 낮고 효과가 즉시 보인다
  - 사내 지식 비서 → 검색 로그(100만 회)를 품질 eval 데이터로 → 7번 항목의 eval 설계와 연결
  - 개발 조직 → "개발자 몇 %가 쓰는가"를 KPI로 두고 분기별 측정 → 도입이 선언에서 끝나지 않는다

## 4. Cyber Verification Program 확대 — 3단계 접근
- 날짜: 2026-10-06
- 출처: https://www.anthropic.com/news/cyber-verification-program
- 요약: 검증된 보안 전문가에게 사이버 안전장치 차단을 줄인 고급 모델을 주는 프로그램이 3단계로 늘었다. Defense Access는 사고 대응·악성코드 분석 같은 방어 업무용으로 비영리·대학·기반시설·오픈소스 유지보수자·일부 개인 연구자까지 열려 있다. Red Team Access는 조직 한정 인가된 침투 테스트, Specialized Access는 안전 핵심 시스템을 시험하는 소수 조직용이며 전원 데이터 보존과 보안 요건을 받아들여야 한다.
- 현실 적용:
  - 사내 보안팀 → Defense Access 신청으로 악성코드 분석·로그 트리아지에서 차단 없이 Claude 사용 → 분석 속도 향상
  - 오픈소스 유지보수자 → 개인 자격으로 Defense Access 신청 → 취약점 신고 검증을 혼자서도
  - 침투 테스트 회사 → Red Team Access 요건(조직·인가 증빙)을 영업 전 준비 → 계약 때 "AI 보조 가능" 명시
  - CTF 동아리·대학 → 교육 맥락은 Defense 범위인지 확인 후 신청 → 수업에서 거부 응답으로 막히는 일 감소
  - 컴플라이언스 → 데이터 보존 요건이 사내 정책과 충돌하는지 먼저 검토 → 신청 후 반려 방지

## 5. Block, Claude Fable로 수천 개 PR 오케스트레이션
- 날짜: 2026-10-08
- 출처: https://claude.com/resources/articles/how-block-orchestrates-claude-fable-across-thousands-of-pull-requests
- 요약: Block은 Fable 5를 오케스트레이터로 두고 설계를 맡긴 뒤 Opus·Sonnet 같은 더 작은 모델이 파일 수정과 테스트를 하게 한다. 한 마이그레이션에서 Fable이 지휘한 PR 약 1천 개가 머지됐고, 여러 저장소·수백만 줄 규모다. main 머지와 프로덕션 배포는 보안 검사와 두 명의 승인이 필요하며 Claude는 그 승인 단계를 우회하는 요청을 거부한다.
- 현실 적용:
  - 대규모 마이그레이션(프레임워크 업그레이드, 린트 규칙 전환) → 비싼 모델이 계획, 싼 모델이 실행하는 2층 구조 → 비용과 품질을 분리해 최적화
  - 모노레포 팀 → PR을 저장소·패키지 단위로 쪼개 병렬 생성 → 리뷰어가 한 번에 감당할 크기로
  - 배포 파이프라인 → "AI가 만든 PR도 사람 2명 승인"을 브랜치 보호 규칙으로 강제 → 모델이 아니라 설정이 지킨다
  - 이 저장소 → 하루 결과물 네 개를 동시에 만든 오늘의 방식과 비교 → 계획자/실행자 분리는 effort-race의 effort 분배와 같은 문제
  - 모델 평가 → 새 모델이 나오면 과거 마이그레이션 일부를 재실행해 비교하는 Block의 습관 → 12번 Cresta와 같은 원칙

## 6. eval 설계와 힐클라이밍 자동화
- 날짜: 2026-10-07
- 출처: https://claude.dev/blog/automating-eval-design-and-hillclimbing/
- 요약: 좋은 eval은 실제 작업을 닮고, 사람이 근거를 댈 수 있는 어려운 사례를 쓰며, 100% 아래 여유가 있어 변화가 보이고, 실행 간 분산이 낮다. 힐클라이밍은 train/test를 나눠 train만 오르는 변경은 되돌린다. claude-api 스킬의 `/claude-api build-eval`이 인터뷰로 입력과 채점기를 만들어 기준선을 돌리고, `/claude-api hillclimb`이 한 라운드에 변경 하나씩 제안해 둘 다 오르는 것만 남긴다.
- 현실 적용:
  - 고객 지원 봇 → 실제 대화 50건으로 `build-eval` → 프롬프트 수정마다 점수로 배포 결정
  - 분류 파이프라인 → train/test 분리로 과적합 없이 프롬프트 최적화 → 예시 몇 개 바꾸고 "좋아진 것 같다"에서 탈출
  - 이 저장소 → 수집 단계의 "현실 적용 아이디어" 품질을 채점하는 작은 eval → 루틴 프롬프트를 힐클라이밍
  - 모델 교체 → 같은 eval을 새 모델에 돌려 하루 안에 교체 가능 여부 판단 → 1번 Haiku 5.5 전환에 바로 적용
  - 비용 최적화 → "품질 동등 조건의 비용"을 목표로 effort·모델을 내리는 실험 → effort-race의 다음 단계
  - 채점기 설계 → 같은 모델이 자기 답을 후하게 주는 편향을 피하는 채점 → 다마고치의 "판정자 분리"와 같은 문제

## 7. Comcast·Booz Allen, Claude Mythos로 코드베이스 보안 점검
- 날짜: 2026-10-06
- 출처: https://claude.com/resources/articles/how-comcast-booz-allen-use-claude-mythos-to-secure-their-codebases
- 요약: 두 회사가 Project Glasswing으로 Mythos Preview를 써서 기존 스캐너가 놓친 결함을 찾았다. Comcast는 258개 시스템·약 1억 7천만 줄을 점검하다 공개 플랫폼의 치명적 인증 우회를 발견해 악용 전에 고쳤다. Booz Allen은 분석가 한 명이 12일 동안 138개 저장소·8개 운영 시스템을 훑어 부팅 시 보호되지 않은 보안 키 결함을 찾았는데, 큰 팀이 몇 달 걸릴 일로 추산했다.
- 현실 적용:
  - 보안팀 → 정적 분석 도구 결과와 모델 리뷰를 병행해 "스캐너가 못 잡는 논리 결함" 전용 트랙 → 인증·권한 로직에 집중
  - 작은 보안 조직 → 분석가 1명 + 모델로 저장소 수십 개 주기 점검 → 외주 감사 사이의 공백을 메운다
  - 하드웨어·펌웨어 팀 → 부팅 체인의 키 보호 같은 저수준 결함도 코드 리뷰 범위에 → 소프트웨어 취약점만 보던 관행 확장
  - 4번 CVP와 연결 → Mythos급 접근은 검증 프로그램이 필요하니 신청부터 → 일반 플랜에서는 Opus 5.5로 같은 방법론 시험
  - 이 저장소 → 자기 코드(오늘의 CLI들)를 모델에게 보안 리뷰시키는 하루 실험 → "스캐너 없는 1인 프로젝트"의 최소 보안

## 8. Claude가 Google Docs·Sheets·Slides 안으로
- 날짜: 2026-10-06
- 출처: https://claude.com/resources/articles/claude-now-works-in-google-docs-sheets-and-slides
- 요약: Google Workspace 애드온(공개 베타)이 Docs·Sheets·Slides 사이드바에 Claude를 넣어 열려 있는 파일과 선택 영역을 읽고 제자리에서 고친다. "편집 전 묻기" 모드로 변경마다 승인할 수 있다. 베타 커넥터는 반대로 Claude 대화에서 파일을 만들고 옆 pane에 열어 편집하며, 권한은 기존 Google 공유 설정을 따른다. 애드온은 유료 플랜 전체, 커넥터는 Team·Enterprise에서 소유자가 먼저 켜야 한다.
- 현실 적용:
  - 기획팀 → 요구사항 문서 옆 사이드바에서 요약·누락 점검 → 복붙 없이 문서 안에서
  - 재무·운영 → Sheets에서 수식 설명과 이상치 점검을 "편집 전 묻기"로 → 숫자가 조용히 바뀌는 사고 방지
  - 발표 준비 → Slides 슬라이드별 발표 노트 생성 → 데크는 그대로, 노트만 추가
  - Workspace 관리자 → Admin console로 특정 그룹에만 먼저 배포 → 파일럿 후 전사 확대
  - 이 저장소 → 매일 README를 Google Docs로 내보내 팀과 공유하는 변형 → 코드 저장소 밖 독자에게도 전달
  - 보안 검토 → 커넥터가 기존 공유 권한을 따르는지 실제로 확인(공유 안 된 파일 접근 시도) → 베타 기능의 권한 경계 검증

## 9. Claude Startups 프로그램 확대
- 날짜: 2026-10-06
- 출처: https://claude.com/resources/articles/were-expanding-the-claude-startups-program-to-help-founders-build
- 요약: 창업자에게 최대 7천 달러 상당의 Claude 제품·크레딧(Claude Team 1년, 프리미엄 5석, API 크레딧 1천 달러)과 최대 4만 5천 달러 상당의 도구 할인, Applied AI 팀 접근, Claude Marketplace 등록 지원을 준다. 5년 안에 창업했거나 2년 안에 투자받은 스타트업이 대상이고, 이번에 더 많은 창업자를 받으며 "Claude Startup Stack" 할인 묶음이 추가됐다.
- 현실 적용:
  - 초기 스타트업 → 신청 요건(창업 5년·투자 2년)을 확인하고 바로 신청 → API 크레딧 1천 달러면 실험 몇 달치
  - 사이드 프로젝트 → 법인이 있으면 Team 1년 무료로 팀 기능(프로젝트·공유) 시험 → 개인 플랜 한계 탈출
  - Marketplace 등록을 원하는 팀 → 등록 지원 트랙을 통해 배포 채널 확보 → 모드·플러그인 제품화 경로
  - 액셀러레이터·VC → 포트폴리오사에 일괄 안내 → 크레딧은 투자금보다 빠르게 쓸 수 있는 자원
  - 이 저장소 → 실험물 중 하나를 제품화할 때 이 프로그램을 첫 자금으로 → 어떤 결과물이 후보인지 README 6절에 메모

## 10. Claude Code 클라우드 세션 가이드
- 날짜: 2026-10-06
- 출처: https://claude.dev/blog/claude-code-in-the-cloud/
- 요약: 클라우드 세션은 격리된 VM에 저장소를 자기 브랜치로 클론해 돌아가므로 노트북을 닫아도 계속된다. 백로그 병렬 처리, 불안정한 테스트 반복 실행, 로컬에서 계획하고 `claude --cloud`·`--teleport`로 실행, 휴대폰 확인, PR의 CI 실패·리뷰 자동 수정, 예약 루틴, 신뢰할 수 없는 코드 실행에 맞다. GitHub 앱 설치와 커밋 푸시가 선행돼야 하고, `~/.claude` 사용자 설정은 따라가지 않으며, 유휴 VM은 회수될 수 있고, Zero Data Retention·API 키·서드파티 접근에서는 쓸 수 없다.
- 현실 적용:
  - 야간 마이그레이션 → 클라우드 세션에 맡기고 아침에 `claude attach`로 확인 → 노트북 상시 가동 불필요
  - 불안정한 테스트 → "100번 돌려 실패 조건 찾기"를 클라우드에 → 로컬 CPU를 안 쓴다
  - 이 저장소 → 06:45 루틴이 클라우드 세션이므로 "사용자 설정이 안 따라간다"를 전제로 `CLAUDE.md`·`.claude/`에 모든 규칙 두기 → 오늘 CLAUDE.md 커밋이 바로 그 조치
  - 보안 검토가 필요한 외부 PR → 네트워크 제한 VM에서 먼저 실행 → 로컬 오염 방지
  - 플랜 관리자 → 병렬 세션이 사용량 한도를 빨리 소진하니 팀 가이드에 동시 세션 수 명시 → 월말 한도 초과 예방
  - 모바일 → 휴대폰에서 진행 확인·승인 → 긴 작업 중 자리 비움 가능

## 11. Claude Code 모드 입문 글과 2.1.287 (Mods, "You should know", 1M 기본)
- 날짜: 2026-10-01
- 출처: https://claude.dev/blog/getting-started-with-claude-code-mods/ , https://code.claude.com/docs/en/changelog
- 요약: 모드는 세션 안에서 도는 JS/TS 플러그인으로 이벤트 관찰, 도구 호출 수정·거부, 터미널·데스크톱 UI 그리기가 가능하다. 예시로 컨텍스트 예보 밴드(Token Weather), 위험한 Bash를 잡아 두는 Blast Radius, 턴의 편집을 되감는 Replay Theater가 소개됐고 `plugin.json` + `hooks/hooks.json` + `register(on)`으로 시작해 `--plugin-dir`로 시험한다. 같은 날 2.1.287이 모드를 정식화했고, 놓친 것을 짚어 주는 내장 모드 "You should know"(`/plugin enable cc-plugin-you-should-know@builtin`)와 Opus 4.7+·Fable의 1M 컨텍스트 기본(`CLAUDE_CODE_DISABLE_1M_CONTEXT=1`로 해제)이 들어갔다.
- 현실 적용:
  - 운영 환경 접근이 있는 팀 → Blast Radius처럼 위험 명령을 pane에서 승인받는 모드 → 설정 훅보다 UI가 있어 승인 이유를 보여 줄 수 있다
  - 비용 민감한 팀 → 컨텍스트 사용량을 프롬프트 위 밴드로 상시 표시 → 압축 시점을 사람이 예측
  - 리팩터링 세션 → "You should know"를 켜 영향 범위 누락을 사이드 에이전트가 지적 → 켜고 끄는 비용 기준은 측정 후 결정
  - 이 저장소 → 오늘 turn-notify·token-pet 두 모드가 이 글의 "시작하기" 절차 그대로 → 다음은 `$.ui.selection()`(14번) 결합
  - 1M 컨텍스트 → Bedrock·Vertex 사용자는 기본값이 바뀌었으니 비용 상한이 걱정되면 해제 플래그 설정 → 긴 세션 요금 급증 예방
  - 모드 공유 → 마켓플레이스 배포 절차를 익혀 팀 내 모드 저장소 운영 → 사내 표준 가드를 모드로 배포

## 12. Cresta, Agent SDK로 "에이전트를 만드는 에이전트" Conductor
- 날짜: 2026-10-05
- 출처: https://claude.com/resources/articles/how-cresta-turned-cx-expertise-into-an-agent-builder-on-the-claude-agent-sdk
- 요약: Cresta가 고객 경험(CX) 에이전트를 자연어로 설계·구현·테스트·개선하는 메타 에이전트 Conductor를 만들었다. Claude Agent SDK를 범용 실행 하네스로 쓰고 그 위에 CX 워크플로·도구·도메인 지식을 얹었다. 초기 사용에서 배포 준비 시간이 절반으로 줄었고, 새 Claude 모델이나 프레임워크 업데이트가 나올 때마다 빌드 과제 eval을 다시 돌린다.
- 현실 적용:
  - 노코드 자동화 제품 → "설정 화면" 대신 자연어로 워크플로를 짜 주는 메타 에이전트 → 온보딩 시간 단축
  - 사내 플랫폼팀 → Agent SDK를 공통 하네스로 두고 팀별 도구만 얹는 구조 → 팀마다 루프를 다시 만들지 않는다
  - 모델 업데이트 대응 → 새 모델마다 자동 재평가 파이프라인(6번) → 교체 결정이 하루
  - 이 저장소 → haiku-mafia 같은 "에이전트가 에이전트를 돌리는" 구조를 Agent SDK로 다시 쓰는 변형 → CLI 호출과 SDK의 차이 기록
  - CX 팀 → 상담 스크립트를 에이전트로 바꿀 때 기존 전문가 지식(도메인 컨텍스트)을 먼저 문서화 → SDK보다 지식이 병목

## 13. Managed Agents 동적 워크플로 (베타)
- 날짜: 2026-10-09
- 출처: https://platform.claude.com/docs/en/release-notes/api , https://github.com/anthropics/skills/commit/dbd4588f9e1033efb41dad4bef2f7947c8993d44
- 요약: Managed Agents 에이전트가 여러 에이전트를 단계별로 돌리는 프로그램을 직접 쓰고 서버가 백그라운드로 실행한다. 한 세션의 자식 스레드 25개 한계를 넘는 큰 작업(수백 개 문서, 항목마다 같은 단계)을 위한 기능이며 Python SDK 1.13.0·TS 0.133.0에 workflows·multiagent 설정이 같이 들어갔다. claude-api 스킬도 10-10 커밋에서 워크플로 퀵스타트 4종을 추가했다. Claude Code의 Workflow 도구와는 별개다.
- 현실 적용:
  - 데이터팀 → 수백 개 테이블 스키마 문서화를 "테이블별 조사 → 중복 제거 → 정리" 단계로 → 배치를 사람이 나누지 않는다
  - 보안팀 → 저장소 수십 개 취약점 조사 팬아웃 → 7번 사례를 자동화 규모로
  - 고객 지원 → 티켓 1천 건 분류 → 묶음별 초안 → 검수 → 한 에이전트가 컨텍스트를 채우는 문제 회피
  - 컨텐츠팀 → 글 하나를 5개 언어로 번역하고 언어별 검수자 병렬 → 번역 품질 검수가 동시에
  - 이 저장소 → 소식 N건의 요약·적용처 작성을 워크플로로 → 소식 많은 날도 수집 시간이 일정. 단, 유료·API 키 필요라 dry-run 설계까지만
  - 시스템 프롬프트 설계 → "어떤 작업에 워크플로를 쓸지"를 조건부로만 적기 → 항상 켜면 토큰 낭비

## 14. Sonnet 5.5 캐시 읽기 반값, Max·Team 월간 API 크레딧
- 날짜: 2026-10-07
- 출처: https://platform.claude.com/docs/en/release-notes/api , https://support.claude.com/en/articles/12138966-release-notes
- 요약: Sonnet 5.5의 프롬프트 캐시 읽기가 $0.20에서 $0.10/MTok로 내렸고 쓰기와 다른 가격은 그대로다. 같은 날 Max·Team 구독자에게 매달 API 크레딧이 생겼고, 결제 설정에서 Console 조직을 연결하면 받는다.
- 현실 적용:
  - 긴 시스템 프롬프트 서비스 → 같은 접두사를 반복 호출하며 `cache_read_input_tokens` 비율을 재는 측정기 → 절감액을 숫자로 (다음 주제 1순위)
  - 프롬프트 점검 → 시스템 프롬프트의 날짜·세션 ID 같은 "조용한 캐시 무효화" 탐지 → 반값 혜택을 실제로 받는지 확인
  - 모델 선택 → 캐시는 모델별로 분리되니 "싼 모델로 바꾸면 캐시를 잃는다"를 계산기로 → 교체 결정에 근거
  - Max·Team 개인 사용자 → Console 조직을 연결해 크레딧 수령 → 이 저장소처럼 키 없이 CLI만 쓰던 실험을 SDK로 확장 가능
  - 비용 리포트 → 모델별 캐시 적중률을 주간 지표로 → 캐시 전략 변경 효과 추적

## 15. Haiku 4.5 → 5.5 호환성 깨짐 목록과 SDK 브라우저·컴퓨터 도구 클래스
- 날짜: 2026-10-07 (SDK: Python 1.12.0, TypeScript sdk-v0.132.0, 10-08)
- 출처: https://platform.claude.com/docs/en/release-notes/api , https://github.com/anthropics/anthropic-sdk-python/releases , https://github.com/anthropics/anthropic-sdk-typescript/releases
- 요약: Haiku 4.5용 코드가 5.5에서 400을 내는 경우가 명시됐다. 수동 확장 사고(`budget_tokens`), `temperature`·`top_p`·`top_k`, 어시스턴트 prefill, `computer_20250124`, system·tools·이전 턴 편집, Bedrock의 구조화 출력. 같은 주 SDK(Python 1.12.0, TS 0.132.0)에 `claude-haiku-5-5`와 브라우저·컴퓨터 사용 툴셋의 타입이 들어갔고, 도구 루프와 승인 콜백을 SDK가 돌려 주는 베타 클래스가 추가됐다. Python 1.12.0은 쿼리 파라미터·멀티파트의 빈 문자열 전송이 바뀐 breaking change도 있다.
- 현실 적용:
  - Haiku 4.5 사용 서비스 → 위 여섯 항목을 grep으로 찾아 고친 뒤 교체 → 배포 후 400 폭주 방지. claude-api 스킬 `migrate`가 이 체크리스트를 자동화
  - QA팀 → 회귀 시나리오를 자연어로 쓰고 SDK 브라우저 도구 루프로 실행 → Playwright 스크립트 유지비 절감
  - 운영팀 → 관리자 콘솔 반복 클릭(월간 리포트 내려받기)을 승인 콜백과 함께 자동화 → 위험한 클릭만 사람이 승인
  - 데이터 수집 → 피드가 없는 사이트를 브라우저 도구로 읽어 구조화 → feed-bookmark의 빈칸(anthropic.com/news)을 메운다
  - SDK 업그레이드 → Python 1.12.0의 빈 문자열 전송 변경을 테스트에서 확인 → 조용한 요청 변화로 인한 장애 예방
  - 이 저장소 → 키가 없어 SDK 클래스는 못 돌리지만 같은 일을 Claude in Chrome 도구로 재현해 비교 → "SDK vs 브라우저 확장" 기록

## 16. Managed Agents 네트워킹 제한 강화
- 날짜: 2026-10-07
- 출처: https://platform.claude.com/docs/en/release-notes/api
- 요약: `limited` 네트워킹에서 `allowed_hosts`가 `web_search`·`web_fetch`에도 적용돼 목록 밖 호스트는 오류를 내거나 결과에서 빠진다. 웹 도구의 `allowed_domains`에 `allowed_hosts` 밖 항목이 있으면 세션 생성·수정이 400으로 실패한다. `web_fetch`는 세션에 이미 나온 URL만 가져오고 아니면 `url_not_in_prior_context` 오류다.
- 현실 적용:
  - 사내 데이터만 다루는 에이전트 → `limited` + 빈 `allowed_hosts`로 웹 접근을 완전히 차단 → 프롬프트 인젝션으로 외부에 데이터가 새는 경로 제거
  - 리서치 에이전트 → 허용 도메인 목록을 `allowed_hosts`와 일치시키는 검증 스크립트 → 세션 생성 400을 배포 전에 잡는다
  - 요약 봇 → "검색 결과에 나온 URL만 fetch" 규칙이 기본이 됐으니 임의 URL 방문 기능을 기대하던 프롬프트 수정 → `url_not_in_prior_context` 오류 대응
  - 보안 검토 → 네트워크 정책이 도구 단위까지 내려왔으니 에이전트별 허용 목록을 코드 리뷰 대상에 → 설정이 곧 보안 경계
  - 이 저장소 → 10-10의 "Building effective agent automations" 읽기 전용 원칙의 구체 설정 예로 기록 → 다음 Managed Agents 실험의 기본값

## 17. Models API 능력 필드, Dreams 지원 모델, Compliance API
- 날짜: 2026-10-01 ~ 10-08
- 출처: https://platform.claude.com/docs/en/release-notes/api , https://github.com/anthropics/anthropic-sdk-python/releases
- 요약: Models API에 모델 계열을 묶는 `line`(10-01), `thinking: disabled` 허용 여부 `capabilities.thinking.types.disabled`(10-05), 웹 검색·코드 실행 지원 여부 `capabilities.server_tools`(10-06)가 생겼고 SDK에는 lifecycle stage 필드와 필터가 들어갔다. Dreams 연구 프리뷰가 Opus 5.5·Fable 5.1·Sonnet 5.5를 지원한다(10-01). Compliance API 채팅 엔드포인트가 통합 Claude 경험의 채팅도 반환한다(10-08, Enterprise 베타). Python 1.10.0은 Admin API에 Enterprise 분석·지출 한도·RBAC·플러그인 마켓플레이스를 추가했다.
- 현실 적용:
  - 플랫폼팀 → 모델 목록을 돌며 컨텍스트·출력·thinking disabled·server_tools 표를 자동 생성 → 문서가 아니라 API가 진실 (다음 주제 3순위)
  - 라우터 → `line`으로 "최신 haiku" 같은 선택을 코드로 → 모델 ID 하드코딩 제거
  - 마이그레이션 → 새 모델이 `thinking: disabled`를 거부하는지 미리 확인 → 15번 400 목록을 코드로 예방
  - 이 저장소 → 매일 수집 때 모델 목록 diff를 소식으로 → 발표보다 API 반영이 먼저일 때가 있다
  - Enterprise 관리자 → Admin API의 지출 한도·RBAC로 팀별 예산 자동 관리 → 월말 정산 대신 사전 제한
  - 컴플라이언스 → Compliance API로 통합 채팅까지 감사 로그 수집 → 제품이 늘어도 감사 범위 누락 없음

## 18. Claude Code 2.1.288 ~ 2.1.291
- 날짜: 2026-10-02 ~ 10-06
- 출처: https://code.claude.com/docs/en/changelog
- 요약: 2.1.288은 모드용 `$.ui.selection()`, 클라우드 세션 내장 `gh api`, Ctrl+C로 지운 프롬프트 복구. 2.1.289는 팀메이트용 `agent.spawn`과 플러그인 코드 pane의 큰 파일 속도 개선. 2.1.290은 `claude attach`·`claude logs`가 세션 이름 일부로 동작, Claude in Chrome을 프로젝트 설정 파일로 켤 수 없게 변경, WebSearch 예산이 200회 후 끝나지 않고 시간에 따라 충전. 2.1.291은 클라우드 세션 권한 응답 누락과 종료 시 마지막 메시지 유실 회귀를 고쳤다.
- 현실 적용:
  - 코드 리뷰어 → 트랜스크립트에서 드래그한 코드만 `$.ui.selection()`으로 받아 설명·테스트 생성하는 모드 → 긴 답변에서 필요한 줄만 (다음 주제 2순위)
  - 외국어 사용자 → 선택한 영어 답변을 한국어로 pane에 띄우는 모드 → 전체 번역 없이 부분만
  - 팀 리더 모드 → `agent.spawn`으로 팀메이트를 띄우고 역할 분담 → 멀티 에이전트 실험을 코드로
  - 클라우드 세션 운영 → `claude attach <이름 일부>`로 아침 점검 루틴 단축 → 세션 ID 복사 불필요
  - 보안 → 프로젝트 설정으로 Chrome 확장을 켤 수 없으니, 저장소를 클론만 해도 브라우저가 열리던 위험 제거 → 외부 저장소 작업 시 안심
  - 리서치 많은 세션 → WebSearch 예산이 충전식이 됐으니 긴 조사 세션 설계 변경 → 200회 제한 때문에 세션을 나누던 관행 폐기

## 19. Claude Code 2.1.292 · 2.1.293
- 날짜: 2026-10-06 ~ 10-07
- 출처: https://code.claude.com/docs/en/changelog
- 요약: 2.1.292는 `claude plugin install --marketplace <source>`, Agent 도구의 `effort` 파라미터, 로컬 MCP의 프로토콜 2026-07-28 기본 협상. 2.1.293은 Haiku 5.5를 기본 Haiku로, `subagentStatusLine`에 `agentType`, 2.1.281의 auto 모드 거부 메시지 변경 되돌림.
- 현실 적용:
  - 서브에이전트 설계 → 조사는 low, 구현은 high처럼 자식마다 effort 지정 → 오늘의 effort-race가 측정한 차이를 실제 분배에
  - 플러그인 배포 → 사내 마켓플레이스 소스를 `--marketplace`로 지정해 설치 명령 한 줄 → 온보딩 문서 단순화
  - MCP 서버 운영자 → 2026-07-28 프로토콜 기본값에 맞춰 서버 버전 확인 → 협상 실패로 조용히 빠지는 도구 방지
  - 상태 줄 모드 → `agentType`으로 어떤 종류의 서브에이전트가 도는지 표시 → 다마고치 pane에 "지금 탐색 중/구현 중" 추가
  - 비용 → 기본 Haiku가 5.5로 바뀌어 서브에이전트 비용 구조가 달라졌으니 1번의 토큰 1.25배와 함께 재계산 → 예산 갱신

## 20. Claude Code 2.1.296
- 날짜: 2026-10-09
- 출처: https://code.claude.com/docs/en/changelog
- 요약: Claude 앱 게이트웨이의 `managed.policies[]`에 `code` 키가 생겨 CLI와 같은 설정을 Claude Desktop의 Code 탭에도 적용한다. 서브에이전트 프런트매터와 `--agents` 정의에 `autoCompactWindow`가 생겨 자식이 부모보다 일찍 압축할 수 있다. `CLAUDE_CODE_WORKFLOW_SUBAGENT_MODEL`로 워크플로의 모든 에이전트를 한 모델로 돌린다.
- 현실 적용:
  - 관리자 → 게이트웨이 정책 한 곳에서 CLI와 Desktop Code 탭을 같이 통제 → 설정 불일치 제거
  - 긴 조사 서브에이전트 → `autoCompactWindow`를 짧게 줘 자식만 자주 압축 → 부모 대화는 그대로, 자식 비용만 절감
  - 워크플로 비용 통제 → `CLAUDE_CODE_WORKFLOW_SUBAGENT_MODEL=claude-haiku-5-5`로 실험 단계 비용 고정 → 품질이 확인되면 모델 올리기
  - 이 저장소 → 오늘 못 쓴 Workflow 도구 실험을 서브에이전트 모델 고정으로 저렴하게 → 다음 실험 후보
  - 대규모 팬아웃 → 자식마다 압축 창을 다르게 둬 긴 문서 읽기 자식만 작게 → 컨텍스트 폭주 예방

## 21. SDK 릴리스 모음 (Python 1.10.0~1.13.0, TypeScript 0.132.0~0.133.0, Agent SDK)
- 날짜: 2026-10-01 ~ 10-10
- 출처: https://github.com/anthropics/anthropic-sdk-python/releases , https://github.com/anthropics/anthropic-sdk-typescript/releases , https://github.com/anthropics/claude-agent-sdk-python/releases , https://github.com/anthropics/claude-agent-sdk-typescript/releases
- 요약: Python 1.10.0은 Admin API 확장(분석·지출 한도·RBAC·플러그인 마켓플레이스)과 Managed Agents idle 이벤트의 `refusal`·`stop_details`, 1.11.0은 지출 한도 목록과 Sonnet 4.5 deprecated, 1.12.0은 Haiku 5.5·툴셋 타입·모델 lifecycle 필드와 빈 문자열 전송 breaking change, 1.13.0은 워크플로·멀티에이전트·스레드 상태 필터와 Chat·Cowork 통합 분석 타입이다. TS 0.132.0은 같은 Haiku·툴셋 추가와 Text Completions API deprecated, 0.133.0은 워크플로·분석 타입이다. Agent SDK Python 0.2.163~165는 번들 CLI를 2.1.286→2.1.294로 올리고 CI 보안 강화(egress 방화벽, 네트워크 허용 목록)를 했다. TS Agent SDK는 Claude Code와 같은 번호로 10개가 나왔다.
- 현실 적용:
  - Sonnet 4.5 사용 서비스 → deprecated 표시가 떴으니 교체 일정 수립 → 종료 공지 전에 이동
  - Text Completions 사용 코드 → Messages API로 이전 → TS SDK에서 deprecated
  - Admin API 사용 조직 → 지출 한도 API로 팀별 예산 자동화 → 17번과 연결
  - 라이브러리 업데이트 봇 → Agent SDK의 "번들 CLI 버전"을 추적해 Claude Code 변경이 SDK에 반영되는 시차 기록 → 이번엔 2~3일
  - CI 운영자 → Agent SDK 저장소의 egress 방화벽·허용 목록 워크플로를 참고해 자기 CI의 Claude 호출을 격리 → 오픈소스 CI 보안 모범 사례
  - 이 저장소 → feed-bookmark가 이 릴리스들을 매일 잡으니 "SDK 변경 요약" 섹션을 수집 파일에 상시 두기 → 수동 확인 불필요

## 22. anthropics/skills와 claude-quickstarts 저장소 변경
- 날짜: 2026-10-01 ~ 10-10
- 출처: https://github.com/anthropics/skills/commits/main.atom , https://github.com/anthropics/claude-quickstarts/commits/main.atom
- 요약: claude-api 스킬이 10-05 Managed Agents 퀵스타트 온보딩(`managed-agents-onboard <이름>`), 10-09 Haiku 5.5를 현재 Haiku로, 10-10 동적 워크플로와 워크플로 퀵스타트 4종으로 세 번 갱신됐다. 퀵스타트 저장소는 NVIDIA OpenShell 자체 호스팅 샌드박스 데모(10-01), Daily brief 퀵스타트를 Sonnet 5.5로 전환(10-07), 현재 SDK·모델로 전체 재실행(10-07), computer·browser 툴셋(10-08)을 추가했다. Cookbook은 10월 커밋이 없다.
- 현실 적용:
  - Claude Code 사용자 → `claude update` 후 `/claude-api` 스킬 서브커맨드(migrate, build-eval, hillclimb, managed-agents-onboard)를 써 보기 → 문서 대신 대화형 절차
  - 자체 인프라 필요한 팀 → OpenShell 자체 호스팅 샌드박스 데모로 Managed Agents의 "실행은 우리 서버" 구성 검토 → 데이터 반출 우려 해소
  - 일일 요약 봇을 만들 팀 → Daily brief 퀵스타트를 출발점으로 → 10-10의 자동화 블로그와 같은 참조 구현
  - 이 저장소 → skills 저장소 커밋을 매일 읽어 "스킬이 바뀌면 어제 읽은 지식이 낡았다"를 알아채기 → 오늘 로드한 claude-api 스킬이 어제 갱신본이었다
  - 퀵스타트 유지 → "현재 SDK·모델로 재실행" 커밋처럼 예제를 주기적으로 다시 돌리는 CI → 낡은 예제가 첫인상을 망치지 않게

## 23. Simon Willison의 10월 Claude 글 2편 (Haiku 5.5 외)
- 날짜: 2026-10-05, 10-06
- 출처: https://simonwillison.net/2026/Oct/6/scrimshaw-jukebox/ , https://simonwillison.net/2026/Oct/5/felix-rieseberg/
- 요약: Scrimshaw Jukebox는 Opus 5.5에게 게임 음악용 텍스트 포맷을 설계시키고 브라우저 아티팩트로 재생하게 한 실험으로, 원숭이 섬 풍의 곡 여섯 개가 나왔고 "텍스트 모델의 작곡"이 새 능력인지 묻는다. Felix Rieseberg 인용 글은 Anthropic의 Cowork 신버전이 추론과 VM을 클라우드로 옮겨 세션마다 샌드박스를 주고 데스크톱 앱은 파일 접근만 맡는다는 내용으로, 로컬 VM의 디스크·배터리 부담을 없애고 휴대폰에서 이어 쓰게 한다.
- 현실 적용:
  - 게임·인디 개발자 → 모델이 설계한 단순 텍스트 음악 포맷으로 배경음 프로토타입 → 작곡가 섭외 전 분위기 확인
  - 이 저장소 → motion-lite에 "Haiku가 쓴 텍스트 악보"를 붙여 배경음 넣기 → 오늘 한계 목록의 "소리가 없다" 해결 후보
  - 능력 탐색 → "3D 그래픽처럼 작곡도 새 능력인가"를 모델별로 같은 프롬프트로 비교 → effort-race식 벤치
  - Cowork 사용자 → 노트북 자원 부담 때문에 껐다면 클라우드 전환 후 재시도 → 10번 클라우드 세션과 같은 흐름
  - 데스크톱 앱 설계 → "추론은 클라우드, 파일 접근은 로컬"의 분리를 자기 제품 아키텍처 참고로 → 보안 경계가 명확

## 다음 주제 선정 (2절 기준)

**1순위: 프롬프트 캐시 측정기 (14번)** — `claude -p --output-format json`의 `cache_read_input_tokens`·`cache_creation_input_tokens`·`total_cost_usd`로 같은 시스템 프롬프트를 N회 호출하며 캐시 적중률과 누적 비용 곡선을 ASCII로 그리는 CLI. 날짜·난수를 프롬프트에 섞어 캐시가 깨지는 "조용한 무효화"를 재현해 비교한다. 키 없이 돌아가고, Sonnet 5.5 캐시 반값이 계기이며, effort-race와 지표가 다르다.

**2순위: 선택 영역 모드 (18번)** — `$.ui.selection()`으로 트랜스크립트에서 선택한 텍스트를 받아 번역·설명을 pane에 띄우는 모드. 모드 API 학습 가치가 크고 token-pet과 결합 가능. selection API 문서를 먼저 읽어야 하고 `-p` e2e가 어렵다.

**3순위: 모델 능력표 생성기 (17번)** — Models API로 모델별 컨텍스트·출력·thinking·server_tools 표를 Markdown으로. API 키가 필요해 dry-run이 주가 된다.

보류: 13번(Managed Agents 전용·유료), 15번 SDK 도구 클래스(키 필요), 6번 eval 힐클라이밍(한 세션에 끝내기 어려움), 10번 클라우드 세션(측정·검증이 어려움).

# RULES.md — 운영 규칙

> **이 파일은 매일 실행되는 AI 작업의 지시문보다 우선한다. 방향을 바꾸려면 이 파일을 수정한다.**

## 0. 시작 조건

- 날짜는 **Asia/Seoul** 기준 `YYYY-MM-DD`로 정한다.
- `days/` 아래에 오늘 날짜로 시작하는 폴더(`days/YYYY-MM-DD-*`)가 이미 있으면 오늘 작업은 완료된 것이다. 아무것도 하지 않고 종료한다.

## 1. 수집

- 최근 **48시간**의 Claude/Anthropic 소식을 수집한다.
- 우선 출처:
  - https://www.anthropic.com/news
  - https://www.anthropic.com/engineering — 에이전트 설계·컨텍스트 관리 같은 개발자 글
  - https://claude.com/blog
  - https://claude.dev/blog — 자동화·에이전트 참조 구현 글
  - Claude Code 문서와 GitHub `anthropics/claude-code` 릴리스 (https://code.claude.com/docs/en/changelog)
  - platform.claude.com 릴리스 노트 모음: https://platform.claude.com/docs/en/release-notes/overview (API 릴리스 노트는 https://platform.claude.com/docs/en/release-notes/api. docs.claude.com 주소는 여기로 301 리다이렉트된다)
  - support.claude.com 릴리스 노트
  - GitHub 피드 (Atom, 증분 읽기 가능): `anthropics/anthropic-sdk-python`·`anthropic-sdk-typescript`·`claude-agent-sdk-python`·`claude-agent-sdk-typescript` 릴리스, `anthropics/claude-cookbooks` 커밋(https://github.com/anthropics/claude-cookbooks/commits/main.atom)
  - 신뢰할 만한 개발자 블로그: Simon Willison의 Claude 태그(https://simonwillison.net/tags/claude.atom) 등
  - anthropic.com·claude.com에는 RSS가 없다. Reddit·HN 같은 커뮤니티 피드는 봇 차단이 잦아 우선 출처로 쓰지 않는다.
- 서비스·사례 출처 (기술 변경보다 "누가 무엇을 만들었나"를 보는 곳. 매일 한 번 훑고 눈에 띄는 것만 항목으로 올린다):
  - https://claude.com/customers — 고객 사례. 카드에 날짜가 없으니 전날 제목과 비교해 새 것만 본다
  - https://claude.com/marketplace — 커넥터·플러그인·파트너 제품. "Trending now"(이번 주 급상승) 목록을 본다
  - https://github.com/anthropics/claude-plugins-official/commits/main.atom — 공식 플러그인 갱신. 어떤 회사가 Claude용 제품을 내는지 보인다
  - https://dev.to/feed/tag/claudecode — 개발자들의 실사용 글
  - https://news.hada.io/rss/news — GeekNews(한국어). 제목에 Claude·Anthropic이 있는 것만
  - https://www.producthunt.com/feed — 제품 런칭. 제목에 Claude가 있는 것만
  - https://www.latent.space/feed — AINews 요약·팟캐스트
  - Medium 태그 피드는 잡글이 많아 쓰지 않는다. X·Bluesky·Threads는 로그인 없이 읽히지 않는다.
- 결과를 `news/YYYY-MM-DD.md`에 항목별로 기록한다. 항목마다 **제목, 날짜, 출처 URL, 2~3문장 요약**을 쓴다.
- 항목마다 **현실 적용 아이디어를 5가지 이상** 적는다. 소식을 스크랩만 하고 끝내지 않고, "이걸 어디에 써먹을 수 있나"까지 쓴다.
  - 한 줄에 하나씩, `어디에(팀·제품·워크플로) → 무엇을 → 왜 이득` 순서로 쓴다.
  - "활용 가능", "도움이 될 것" 같은 막연한 말 금지. 오늘 당장 시작할 수 있는 구체적인 장면이어야 한다.
  - 개인 프로젝트, 회사 업무, 이 저장소의 루틴처럼 서로 다른 맥락을 섞는다. 같은 아이디어의 변주 다섯 개는 하나로 친다.
  - 주제 선정(2절)은 이 목록에서 고르는 것을 우선한다. 적용처가 떠오르지 않는 소식은 만들 가치도 낮다.
- 원문은 자기 말로 요약한다. 직접 인용은 **15단어 미만**, **출처당 1회 이하**로 제한한다.
- **읽기 실패는 "소식 없음"이 아니다.** news 파일 맨 위에 `## 소스 점검` 표를 두고 소스마다 `새 항목 N개 / 조용함 / 읽기 불가(이유)` 중 하나를 적는다. 읽기 불가에는 404, 타임아웃, 파싱 실패 같은 이유를 쓴다.
  - 모든 소스가 읽기 불가면 그 사실만 적은 news 파일을 남기고 2절의 "새 소식이 없을 때" 경로로 간다. 확인 못 한 날을 조용한 날로 기록하지 않는다.

## 2. 주제 선정

- 수집한 소식 중 "오늘 직접 만들어볼 만한 것" **하나**를 고른다.
- 새 기능, 새 API, Claude Code 신규 기능(스킬, 서브에이전트, 훅, MCP, 플러그인 등)을 우선한다.
- 루트 `README.md`의 결과물 목록과 겹치는 주제는 피한다.
- 새 소식이 없으면 아직 다루지 않은 기존 기능을 실험한다.

## 3. 제작

- 종류는 다음 중 하나: Claude Code 스킬(`SKILL.md`), 서브에이전트 정의, 훅, 작은 MCP 서버, CLI 스크립트, 단일 HTML 웹 도구.
- 한 세션 안에 끝낼 수 있는 **작고 완결된 크기**로 만든다.
- 위치: `days/YYYY-MM-DD-<짧은-영문-kebab-slug>/`
- 반드시 **실제로 실행하거나 테스트**해서 동작을 확인한다.
- API 키가 필요하면 키 없이 돌아가는 **dry-run 모드**를 함께 제공한다. 키와 비밀값은 절대 커밋하지 않는다.
- 테스트가 있으면 폴더 안에 `test.sh`를 두고, 그 폴더에서 `bash test.sh`로 실행되게 한다. CI가 변경된 폴더의 `test.sh`를 실행한다.
- **실패도 결과물이다.** 만들다 막히거나 테스트가 끝내 통과하지 않아도 폴더를 지우지 않는다. README 5절에 실패한 명령과 출력을 그대로, 6절에 원인과 시도한 것을 적고, 루트 README 표의 한 줄 설명 맨 앞에 `⚠ 미완`을 붙여 올린다. 조용히 지우고 "오늘은 없음"으로 끝내는 것을 금지한다.

## 4. 모노레포 격리 원칙

- 폴더 하나 = 완결된 프로젝트 하나. 의존성 파일(`package.json`, `requirements.txt` 등)은 그 폴더 안에만 둔다.
- 자기 폴더 밖의 파일을 import하거나 참조하지 않는다. 공유 유틸 폴더를 만들지 않는다. 필요하면 복사한다.
- 다른 날짜 폴더는 수정하거나 삭제하지 않는다.
- 루트에 의존성 파일을 만들지 않는다.
- 이 저장소 외의 저장소는 건드리지 않는다.

## 5. 프로젝트 README

- `_template/README.md`의 **7개 섹션을 모두** 채워 `days/YYYY-MM-DD-<slug>/README.md`로 둔다.
  1. 무엇을 만들었나
  2. 왜 만들었나
  3. 어떻게 만들었나
  4. 사용법
  5. 테스트 결과
  6. 한계와 다음 아이디어
  7. 출처

## 6. 인덱스 갱신과 반영

- 루트 `README.md`의 결과물 목록 표 **맨 위**에 오늘 행을 추가한다 (최신이 위). 표 위의 `<!-- 최신 항목이 위로 오도록 이 줄 아래에 행을 추가 -->` 주석 아래, 헤더 행과 구분선 바로 다음에 넣는다.
  - 열: `날짜 | 이름 | 종류 | 계기가 된 소식 | 한 줄 설명`
- **푸시 직전 재확인.** 커밋 전에 다음을 다시 본다. 하나라도 걸리면 고치고, 못 고치면 3절의 `⚠ 미완` 경로로 올린다.
  1. 프로젝트 폴더에서 `bash test.sh`를 다시 실행해 통과한다.
  2. README에 7개 섹션 제목(`## 1.` ~ `## 7.`)이 모두 있다.
  3. 루트 README 표 맨 위에 오늘 행이 들어가 있고 링크 경로가 실제 폴더와 같다.
  4. README 7절의 출처 URL이 응답한다(`curl -sI`로 2xx/3xx). 응답하지 않으면 그 옆에 `(확인 시점에 접속 불가)`라고 적는다.
  5. 커밋할 파일에 API 키·토큰·개인키 패턴(`sk-ant-`, `AKIA`, `ghp_`, `BEGIN .* PRIVATE KEY`)이 없다.
- 커밋 메시지: `day: YYYY-MM-DD <slug>`
- `main`에 바로 푸시한다. 거부되면 `git pull --rebase` 후 **한 번만** 재시도한다.

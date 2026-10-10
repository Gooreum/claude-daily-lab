---
name: daily-lab
description: claude-daily-lab의 하루 루틴을 끝까지 수행한다. 소식 수집 → news/YYYY-MM-DD.md → 주제 선정 → days/YYYY-MM-DD-<slug>/ 제작·테스트 → README 7섹션 → 루트 README 표 → main 푸시. 로컬, 클라우드 세션, Routine, GitHub Actions 어디서 불러도 같은 절차로 돈다.
when_to_use: "Trigger on /daily-lab, 오늘 루틴 돌려, daily lab 실행, or when a Routine or GitHub Actions run calls it at 06:45 KST"
argument-hint: "[YYYY-MM-DD] [--no-build] [--force]"
disable-model-invocation: true
allowed-tools: Bash(git *) Bash(bash *) Bash(python3 *) Bash(node *) Bash(curl *) Bash(ls *) Bash(cat *) Bash(date *) Bash(mkdir *) Bash(chmod *) Bash(grep *) Bash(find *) Bash(claude *) Read Write Edit Glob Grep WebFetch WebSearch
effort: high
---

# daily-lab 하루 루틴

이 스킬은 `RULES.md`를 실행 가능한 순서로 옮긴 것이다. **규칙의 원본은 RULES.md다.** 둘이 다르면 RULES.md를 따르고, 이 파일을 고친다.
사람이 지켜보지 않는 자리(Routine, GitHub Actions)에서 돌 수 있으니 **질문하지 말고 끝까지 간다.** 막히면 3절의 "실패도 결과물" 경로로 올린다.

인자: `$ARGUMENTS`
- 날짜(`YYYY-MM-DD`)가 있으면 그 날짜로 돈다. 없으면 아래 "오늘"을 쓴다.
- `--no-build`: 수집(1절)까지만 하고 커밋·푸시한다. 제작은 건너뛴다.
- `--force`: 오늘 폴더가 이미 있어도 수집부터 다시 한다(제작은 새 slug로).

## 지금 상태

!`bash .claude/skills/daily-lab/status.sh`

## 0. 시작 조건 (RULES 0절)

1. 저장소 루트로 이동한다. 브랜치가 `main`이 아니면 `git checkout main && git pull --ff-only`.
2. `days/<오늘>-*` 폴더가 **이미 있으면** 아무것도 만들지 않는다. "오늘(<날짜>) 작업은 이미 완료됨: <폴더>" 한 줄만 답하고 끝낸다. (`--force`가 있을 때만 예외)
3. git 사용자 이름·이메일이 비어 있으면(클라우드·CI) 커밋 전에 설정한다:
   `git config user.name "claude-daily-lab" && git config user.email "claude-daily-lab@users.noreply.github.com"`

## 1. 수집 (RULES 1절)

`news/<오늘>.md`를 만든다. 이미 있으면 "소스 점검" 표와 빠진 항목만 보강한다.

1. **소스 점검 표를 먼저 쓴다.** RULES 1절의 우선 출처와 서비스·사례 출처를 **전부** 순서대로 읽고, 소스마다 `새 항목 N개 / 조용함 / 읽기 불가(이유)` 한 줄을 표에 적는다. 읽는 방법:
   - HTML 페이지: `WebFetch`. 403·타임아웃이면 `curl -sL --max-time 20 <url> | head -c 20000`으로 한 번 더. 그래도 안 되면 `읽기 불가(사유)`.
   - Atom/RSS: `curl -sL <feed>`로 받아 `<entry>`/`<item>`의 제목·날짜·링크를 본다. 최근 48시간 것만.
   - 날짜가 없는 카드형 페이지(customers, marketplace)는 어제 news 파일의 제목과 비교해 새 것만.
2. **항목 쓰기.** 48시간 안의 소식마다 다음 형식을 **그대로** 쓴다. 생략 금지.
   ```
   ## N. 제목
   - 날짜: YYYY-MM-DD
   - 출처: URL
   - 요약: 자기 말로 2~3문장. 직접 인용은 15단어 미만, 출처당 1회 이하.
   - 현실 적용:
     - 어디에(팀·제품·워크플로) → 무엇을 → 왜 이득
     - … (5개 이상. 개인·회사·이 저장소 등 맥락을 섞는다. 같은 아이디어 변주 5개는 1개로 친다)
   ```
   "활용 가능", "도움이 될 것" 같은 막연한 말은 쓰지 않는다. 오늘 당장 시작할 수 있는 장면이어야 한다.
3. 자기 점검: `days/2026-10-10-idea-grader/`가 있으면 `python3 days/2026-10-10-idea-grader/idea_grader.py news/<오늘>.md`를 돌려 5개 미만·형식 위반·막연한 말로 걸린 줄을 고친다. (exit 1이면 고친 뒤 다시)
4. 모든 소스가 읽기 불가면 그 사실만 적은 news 파일을 남기고 2절의 "새 소식이 없을 때"로 간다.
5. `--no-build`면 여기서 6절(커밋·푸시)로 건너뛴다. 커밋 메시지는 `docs: <오늘> 소식 수집`.

## 2. 주제 선정 (RULES 2절)

- 오늘 항목의 "현실 적용" 목록에서 **하나**를 고른다. 우선순위: 새 기능·새 API·Claude Code 신규 기능(스킬·서브에이전트·훅·MCP·플러그인·모드) > 기존 기능 실험.
- 루트 `README.md` 결과물 목록과 겹치는 주제는 피한다. `news/*.md`의 "다음 주제 선정" 절에 남은 후보가 있으면 그것을 우선한다.
- 새 소식이 없으면 아직 다루지 않은 기존 기능을 실험한다.
- news 파일 끝에 `## 오늘의 선정` 절로 무엇을 왜 골랐는지 3줄 이내로 적는다.

## 3. 제작·테스트 (RULES 3·4절)

- 위치: `days/<오늘>-<짧은-영문-kebab-slug>/`. 종류: 스킬(`SKILL.md`), 서브에이전트 정의, 훅, 작은 MCP 서버, CLI 스크립트, 단일 HTML 도구, Claude Code 모드 중 하나.
- **한 세션에 끝나는 작은 크기.** 의존성 파일은 폴더 안에만. 폴더 밖 파일 import 금지, 공유 유틸 금지(필요하면 복사). 다른 날짜 폴더는 건드리지 않는다. 루트에 의존성 파일을 만들지 않는다.
- `test.sh`를 두고 그 폴더에서 `bash test.sh`로 통과시킨다. 모델 호출이 필요한 검증은 `e2e.sh`로 분리하고, `test.sh`는 키·모델 없이 돈다(CI가 돌린다).
- API 키가 필요하면 키 없이 도는 `--dry-run`을 같이 만든다. 키·토큰·비밀값은 절대 커밋하지 않는다.
- 모델을 부를 때는 `claude -p … --model claude-haiku-5-5 --effort low --max-turns 3 --tools "" --output-format json`을 기본으로. 구조화 출력(`--json-schema`)은 턴을 하나 더 쓰므로 `--max-turns 1`은 쓰지 않는다. `--bare`는 로그인을 건너뛰어 실패한다.
- **실패도 결과물이다.** 테스트가 끝내 안 통과해도 폴더를 지우지 않는다. README 5절에 실패한 명령과 출력을 그대로, 6절에 원인과 시도한 것을 적고, 루트 README 행의 한 줄 설명 맨 앞에 `⚠ 미완`을 붙인다.

## 4·5. README (RULES 5절)

`_template/README.md`의 7개 섹션 제목(`## 1.` ~ `## 7.`)을 **모두** 채워 `days/<오늘>-<slug>/README.md`로 둔다. 5절에는 `bash test.sh`(와 `e2e.sh`) 실제 출력을 붙인다. 7절의 URL은 실제로 응답하는 것만.

## 6. 인덱스 갱신과 푸시 (RULES 6절)

1. 루트 `README.md`의 결과물 표에서 `<!-- 최신 항목이 위로 오도록 이 줄 아래에 행을 추가 -->` 주석 아래, 헤더 행과 구분선 **바로 다음**에 오늘 행을 넣는다.
   `| 날짜 | [slug](days/<오늘>-<slug>/) | 종류 | [계기가 된 소식](URL) | 한 줄 설명 |`
2. **푸시 직전 재확인** (하나라도 걸리면 고치고, 못 고치면 ⚠ 미완 경로):
   - 프로젝트 폴더에서 `bash test.sh` 재실행 → 통과
   - `grep -c '^## [1-7]\.' days/<오늘>-<slug>/README.md` → 7
   - 루트 README 표 맨 위 행의 링크 경로가 실제 폴더와 같다
   - README 7절 URL이 응답한다: `curl -sI -o /dev/null -w '%{http_code}' -L --max-time 20 <url>` → 2xx/3xx. 아니면 그 옆에 `(확인 시점에 접속 불가)`
   - 커밋할 파일에 `sk-ant-`, `AKIA`, `ghp_`, `BEGIN .* PRIVATE KEY` 패턴이 없다: `git diff --cached | grep -nE 'sk-ant-|AKIA|ghp_|BEGIN .* PRIVATE KEY'` → 없음
3. 커밋: 파일을 **개별로** `git add`한다(`git add .`/`-A` 금지). `.env`·`credentials`·`*.key`·`*.pem`·`__pycache__`·`node_modules`는 넣지 않는다.
   ```bash
   git commit -m "$(cat <<'MSG'
   day: <오늘> <slug>
   MSG
   )"
   ```
   메시지에 `Co-Authored-By`를 넣지 않는다.
4. **`main`에 바로 푸시**: `git push origin main`. 거부되면 `git pull --rebase origin main` 후 **한 번만** 재시도. 클라우드 세션·Routine은 기본으로 `claude/` 브랜치를 만들려 하지만, 이 저장소는 **main 직접 푸시**가 규칙이다. 브랜치를 새로 만들지 않는다.
5. 마지막 답변은 세 줄: 만든 것(폴더·한 줄 설명) / 테스트 결과(통과 수, 실패면 무엇) / 커밋 해시와 푸시 여부. 실패 시 원인 한 줄.

## 환경별 메모

- **로컬 터미널**: `claude` 안에서 `/daily-lab`. 권한 프롬프트가 뜨면 승인한다.
- **클라우드 세션·Routine**: 권한 프롬프트가 없다. 네트워크는 환경의 허용 목록을 따르므로 소식 출처(dev.to, news.hada.io, producthunt.com, latent.space, simonwillison.net 등)가 막히면 소스 점검 표에 `읽기 불가(403 host_not_allowed)`로 적고 계속 간다. 환경 네트워크를 **Full**로 두면 전부 읽힌다.
- **GitHub Actions**: `.github/workflows/daily-lab.yml`이 매일 21:45 UTC(06:45 KST)에 `/daily-lab`을 부른다. 러너에는 `claude` CLI가 없을 수 있으니 e2e는 건너뛰고 README 5절에 "CI에서는 e2e 미실행"이라고 적는다.

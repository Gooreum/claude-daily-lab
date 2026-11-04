# login-watch

Claude Code 2.1.318 이 노출한 **로그인 만료일**을 읽어 남은 날짜로 ok/경고/위험/만료를 판정하는 CLI 스크립트.

## 1. 무엇을 만들었나
`login_watch.py` 한 파일(표준 라이브러리만). `claude auth status` JSON 의 `loginExpiresAt`, 또는 `claude -p … --output-format json` 결과의 `credential_expires_at` 을 읽어 남은 날수를 계산하고 `OK / WARN / CRIT / EXPIRED / LOGGEDOUT / NOEXPIRY / ERROR` 로 판정한다. 파일을 여러 개 주면 가장 급한 순서로 정렬한 표를 보여 주고, 종료 코드(0 정상 · 1 경고 · 2 위험/만료/로그아웃 · 3 입력 오류)로 cron·Actions 에 바로 물린다. `--format gha` 는 GitHub Actions 의 `::warning::`/`::error::` 줄을 낸다.

## 2. 왜 만들었나
- 계기: Claude Code 2.1.318(2026-11-04)이 저장된 claude.ai 로그인이 끝나는 날짜를 `claude auth status`(`loginExpiresAt`)와 `claude -p` JSON 결과(`credential_expires_at`)에 넣고, 만료 10일 전부터 stderr 에 한 줄 경고를 붙인다. 출처: https://github.com/anthropics/claude-code/releases/tag/v2.1.318
- 이 저장소 자신이 `CLAUDE_CODE_OAUTH_TOKEN` 하나로 매일 06:45 KST 에 무인 실행된다. 만료는 곧 "어느 날 아침 조용히 Not logged in 으로 멈춤"이다. 새 필드는 기계가 읽을 수 있게 됐지만 누군가 읽어야 쓸모가 있어서, 읽고 판정하는 얇은 도구를 만들기로 했다. (news/2026-11-04.md 1번)

## 3. 어떻게 만들었나
1. 로컬 `claude auth status` 의 실제 출력(키: `loggedIn`, `authMethod`, `loginExpiresAt`)을 먼저 확인했다. 로그아웃 상태에서는 `loginExpiresAt: null` 이다.
2. 판정은 `judge()` 순수 함수 하나로 두고 `--now` 로 기준 시각을 주입해 테스트가 날짜에 흔들리지 않게 했다.
3. 설계 결정:
   - 임계값 기본 10일은 Claude Code 자체 경고(만료 10일 전)와 맞췄고, 3일 이하는 CRIT 로 한 단계 더 둔다.
   - 만료일이 `null` 인 경우(API 키·환경 토큰 등)는 정상(NOEXPIRY)으로 두되 `--strict` 로 경고화할 수 있게 했다. **`CLAUDE_CODE_OAUTH_TOKEN`(setup-token) 환경에서 이 값이 실제로 채워지는지는 확인하지 못했다.**
   - 필드가 아예 없으면 "2.1.318 이상인가?" 를 알려 주며 입력 오류(3)로 끝낸다. 옛 CLI 를 조용히 정상으로 보지 않기 위해서다.
   - 시각은 ISO8601(`Z`/오프셋)과 epoch 초·밀리초를 모두 받는다. 필드 직렬화 형식을 릴리스 노트만으로 알 수 없어서 넓게 받았다.
   - 입력은 단일 JSON, JSONL(마지막 `result` 줄), JSON 배열, stdin(`-`)을 받는다.
4. 도구: Claude Code(Edit/Bash)만 사용. 모델 호출은 없다.

## 4. 사용법
```bash
# 지금 이 기계의 로그인 상태 (claude CLI 필요)
python3 login_watch.py --live

# claude -p 결과를 그대로 파이프
claude -p "ok" --model claude-haiku-5-5 --effort low --max-turns 3 --tools "" --output-format json | python3 login_watch.py -

# 서버 여러 대의 상태 JSON 을 모아 한 표로 (가장 급한 것부터)
python3 login_watch.py hostA.json hostB.json hostC.json

# GitHub Actions 단계: 7일 이내면 경고, 3일 이내면 error 로 잡을 수 있다
python3 login_watch.py --live --warn-days 7 --crit-days 2 --format gha

# claude 없이 출력 모양만 보기
python3 login_watch.py --dry-run
```
예시 출력(`--dry-run`):
```
EXPIRED   demo-expired  만료 2026-11-02T01:43Z  2.0일 전에 만료됨
WARN      demo-warn     만료 2026-11-10T01:43Z  6.0일 남음 — 이번 주 안에 재로그인
OK        demo-ok       만료 2026-12-04T01:43Z  30일 남음
→ 종료 코드 2 (위험/만료)
```
옵션: `--warn-days`(10) · `--crit-days`(3) · `--strict` · `--now ISO` · `--format text|json|gha`.

## 5. 테스트 결과
`bash test.sh` (키·로그인·모델 없이 실행. 이 환경에는 `claude` 2.1.318 이 있지만 로그아웃 상태라 모델 호출 e2e 는 하지 않았다):
```
ok   ok: exit 0, OK 46일
ok   warn: exit 1 (5.9일)
ok   crit: exit 2 (+00:00 표기 2.0일)
ok   expired: exit 2
ok   loggedOut: exit 2
ok   null 만료일: exit 0 NOEXPIRY
ok   --strict: null 은 WARN exit 1
ok   claude -p 결과: 8.0일 WARN
ok   JSONL 마지막 result + epoch ms
ok   stdin('-') 입력
ok   --warn-days 5: 5.9일은 OK
ok   --crit-days 7 > warn-days 10 아님: 5.9일 CRIT
오류: --crit-days 는 --warn-days 이하여야 함
ok   crit > warn 는 입력 오류 exit 3
ok   JSON 아님: exit 3
ok   필드 없음(옛 CLI): exit 3 + 버전 안내
ok   없는 파일: exit 3
ok   인자 없음: exit 3
ok   --now 형식 오류: exit 3
ok   다중: 최악 코드 2
ok   다중: EXPIRED → WARN → OK 순서
ok   gha: ::error 와 ::warning 줄
ok   json: 파싱되고 worst_exit=1
ok   dry-run: 3건, 최악 코드 2
ok   live(가짜 claude): 3.0일 CRIT
ok   live: claude 없으면 exit 3
---
통과 24 / 실패 0
```
추가로 로그아웃 상태의 실제 `claude auth status` 에 `python3 login_watch.py --live` 를 돌려 `LOGGEDOUT … 종료 코드 2` 를 확인했다. **로그인된 계정의 실제 `loginExpiresAt` 값(형식·채워지는 조건)은 이 환경에서 확인하지 못했다** — 테스트의 만료일은 모두 fixture 다.

## 6. 한계와 다음 아이디어
- 만료일 필드의 실제 값 형식을 릴리스 노트로만 알고 fixture 로 흉내 냈다. 로그인된 계정에서 `--live` 를 한 번 돌려 확인해야 한다.
- `setup-token` 토큰(Actions 용)이 만료일을 보고하는지, 몇 달짜리인지 확인하지 못했다. null 이면 이 도구는 NOEXPIRY 로 통과시키므로 Actions 보호 효과가 없을 수 있다. 그 경우 `claude -p` 결과의 `credential_expires_at` 을 쓰는 쪽을 먼저 확인해야 한다.
- stderr 의 "10일 전 경고" 한 줄은 파싱하지 않는다(문구를 모른다).
- 다음: `.github/workflows/daily-lab.yml` 앞 단계에 `--format gha` 호출을 붙이는 제안(이 저장소 워크플로는 오늘 건드리지 않음), 서버별 만료일을 모으는 cron 래퍼, `config_file_invalid`(SDK 0.3.318) 시작 실패 분기 점검.

## 7. 출처
- https://github.com/anthropics/claude-code/releases/tag/v2.1.318
- https://github.com/anthropics/claude-agent-sdk-typescript/releases/tag/v0.3.318
- https://github.com/anthropics/claude-agent-sdk-python/releases/tag/v0.2.178

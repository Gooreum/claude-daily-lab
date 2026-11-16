# rule-leak

## 1. 무엇을 만들었나
CLI 스크립트(`rule_leak.py`, 표준 라이브러리만 사용). `.claude/settings.json`·`.claude/settings.local.json`(과 선택적으로 `~/.claude/`)의 `permissions.allow/ask/deny` 규칙 문자열과 `env` 블록에서 비밀값을 찾고, 설정 파일이 git에 추적되는지·`.gitignore`로 무시되는지를 함께 판정한다. 비밀값은 앞 두 글자와 길이만 남기고 마스킹해 출력하며, 원본은 출력·JSON 어디에도 나오지 않는다.

판정은 `LEAK`(비밀값 발견), `TRACKED`(로컬 전용 파일이 git에 추적됨), `UNIGNORED`(추적은 안 되지만 `.gitignore`에도 없음 — 경고만), `ERROR`(JSON 읽기 실패), `OK`다.

## 2. 왜 만들었나
- 계기: dev.to 11-15 "Before you click 'don't ask again'" — https://dev.to/roidayan/before-you-click-dont-ask-again-what-your-coding-agent-saves-and-how-to-keep-secrets-out-of-it-j2m (news/2026-11-16.md 1번)
- 글은 Apiiro가 11-05에 공개 저장소를 훑어 `settings.local.json` 사본 10만 개 이상 중 1,122개에서 실제 비밀값을 찾았다고 전한다(iTWire 보도를 글이 재인용한 수치로, 원 조사는 직접 확인하지 못했다). 허용 규칙이 곧 명령 문자열이라서, 비밀번호를 붙여 승인하면 비밀번호도 영구 규칙으로 남는다는 구조가 "직접 점검해 볼 만하다"고 판단했다.
- 이 저장소는 루틴이 자동으로 커밋·푸시하는 공개 저장소라 설정 파일이 섞여 올라갈 위험이 직접 닿는다. 기존 `read-guard`·`secret-envoy`·`onfailure-secret-guard`는 읽기·환경변수·실패 출력을 보며, 저장된 허용 규칙 속 비밀은 보지 않는다.

## 3. 어떻게 만들었나
1. 글이 말하는 유출 경로를 세 갈래로 나눴다: 명령에 박힌 값(`PGPASSWORD=값`, `--password 값`, `curl -u 사용자:값`, `Authorization: Bearer 값`, URL의 `사용자:값@`), 알려진 키 모양(Anthropic·AWS·GitHub·Slack·Google·개인키 머리말), `env` 블록의 이름이 비밀스러운 리터럴 값.
2. **오탐을 줄이는 규칙을 먼저 정했다.** `$VAR`·`${VAR}`·`<자리표시자>`·`*` 와일드카드 값은 비밀이 아니다. 환경변수 이름은 `PASSWORD`·`TOKEN` 등으로 **끝날 때만** 보므로 `CLAUDE_CODE_MAX_OUTPUT_TOKENS`는 걸리지 않는다.
3. 같은 구간을 여러 패턴이 잡으면 먼저 맞은 패턴 하나로만 센다(예: URL 속 GitHub 토큰은 `url-cred`가 아니라 `api-key`).
4. 출력 마스킹을 시험으로 고정했다: 가짜 비밀값 6종이 출력·`--json` 어디에도 원문으로 나오지 않는지 `grep`으로 확인한다.
5. git 상태는 `git ls-files --error-unmatch`와 `git check-ignore`로 판정한다. `settings.local.json`이 추적 중이면 비밀이 없어도 `TRACKED`(exit 1)다. 이 파일은 로컬 전용이어야 하기 때문이다.
6. 시험 픽스처의 가짜 키는 `test.sh`가 실행 중에 문자열을 이어 붙여 만든다. 소스에 키 모양 문자열이 그대로 남으면 RULES 6절의 푸시 전 비밀 패턴 점검에 걸리기 때문이다(`rule_leak.py`의 정규식도 같은 이유로 나눠 적었다).

## 4. 사용법
```bash
python3 rule_leak.py                 # 현재 폴더 아래의 .claude/settings*.json 전부
python3 rule_leak.py ~/code/app      # 폴더 지정(여러 개 가능)
python3 rule_leak.py --home          # ~/.claude/settings*.json 도 함께
python3 rule_leak.py . --quiet       # OK 줄 숨김
python3 rule_leak.py . --json        # 기계가 읽는 출력
```

종료 코드: 0 = 문제 없음(`UNIGNORED` 경고 포함), 1 = LEAK·TRACKED·ERROR 있음, 2 = 사용 오류(없는 경로).
`LEAK`가 나오면 출력 안내대로 **값을 먼저 폐기·재발급**하고, 그다음 규칙에서 값을 빼 세션 허용으로 대체한다. 파일을 지워 히스토리를 다시 쓰는 것으로는 이미 퍼진 값이 회수되지 않는다는 점이 글의 요지다.

출력 예(가짜 값, 시험에서 발췌):
```text
LEAK      /tmp/…/leak/.claude/settings.local.json  [git: untracked]
          permissions.allow[0]  inline-env  Bash(PGPASSWORD=hu***(9자) psql -h db -c 'select 1')
          permissions.allow[1]  bearer  Bash(curl -H "Authorization: Bearer s3***(13자)" https://api.example.com/*)
          env.MY_API_KEY  env-literal  li***(19자)
          순서: 1) 값을 폐기·재발급 2) 규칙에서 값을 빼고 세션 허용으로 대체
```

## 5. 테스트 결과
`bash test.sh` (키·모델·네트워크 없이 돈다. 임시 폴더의 가짜 프로젝트로 시험한다. CI에서도 e2e 없이 같다):

```text
ok   - 비밀이 든 설정 → exit 1 (exit 1)
ok   - inline-env 탐지 (PGPASSWORD)
ok   - bearer 탐지 (Bearer)
ok   - api-key 탐지 (ANTHROPIC_KEY)
ok   - api-key 탐지 (aws s3)
ok   - url-cred 탐지 (r.git)
ok   - api-key 탐지 (r2.git)
ok   - cli-flag 탐지 (mysql)
ok   - curl-user 탐지 (curl -u)
ok   - env-literal 탐지 (env.MY_API_KEY)
ok   - 판정 LEAK
ok   - 마스킹 — hunter… 노출 안 됨
… (중간 생략)
ok   - --quiet 는 OK 줄을 숨긴다 (exit 0)
ok   - --quiet OK 줄 숨김
ok   - --home 이 ~/.claude 를 본다
ok   - --home 마스킹
---
통과 46 / 실패 0
```

이 저장소 전체에 돌린 실제 결과(`python3 rule_leak.py ../.. --quiet`):

```text
TRACKED   ../../days/2026-11-07-deny-preview/fixtures/proj/.claude/settings.local.json  [git: tracked]
          로컬 전용 파일이 git에 추적된다 — git rm --cached 후 .gitignore 에 추가
TRACKED   ../../days/2026-11-13-auto-mode-lint/fixtures/proj/.claude/settings.local.json  [git: tracked]
          로컬 전용 파일이 git에 추적된다 — git rm --cached 후 .gitignore 에 추가
합계: LEAK=0 TRACKED=2 UNIGNORED=0 ERROR=0 OK=7 (파일 9개)
```
→ 이 저장소의 실제 설정에는 비밀이 없다(LEAK=0). `TRACKED` 2건은 `deny-preview`·`auto-mode-lint` 폴더가 **시험용으로 일부러 커밋한 `fixtures/` 안의 가짜 설정**이라 의도된 것이다. 실제 사용 시 픽스처 폴더는 경로에서 빼고 돌리면 된다(도구는 아직 제외 옵션이 없다).

## 6. 한계와 다음 아이디어
- 정규식 휴리스틱이라 **놓칠 수 있다.** 글도 범용 스캐너가 비밀을 놓친 사례를 든다. 이름이 평범한 변수(`DB=값`)나 따옴표 안에 공백이 든 값, 스크립트 파일 안에 숨은 값은 못 본다. 반대로 `--token` 뒤의 비밀 아닌 값이 오탐일 수 있다.
- `.mcp.json`의 `env`·`headers`, `apiKeyHelper`, 훅 명령 안의 값은 보지 않는다. 설정 파일 두 종류의 규칙과 `env`만 본다.
- git 히스토리는 보지 않는다. 지금 추적되는지만 본다(과거 커밋에 남은 값은 별도 도구로 찾아야 한다).
- `UNIGNORED`는 Claude Code가 전역 git 제외에 항목을 넣어 주는 경우를 구분하지 못한다(글의 설명에 따른 동작이며 이 환경에서는 확인하지 못했다).
- 다음 아이디어: `--exclude` 옵션, `.mcp.json` 검사, 푸시 전 훅(`PreToolUse`의 `git push` 매처)으로 자동 실행, 같은 규칙을 `skill-gate`(11-15)의 `permissions.allow` 조각 출력에도 적용(조각에 비밀이 섞이지 않는지).

## 7. 출처
- https://dev.to/roidayan/before-you-click-dont-ask-again-what-your-coding-agent-saves-and-how-to-keep-secrets-out-of-it-j2m
- https://dev.to/vildandenai/stop-claude-code-from-overwriting-your-env-with-a-pretooluse-write-guard-2n21 (같은 날 수집한 2번: 읽기 deny 외에 쓰기 가드가 필요하다는 맥락)
- https://code.claude.com/docs/en/permissions
- https://code.claude.com/docs/en/settings

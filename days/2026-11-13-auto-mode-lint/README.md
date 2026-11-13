# auto-mode-lint

> Claude Code `settings.json`의 `autoMode` 블록을 점검하는 CLI. 자리표시자, `"$defaults"` 누락, 프로젝트 설정에 둔 무시되는 블록, 형식 오류를 찾는다.

## 1. 무엇을 만들었나

종류는 CLI 스크립트(`auto_mode_lint.py`, 표준 라이브러리만 사용)다. `~/.claude/settings.json`과 현재 폴더의 `.claude/settings.json`·`settings.local.json`(또는 인자로 준 파일)을 읽어 `autoMode`의 `environment`·`allow`·`soft_deny`·`hard_deny`·`classifyAllShell`을 검사하고, 오류가 있으면 exit 1을 낸다. 모델·키·네트워크가 필요 없어 dry-run이 따로 없다. 설정 파일만 읽고 쓰지 않는다.

| 규칙 | 심각도 | 무엇을 잡나 |
|------|--------|-------------|
| AM001 | `soft_deny`·`hard_deny` 오류 / `allow` 경고 / `environment` 참고 | 배열에 `"$defaults"`가 없어 내장 규칙을 통째로 대체함 |
| AM002 | 오류 | `GITHUB_ACCOUNT_HERE`·`<org>`·`TODO`·`example.com`·`acme-corp` 같은 자리표시자 |
| AM003 | 오류 | 프로젝트 설정(`.claude/settings*.json`)에 둔 `autoMode`. 분류기가 읽지 않는다 |
| AM004 | 오류·경고 | 배열이 아님, 문자열이 아닌 항목, `classifyAllShell`이 불리언이 아님, 모르는 키 |
| AM005 | 경고 | 빈 배열(내장 규칙을 대체함) |
| AM006 | 오류·경고 | `"$default"` 같은 `"$defaults"` 오타, `"$defaults"` 중복 |
| AM007 | 경고 | `Bash(npm test)`처럼 권한 규칙 문법으로 쓴 항목(autoMode 항목은 산문) |

## 2. 왜 만들었나

소식: dev.to 11-12 "My Claude Code auto mode config still said GITHUB_ACCOUNT_HERE. One command found it." — https://dev.to/rapls/my-claude-code-auto-mode-config-still-said-githubaccounthere-one-command-found-it-2mb7 (`news/2026-11-13.md` 4번).

저자는 auto mode 설정에 자리표시자를 몇 주 둔 채 썼고, `"$defaults"` 유무가 내장 차단 규칙을 살리거나 없애는 스위치라는 점을 짚는다. 공식 문서(https://code.claude.com/docs/en/auto-mode-config)를 직접 열어 확인한 사실만 규칙으로 옮겼다: `"$defaults"` 없이 `soft_deny`를 쓰면 force push·`curl | bash`·운영 배포·auto mode 우회 차단이 전부 사라지고, `hard_deny`는 데이터 유출 규칙이 사라지며, 분류기는 프로젝트 설정의 `autoMode`를 읽지 않는다. 사람이 `jq`로 눈으로 읽는 대신 기계가 매번 같은 기준으로 보게 하려고 만들었다. 이 저장소의 `sandbox-lint`·`mod-audit`·`hook-manners` 같은 설정 점검 도구에 `autoMode`를 보는 것이 없었다.

## 3. 어떻게 만들었나

1. 문서에서 규칙 근거를 먼저 확정했다. 확인한 것: `"$defaults"` 리터럴, 섹션별 독립 평가, 읽는 범위(사용자·관리형·`--settings`), `/auto-mode-setup`이 `environment`를 `"$defaults"` 없이 쓴다는 점.
2. 마지막 항목 때문에 `environment`의 `"$defaults"` 누락은 오류가 아니라 **참고**로만 표시한다. 문서가 정상 동작이라고 한 것을 오류로 띄우면 도구가 신뢰를 잃는다. `allow`는 프롬프트가 늘 뿐 안전이 줄지 않아 경고, `soft_deny`·`hard_deny`는 안전이 줄어 오류다.
3. 범위 추정은 경로로 한다(`settings.local.json`이나 홈이 아닌 `.claude/settings.json`은 프로젝트). 틀릴 수 있어 `--scope user|managed|project`로 덮어쓸 수 있다.
4. 자리표시자 탐지는 사례의 `GITHUB_ACCOUNT_HERE`(대문자 `_HERE`)를 기준으로 하되, `<...>`·`TODO`·`example.com`·`acme-corp`(문서 예시에 나오는 이름)로 넓혔다. 오탐이 날 수 있어 모두 한 줄 메시지에 원문을 보여 준다.
5. `fixtures/`에 입력 9개(정상·자리표시자·`$defaults` 없음·오타·형식 오류·패턴형·`autoMode` 없음·깨진 JSON·객체 아님)와 홈·프로젝트 폴더 모형을 두고 `test.sh`로 종료 코드와 걸린 규칙 코드 목록을 고정했다. 사용 도구는 Claude Code(Edit/Write/Bash)와 Python 3.12다.
6. 실행 중 한 번 고쳤다: 읽기 실패(exit 2)와 설정 오류(exit 1)를 구분하는 첫 구현의 종료 코드 계산이 복잡해 "AM000이 하나라도 있으면 2"로 단순화했다.

## 4. 사용법

```bash
python3 auto_mode_lint.py                       # ~/.claude/settings.json + ./.claude/settings*.json
python3 auto_mode_lint.py path/to/settings.json # 파일 지정
python3 auto_mode_lint.py managed-settings.json --scope managed
python3 auto_mode_lint.py --strict              # 경고도 실패(CI용)
python3 auto_mode_lint.py --json                # 기계가 읽는 출력
```

종료 코드: 0 문제 없음(경고만 있어도 0, `--strict`면 1) / 1 오류 있음 / 2 파일을 읽지 못함.

예시 출력(`fixtures/placeholder.json`):

```
[오류] AM002 fixtures/placeholder.json:autoMode.environment[1]
       자리표시자로 보인다: 'Source control: GitHub personal account GITHUB_ACCOUNT_HERE; repositories under '

파일 1개 · 오류 1 · 경고 0 → exit 1
실제 적용 결과는 `claude auto-mode config`로 확인한다(이 도구는 설정 파일만 본다).
```

점검 뒤에는 문서가 안내하는 `claude auto-mode config`로 합쳐진 실제 설정을 한 번 본다. 이 도구는 파일만 읽으므로 여러 범위가 합쳐진 결과는 보지 못한다.

## 5. 테스트 결과

`bash test.sh` (이 폴더에서, 키·모델 없이):

```
ok   - clean → exit 0, []
ok   - placeholder → exit 1, [AM002]
ok   - no-defaults → exit 1, [AM001]
ok   - typo → exit 1, [AM001 AM006]
ok   - badtypes → exit 1, [AM004 AM005]
ok   - patterns → exit 0, [AM007]
ok   - noauto → exit 0, []
ok   - notobject → exit 1, [AM004]
ok   - broken → exit 2, [AM000]
ok   - 없는 파일 → exit 2
ok   - 섹션별 심각도(soft/hard=오류, allow=경고, environment=참고)
ok   - --strict 는 경고도 exit 1
ok   - settings.local.json 의 autoMode → AM003 + 내용 점검도 함께
ok   - --scope user 로 범위 지정
ok   - 인자 없이 실행 시 홈 설정 + 프로젝트 설정을 탐색
ok   - 설정 파일 없음 → 안내 + exit 0
ok   - 입력 파일을 바꾸지 않는다
ok   - 텍스트 출력 요약 줄

통과 18 · 실패 0
```

e2e: 모델 호출이 없어 `e2e.sh`는 두지 않았다. 이 환경의 실제 `~/.claude/settings.json`에도 돌려 봤다: `autoMode` 블록이 없어 "기본값 그대로", 오류 0·경고 0·exit 0. 실제 Claude Code 세션에서 `claude auto-mode config`와 대조하는 것은 하지 않았다(이 실행 환경에서 auto mode 설정이 비어 있었다).

## 6. 한계와 다음 아이디어

- 파일 하나씩 점검한다. 사용자·관리형·`--settings`가 합쳐진 결과나 관리형 설정이 `"$defaults"` 없는 배열을 덧붙이는 경우는 보지 못한다. 합쳐진 결과는 `claude auto-mode config`의 JSON을 입력으로 받아 보는 모드가 다음 단계다.
- 자리표시자 탐지는 휴리스틱이다. `example.com`을 일부러 쓰는 문서용 설정은 오류로 나온다. 규칙 끄기 옵션(`--ignore AM002`)이 없다.
- 산문 규칙이 실제로 분류기에서 의도대로 읽히는지(의미)는 점검하지 못한다. 그건 모델 호출이 필요한 별도 시험이다.
- `settings.json`에 JSON 주석이 있으면 파싱 실패(exit 2)가 난다.
- 규칙은 2026-11-13 시점 문서 기준이다. 문서가 바뀌면 `LOSS` 표와 규칙을 같이 고쳐야 한다.

## 7. 출처

- https://code.claude.com/docs/en/auto-mode-config — `"$defaults"`·읽는 범위·`claude auto-mode` 하위 명령
- https://code.claude.com/docs/en/settings-reference — `autoMode` 키 형식
- https://dev.to/rapls/my-claude-code-auto-mode-config-still-said-githubaccounthere-one-command-found-it-2mb7 — 계기가 된 글
- https://github.com/anthropics/claude-code/releases/tag/v2.1.323 — 같은 날 나온 Claude Code 릴리스(오늘 소식 1번)

# settings-live

## 1. 무엇을 만들었나
Claude Code 설정 파일(`~/.claude/settings.json`, `.claude/settings.json`, `.claude/settings.local.json`)이 **읽히는지**, 안 읽히면 **무엇이 꺼지는지** 세션을 열기 전에 알려 주는 CLI 스크립트(`settings_live.py`, 표준 라이브러리만 사용)다. JSON 오류(위치와 원인 힌트), 같은 키가 두 번 나와 앞 내용이 사라지는 경우, `permissions`·`hooks`·`env` 등의 모양, 오타 키·훅 이벤트 이름, 없는 훅 스크립트를 점검하고, 파일마다 "이 파일이 담당하는 deny·ask·allow·훅·env 개수"를 보여 준다. SDK `query()`에 넘길 `settings` JSON 문자열을 `--string`으로 미리 점검할 수도 있다.

## 2. 왜 만들었나
- 계기: [claude-agent-sdk-typescript v0.3.330 (2026-11-20)](https://github.com/anthropics/claude-agent-sdk-typescript/releases/tag/v0.3.330) — 사용자·프로젝트·로컬 설정 파일이 검증에 실패해 적용되지 않으면 `settings_not_in_effect` 경고를 보내고, `query()`의 `settings`가 파싱 안 되는 JSON 문자열이면 오류로 끝난다. 앞선 v0.3.329의 `managed_hooks_not_loaded`(관리형 훅 로드 실패)와 같은 계열이다.
- 판단: 이 저장소의 `matcher-lint`·`hook-exit-audit`·`hook-merge`는 모두 "파일이 로드된다"는 전제로 훅 하나하나를 본다. 쉼표 하나로 파일이 통째로 안 읽히면 그 안의 deny 규칙과 가드 훅이 전부 꺼지는데, 이 경우를 보는 도구가 없었다. 그 피해 규모(꺼지는 deny·훅 개수)를 숫자로 보이는 것이 "만들어 볼 만하다"고 봤다.

## 3. 어떻게 만들었나
1. 점검을 심각도 셋으로 나눴다. `error`는 파일이 안 읽힐 만한 것(JSON 오류·빈 파일·최상위가 객체 아님·핵심 키의 타입 어긋남), `warn`은 읽히지만 의도와 다르게 동작할 만한 것(중복 키·오타·없는 스크립트·BOM), `info`는 이 도구가 모르는 이름(목록이 스냅샷이라 새 키일 수 있음).
2. 오탐을 줄이려고 **모르는 키는 가까운 알려진 키가 있을 때만 warn**(`difflib`, 대소문자만 다른 경우 포함)으로 올리고, 아니면 info로 둔다. 훅 이벤트 이름도 같다.
3. JSON이 깨졌을 때는 주석과 후행 쉼표를 걷어 낸 사본으로 한 번 더 파싱해 "고치면 살아날 deny N·훅 M개"를 센다. 뭐가 걸려 있는지 알아야 심각도를 느낄 수 있어서다.
4. 중복 키는 `object_pairs_hook`으로 잡고, 덮여 사라지는 쪽의 deny·훅 개수까지 메시지에 넣는다(`permissions`가 두 번 나오는 흔한 병합 실수).
5. 훅 `command`는 첫 단어(또는 인터프리터 다음 단어)를 경로로 보고 `$CLAUDE_PROJECT_DIR`·`$HOME`·`./`를 풀어 존재만 확인한다. 없으면 exit 127로 끝나는데 127은 호출을 막지 못하므로(막는 코드는 2) 가드가 조용히 무력해진다.
6. 파일 탐색은 홈·프로젝트·로컬 세 곳, `--root`·`--home`으로 바꿀 수 있어 테스트가 실제 홈에 기대지 않는다. 결과는 사람이 읽는 표, `--json`, 종료 코드(error면 1, `--strict`면 warn도 1)로 낸다.
7. 막힌 곳: 이 환경의 `claude`가 로그인이 안 돼 있어 `claude -p`로 `settings_not_in_effect`가 실제로 나오는지는 확인하지 못했다(5절).

## 4. 사용법
```bash
cd days/2026-11-21-settings-live
python3 settings_live.py                      # ~/.claude/settings.json, ./.claude/settings*.json 자동 탐색
python3 settings_live.py path/to/settings.json [...]
python3 settings_live.py --root ../my-repo --home /tmp/fakehome
python3 settings_live.py --string '{"permissions":{"deny":["Read(./.env)"],}}'   # SDK query()의 settings 문자열
python3 settings_live.py --json --strict      # CI용: JSON 출력, warn도 실패
```
깨진 파일 예(`fixtures/trailing_comma.json`):
```
== fixtures/trailing_comma.json
  error SL01 3행 47열 — JSON 파싱 실패: Expecting value — 마지막 항목 뒤에 쉼표(,)가 남았다
  stake 고치면 살아날 것: deny 2 · ask 1 · allow 0 · 훅 1 · env 0 · (PreToolUse 1)
  stake → deny 2개·훅 1개가 적용되지 않은 채 세션이 시작된다(SDK는 settings_not_in_effect 경고만 보낸다)
```
규칙: SL01 JSON 오류·빈 파일 / SL02 최상위가 객체 아님 / SL03 모양 어긋남 / SL04 설정 키 오타 / SL05 훅 이벤트 이름 오타 / SL06 없는 훅 스크립트 / SL07 BOM / SL09 중복 키 / SL10 권한 규칙 괄호 짝 불일치.

활용: 커밋 전 `git pre-commit`에서 `python3 settings_live.py .claude/settings.json --strict`, 또는 SessionStart 훅에서 한 번 돌려 error가 있으면 알림.

## 5. 테스트 결과
`bash test.sh` (키·모델 없이 동작, CI가 실행):
```
ok   good: exit 0
ok   good: error 0 · warn 0 · info 0
ok   good: deny 2 · 훅 3 담당 표시
ok   SL01 후행 쉼표: exit 1
ok   SL01 후행 쉼표: 3행과 원인
ok   SL01 후행 쉼표: 고치면 살아날 deny 2 · 훅 1
…(중략)…
ok   --json: 올바른 JSON이고 rule SL01
ok   없는 파일: error 읽을 수 없다

통과 49 · 실패 0
```
`bash e2e.sh` — **CI에서는 e2e 미실행.** 이 환경에서 직접 돌린 결과:
```
ok   settings_live: 깨진 파일을 error 로 잡음
SKIP 로그인이 없어 claude -p 확인 생략
```
`claude` 2.1.330이 있었지만 `Not logged in · Please run /login`으로 끝나 모델 호출이 없었다. 따라서 **`claude -p`/SDK 스트림에 `settings_not_in_effect`가 실제로 오는지, 이 도구가 error로 잡는 파일과 Claude Code가 "검증 실패"로 보는 파일이 일치하는지는 확인하지 못했다.**
이 저장소 실제 설정(`~/.claude/settings.json`)에 돌리면 "지적 없음"(담당하는 규칙 0개)이었다.

## 6. 한계와 다음 아이디어
- **"검증 실패"의 정확한 기준은 릴리스 노트에 없다.** 이 도구의 error 기준(엄격한 JSON·핵심 키 타입)은 문서와 일반 JSON 규칙에 근거한 추정이라, Claude Code가 후행 쉼표·주석을 실제로 허용하는지(관대하게 읽는지)는 확인하지 못했다. 허용한다면 SL01의 해당 사례는 과잉 경고다. e2e에서 로그인 상태로 돌려 대조하는 것이 첫 후속 작업이다.
- 알려진 키·훅 이벤트·핸들러 종류·권한 모드 목록은 이 날짜의 스냅샷이라 새 키는 info로만 나온다. 공식 JSON 스키마를 받아 쓰는 `--schema` 옵션이 다음 단계다.
- 관리형 설정(Admin API)·`--settings`로 넘기는 파일·플러그인이 선언한 훅은 점검하지 않는다. 훅 `command`의 경로 해석은 첫 단어만 보며 셸 파이프·`cd` 뒤의 경로는 보지 않는다.
- 권한 규칙 문법(`Bash(...)` 인자 패턴 내용)은 괄호 짝만 본다. `matcher-lint`와 합쳐 "파일 → 모양 → matcher → 병합 결과"를 한 번에 돌리는 점검 체인이 다음 아이디어다.

## 7. 출처
- https://github.com/anthropics/claude-agent-sdk-typescript/releases/tag/v0.3.330 (`settings_not_in_effect`, `settings` JSON 문자열 오류)
- https://github.com/anthropics/claude-agent-sdk-typescript/releases/tag/v0.3.329 (`managed_hooks_not_loaded`)
- https://github.com/anthropics/claude-code/releases/tag/v2.1.330 (Edit가 거부하던 유효한 훅 명령 수정 등)
- https://code.claude.com/docs/en/settings
- https://code.claude.com/docs/en/hooks

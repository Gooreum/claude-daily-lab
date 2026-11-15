# skill-gate

> `days/2026-11-15-skill-gate/` — 예약 작업·`/loop`가 승인 대기로 멈출 스킬을 미리 찾는 점검기.

## 1. 무엇을 만들었나

CLI 스크립트(`skill_gate.py`, 표준 라이브러리만, 키·네트워크·모델 불필요). 폴더 안의 `SKILL.md`를 전부 찾아 `allowed-tools`나 `hooks`를 선언한 스킬을 가려내고, 프로젝트의 `.claude/settings.json`·`settings.local.json`(과 `--settings`로 준 파일)의 `permissions`와 대조해 스킬마다 `NEEDS-ALLOW`(허용 규칙 없음) / `ALLOWED` / `ASK`(ask 규칙이 있어 계속 묻는다) / `DENIED` / `FREE`(선언 없음, 이 확인 대상 아님)로 판정한다. 빠진 규칙은 `permissions.allow`에 합칠 JSON 조각(`Skill(이름)`)으로 출력한다. `!` 백틱 주입 줄이 있으면 참고로 줄 번호를 알린다. 막힐 스킬이 있으면 exit 1이다.

## 2. 왜 만들었나

- 소식: [Claude Code 2.1.325 (11-13)](https://github.com/anthropics/claude-code/releases/tag/v2.1.325). 변경 목록에 "예약 작업과 `/loop`는 `allowed-tools`나 `hooks`를 선언한 스킬을 실행하기 전에 묻고, 무인으로 돌리려면 `permissions.allow`에 `Skill(name)`을 추가하라"는 줄이 있다(11-14 news 1번의 후속, 11-15 news 1번).
- 함께 본 글: [dev.to 11-14: A Skill Can Run Commands Before Claude Reads It](https://dev.to/promptmaster/a-skill-can-run-commands-before-claude-reads-it-what-to-check-first-20b5) — 스킬이 명령을 실행하거나 권한을 여는 위치를 짚는다.
- 이 저장소의 `/daily-lab` 스킬이 바로 `allowed-tools`를 선언한 스킬이다. Routine에서 매일 06:45에 도는 작업이 첫 줄에서 승인 대기에 걸릴 수 있는지 사람이 릴리스 노트를 읽지 않고 기계로 확인하고 싶었다. `skill-lint`(10-23)는 규격·위험 패턴을 보지만 "무인 실행에 필요한 허용 규칙이 빠졌나"는 보지 않는다.

## 3. 어떻게 만들었나

1. 릴리스 노트의 문장을 규칙으로 옮겼다: 게이트 대상 = `allowed-tools` 또는 `hooks` 선언, 해소 방법 = `permissions.allow`의 `Skill(name)`. `!` 주입 줄은 이 문장의 대상이 아니므로 판정에 쓰지 않고 참고로만 알린다.
2. frontmatter는 `skill-lint`처럼 PyYAML 없이 읽는다(폴더 밖 import 금지라 필요한 부분만 복사해 줄였다). 한 줄 값, 목록(`- `), `[]`, 비어 있는 `hooks:`를 구분해야 "선언했나"를 맞게 판정하므로 "빈 선언은 FREE"를 테스트로 먼저 고정했다.
3. 설정 탐색: 스킬 경로가 `<루트>/.claude/skills/<이름>/SKILL.md`면 그 `<루트>`의 설정 두 개를, 아니면 인자로 준 폴더의 설정을 읽는다. 프로젝트마다 다른 설정이 섞이지 않게 했다(테스트 포함). 사용자 전역 설정은 `--settings`로 명시해야 읽는다(홈 디렉터리를 몰래 읽지 않기 위해).
4. 규칙 일치는 `Skill`(전체), `Skill(이름)`, `Skill(이름 *)`, `Skill(이름:*)`를 인정하고, 이름이 부분만 같은 규칙은 불허한다. 우선순위는 deny > ask > allow다.
5. `DENIED`·`ASK`는 `--print-allow` 조각에 넣지 않는다. 사람이 일부러 둔 규칙을 덮으라고 권하지 않기 위해서다(대신 exit 1로 알린다).
6. 모델이 필요 없어서 Claude 호출은 쓰지 않았다. Claude Code 기능은 조사 단계(WebFetch 대신 curl로 릴리스 본문 확인)에만 썼다.

## 4. 사용법

```bash
python3 skill_gate.py .claude/skills              # 이 저장소의 스킬 점검
python3 skill_gate.py . --quiet                   # 막힐 스킬만
python3 skill_gate.py . --settings ~/.claude/settings.json   # 전역 규칙도 포함
python3 skill_gate.py . --print-allow             # 빠진 규칙만 JSON 조각으로
python3 skill_gate.py . --json                    # 기계가 읽는 출력
```

종료 코드: 0 = 막힐 스킬 없음, 1 = NEEDS-ALLOW·ASK·DENIED 있음, 2 = 사용 오류(없는 경로, SKILL.md 없음).

이 저장소에 돌린 실제 출력:

```text
NEEDS-ALLOW daily-lab  [allowed-tools]  .claude/skills/daily-lab/SKILL.md
            무인 실행 시 실행 전에 묻는다 — permissions.allow 에 규칙 필요
            참고: ! 주입 줄 1개(줄 23) — 렌더링 때 실행됨
FREE        daily-lab-apply  [-]  .claude/skills/daily-lab-apply/SKILL.md
            allowed-tools·hooks 선언 없음 — 이 확인 대상 아님
합계: NEEDS-ALLOW=1 DENIED=0 ASK=0 ALLOWED=0 FREE=1

빠진 규칙(permissions.allow 에 합칠 것):
{ "permissions": { "allow": [ "Skill(daily-lab)" ] } }
```

## 5. 테스트 결과

`bash test.sh` (키·모델·네트워크 없이 돈다. 전부 임시 폴더에 만든 가짜 프로젝트로 시험한다):

```text
ok   - 허용 규칙이 빠졌으면 exit 1
ok   - 한 줄 allowed-tools → NEEDS-ALLOW
ok   - 목록형 allowed-tools → NEEDS-ALLOW
ok   - hooks 만 있어도 NEEDS-ALLOW
ok   - 선언 없는 스킬 → FREE
ok   - allowed-tools: [] / 빈 hooks: → FREE
ok   - name 키 없으면 폴더 이름 사용
ok   - 선언 종류(allowed-tools·hooks)를 표시
ok   - --print-allow 는 이름순 Skill(이름) JSON 조각
ok   - --json 구조(skills·allow_snippet)
ok   - --quiet 는 FREE 를 숨김
ok   - 규칙을 모두 갖추면 exit 0
ok   - '이름 *'·'이름:*' 형태도 허용으로 인정
ok   - 빠진 규칙이 없으면 조각을 안 냄
ok   - 이름이 부분만 같은 규칙은 허용이 아님
ok   - settings.local.json 의 'Skill' 은 전체 허용
ok   - deny 가 allow 보다 우선 → DENIED
ok   - ask 가 allow 보다 우선 → ASK
ok   - DENIED·ASK 도 exit 1
ok   - DENIED·ASK 는 허용 조각에 넣지 않는다(규칙을 지우라는 뜻이 아니므로)
ok   - 다른 프로젝트 규칙은 그 프로젝트 설정으로 판정
ok   - 경로 둘을 함께 줘도 설정이 섞이지 않음
ok   - 전역 규칙 없이는 NEEDS-ALLOW
ok   - --settings 로 전역 규칙을 더하면 통과
ok   - ! 주입 줄은 인라인과 느낌표 펜스만 세고 일반 펜스 안은 제외
ok   - 주입 줄만으로는 게이트 대상이 아님(참고만)
ok   - 깨진 settings.json 은 경고 후 규칙 없음으로 처리
ok   - 없는 경로는 exit 2
ok   - SKILL.md 없는 폴더는 exit 2
ok   - 없는 --settings 파일은 exit 2
ok   - 이 저장소 daily-lab 스킬을 읽음

통과 31 · 실패 0
```

`e2e.sh`는 없다. 모델 호출이 필요한 검증이 없고, 실제 Claude Code가 예약 작업에서 정말 멈추는지는 이 환경에서 시험하지 못했다(6절).

## 6. 한계와 다음 아이디어

- **판정은 릴리스 노트 문장에 기댄 추정이다.** 실제 Claude Code에서 예약 작업·`/loop`가 멈추는 것을 재현해 보지 않았다(로그인된 예약 작업 환경이 없다). `Skill(name)` 외의 문법(`Skill(name *)`, `Skill(name:*)`, 맨 `Skill`)을 허용으로 보는 것도 권한 규칙 일반 문법에서 유추한 것이라 문서로 확인하지 못했다.
- 이 저장소의 GitHub Actions 실행은 `--allowedTools`로 도구를 열어 두므로 같은 게이트가 걸리는지는 알 수 없다. `/daily-lab`은 `disable-model-invocation: true`라 `Skill(daily-lab)`이 필요한 경로가 "예약 작업이 스킬을 부를 때"인지도 확인하지 못했다. 그래서 이 저장소의 `.claude/settings.json`에는 규칙을 넣지 않았다.
- 플러그인이 배포하는 스킬(`plugin:skill` 이름)과 관리형 설정(managed settings)은 읽지 않는다. `hooks`·`allowed-tools` 파싱은 흔한 모양만 지원하는 간이 파서다.
- 다음 아이디어: `--fix`로 `settings.json`에 조각을 합치기(기존 규칙 보존), `skill-lint`에 "무인 사용 시 규칙 필요" 정보 줄 추가, CI에서 새 스킬이 `hooks`를 선언하면 PR에 알리기.

## 7. 출처

- https://github.com/anthropics/claude-code/releases/tag/v2.1.325
- https://dev.to/promptmaster/a-skill-can-run-commands-before-claude-reads-it-what-to-check-first-20b5
- https://code.claude.com/docs/en/skills
- https://code.claude.com/docs/en/permissions

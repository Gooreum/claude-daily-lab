# sandbox-lint

> `days/2026-10-29-sandbox-lint/` — Claude Code 샌드박스 설정(`settings.json`)의 구멍을 무인 작업 기준으로 정적 점검하는 CLI.

## 1. 무엇을 만들었나
Python 표준 라이브러리만 쓰는 CLI `sandbox_lint.py`다. 사용자(`~/.claude/settings.json`)·프로젝트(`.claude/settings.json`)·로컬(`settings.local.json`)·관리형(`managed-settings.json`) 설정을 우선순위(관리형 > 로컬 > 프로젝트 > 사용자)대로 합쳐 읽고, 18개 규칙으로 HIGH/MEDIUM/INFO를 매긴다. 샌드박스 꺼짐, `failIfUnavailable` 없음, 샌드박스 밖 재시도 허용, 자격 증명 경로 읽기 거부 없음, 프로젝트 설정에서 무시되는 키(`network.strictAllowlist` 등), 약화 플래그, 넓은 `excludedCommands`, 넓은 허용 도메인·쓰기 범위, `denyRead`만 있고 내장 Read 도구 규칙이 없는 틈, `bypassPermissions` + 느슨한 샌드박스를 찾는다. 프로필은 `unattended`(기본)와 `interactive`, 종료 코드는 0/1/2/3, `--json`과 권장 설정 조각을 찍는 `--print-baseline`을 지원한다.

## 2. 왜 만들었나
2026-10-28 dev.to 글 [Claude Code Sandbox Mode: Exact Config and What It Blocks](https://dev.to/aobaworks/claude-code-sandbox-mode-exact-config-and-what-it-blocks-309p)는 샌드박스가 Bash 쓰기·네트워크만 막고 기본값에서는 `~/.ssh` 같은 읽기, 내장 도구, 훅, 로컬 MCP를 막지 않는다고 정리한다. 같은 날 [권한 프리셋 3종과 그 틈](https://dev.to/luijhy_michaelguerraflo/3-permission-presets-for-claude-code-strict-balanced-autonomous-and-the-gap-none-of-them-close-4pn8) 글은 `Read` 거부가 셸의 `cat .env`를 못 막는 문제를 짚는다. "켜 뒀다"와 "막힌다" 사이의 간격이 설정 파일 안에 그대로 보이므로 정적 점검이 맞는다고 봤다. 이 저장소의 `mod-audit`·`mcp-rule-audit`·`agent-scope-lint`·`dir-trust`는 설치물·규칙·지침 파일을 보지만 샌드박스 설정 자체를 보는 도구는 없었다.

## 3. 어떻게 만들었나
1. **기준 확인**: 글만 믿지 않고 공식 문서 [sandboxing](https://code.claude.com/docs/en/sandboxing)에서 키 이름과 "사용자·관리형·`--settings`에서만 효력이 있는 키" 목록, `Read` 거부 규칙이 샌드박스 설정에 합쳐진다는 설명을 확인해 규칙에 옮겼다. 문서 발췌가 잘려 일부(7천 자)는 읽지 못했다.
2. **범위별 유효값**: 대부분의 키는 우선순위가 가장 높은 범위의 값을 쓰고, `allowUnsandboxedCommands`는 어느 범위든 `false`면 꺼진 것으로 본다(문서: 사용자·관리형의 `false`는 프로젝트의 `true`보다 우선). `strictAllowlist`는 사용자·관리형 범위의 값만 센다.
3. **경로 비교**: 샌드박스 경로(`~/.ssh`)와 권한 규칙(`Read(~/.ssh/**)`, `Read(//etc/x)`)을 `~/…`·절대 경로 문자열로 맞춘 뒤 접두사 포함 관계로 비교한다. 홈 하위 절대 경로는 `~`로 바꾼다. 프로젝트 상대 규칙(`Read(/src/**)`)은 비교할 수 없어 건너뛴다.
4. **프로필**: 같은 구멍이라도 사람이 앞에 있으면 덜 위험하다. `fail-open`·`no-strict-allowlist`는 interactive에서 보지 않고 `sandbox-off`·`unsandboxed-retry`는 MEDIUM으로 낮춘다.
5. **막힌 지점**: 처음 테스트 두 건이 실패했다. 코드가 아니라 기대값이 틀렸다(HIGH가 사라진 뒤에도 MEDIUM이 남는 것이 맞고, `--ignore` 뒤에도 다른 HIGH가 남는다). 의도(그 규칙만 사라진다)를 지키도록 기대값을 고쳤다.
6. **사용 도구**: Python 3.12, bash, Claude Code(Sonnet 5.5), WebFetch로 소식·문서 확인. 계획·승인 단계 없이 바로 만들었다.

## 4. 사용법
키가 필요 없고 읽기 전용이다. 모델도 네트워크도 쓰지 않는다.
```bash
cd days/2026-10-29-sandbox-lint
python3 sandbox_lint.py ~/work/my-repo                 # 프로젝트 + 사용자 설정 점검 (무인 작업 기준)
python3 sandbox_lint.py . --profile interactive         # 사람이 앞에 있을 때 기준
python3 sandbox_lint.py ~/.claude/settings.json         # 파일 하나를 직접 점검
python3 sandbox_lint.py . --managed /etc/claude-code/managed-settings.json
python3 sandbox_lint.py . --ignore outside-sandbox --json
python3 sandbox_lint.py --print-baseline                # 무인 작업용 권장 설정 조각
```
종료 코드: 0=문제 없음(INFO만) · 1=검토 필요 · 2=위험 · 3=사용법 오류. 야간 작업 스크립트 앞에 `python3 sandbox_lint.py . || exit 1`을 두면 HIGH·MEDIUM이 있는 설정으로는 시작하지 않는다.

예시 출력(합성 프로젝트, 일부):
```
[HIGH  ] broad-domain        (project) sandbox.network.allowedDomains
          `*.com`는 사실상 모든 호스트를 허용한다. 프록시는 호스트 이름만 보므로 어디로든 유출 가능하다.
[HIGH  ] bypass-unsandboxed  (project) permissions.defaultMode
          bypassPermissions에서는 샌드박스 밖 재시도까지 자동 승인된다. 샌드박스가 없는 것과 같다.
[MEDIUM] ignored-in-project  (project) sandbox.network.strictAllowlist
          project 설정에 있지만 이 키는 사용자·관리형·--settings에서만 효력이 있어 무시된다.
[MEDIUM] read-tool-gap       (project) sandbox.filesystem.denyRead
          `~/.ssh`는 Bash에서만 막힌다. 내장 Read 도구는 permissions 규칙을 따르므로 여전히 읽을 수 있다.
HIGH 6 · MEDIUM 7 · INFO 1 → 위험 — 이 설정으로 무인 작업을 돌리지 말 것
```

## 5. 테스트 결과
`cd days/2026-10-29-sandbox-lint && bash test.sh` (키·모델 없이 동작. 이 도구는 모델을 부르지 않으므로 e2e는 해당 없음):
```
== 기준을 만족하는 설정
  ✅ 엄격 설정은 문제 없음 (exit=0)
  ✅ 훅이 있으면 INFO만, 종료 코드 0 (exit=0)
== 샌드박스 자체          … 8건 통과 (user의 false가 project의 true보다 우선, local이 user를 덮음 포함)
== 프로젝트에서 무시되는 키 … 3건 통과
== 약화 플래그             … 2건 통과
== 자격 증명·읽기          … 5건 통과 (절대 경로를 ~로 맞춘 비교 포함)
== excludedCommands       … 4건 통과
== 허용 도메인             … 4건 통과
== 쓰기 범위               … 4건 통과
== bypassPermissions·프록시 … 3건 통과
== 입력·출력              … 10건 통과 (깨진 JSON, 관리형 덮어쓰기, --ignore, --json, --print-baseline)
통과 45 · 실패 0
```
처음 실행에서는 45건 중 2건이 실패했다(`사용자의 false는 프로젝트의 true보다 우선`은 exit=1이어야 하는데 2로 기대, `--ignore로 규칙 끄기`는 다른 HIGH가 남아 exit=2여야 하는데 1로 기대). 둘 다 테스트 기대값 오류여서 기대값을 고쳐 재실행해 45건이 통과했다.

실제 환경 확인: 이 GitHub Actions 러너에서 `python3 -I sandbox_lint.py ../..`를 돌리자 사용자 설정이 샌드박스를 켜지 않아 `sandbox-off`·`unsandboxed-retry`(HIGH)와 `cred-not-denied`(MEDIUM)가 나왔고 종료 코드는 2였다. 이 저장소의 `.claude/`에는 settings.json이 없다.

## 6. 한계와 다음 아이디어
- 키 이름과 효력 범위는 2026-10-29 시점의 문서와 글에 근거한다. 문서 발췌의 마지막 약 7천 자는 읽지 못했고 전체 설정 레퍼런스 표와 대조하지 않았다. 키가 바뀌면 규칙도 바꿔야 한다.
- 실제로 Claude Code를 띄워 `cat ~/.ssh/id_rsa`가 막히는지 확인하지 않았다. 설정 파일이 맞는지만 본다. 다음에는 샌드박스를 켠 임시 홈에서 `claude -p`로 읽기를 시켜 보는 e2e를 따로 둘 수 있다.
- `--settings` 인자로 주는 설정과 플러그인이 더하는 설정은 읽지 않는다. 훅·로컬 MCP 서버가 샌드박스 밖에서 도는 것은 INFO로 알리기만 하고 내용은 검사하지 않는다(그건 `dir-trust`의 몫).
- 와일드카드 도메인 판정은 정적 목록(공용 호스팅 16곳)이다. 허용 도메인으로의 유출은 프록시가 호스트 이름만 보므로 근본적으로 막을 수 없다.
- 다음 아이디어: `permissions.allow`와 `deny` 규칙끼리의 포함 관계(`Bash(git:*)` 아래에 `git push --force`가 들어가는 문제)를 같은 방식으로 정리하는 점검, 그리고 `claude -p` 시작 전에 이 린트를 자동으로 부르는 훅.

## 7. 출처
- https://dev.to/aobaworks/claude-code-sandbox-mode-exact-config-and-what-it-blocks-309p
- https://dev.to/luijhy_michaelguerraflo/3-permission-presets-for-claude-code-strict-balanced-autonomous-and-the-gap-none-of-them-close-4pn8
- https://code.claude.com/docs/en/sandboxing
- https://code.claude.com/docs/en/settings

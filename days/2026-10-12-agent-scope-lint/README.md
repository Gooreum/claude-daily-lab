# agent-scope-lint

## 1. 무엇을 만들었나
Claude Code 서브에이전트 정의(`.claude/agents/*.md`)와 `settings.json`의 권한 규칙에서 **"막았다고 믿지만 실제로는 다르게 동작하는"** 설정을 정적으로 잡는 CLI 린터다(`agent_scope_lint.py`, 표준 라이브러리만). 모델 호출 없이 돌고, 실제 Claude Code에서 핵심 전제를 다시 확인하는 `e2e.sh`를 함께 둔다.

| 코드 | 수준 | 잡는 것 |
|---|---|---|
| AS001 | error | `disallowedTools`의 괄호 지정자(`Bash(git push *)`) → `git push`만이 아니라 Bash 도구 **전체**가 사라진다 |
| AS002 | warn | 셸을 막은 서브에이전트가 `Agent`(옛 이름 `Task`) 도구는 갖고 있다 → 이 에이전트가 띄우는 손자 에이전트는 제한을 물려받지 않는다 |
| AS003 | warn | `permissions.deny`의 `Bash(git <sub> …)` → `git -C <경로> <sub>`, `git -c k=v <sub>`, `git --git-dir=… <sub>`로 우회된다 |
| AS004 | warn | `tools` 허용 목록에 괄호 지정자 → 도구 목록은 이름 단위라 뜻대로 안 먹을 수 있다(실측 없음, 그래서 warn) |
| AS000 | warn | 직접 지정한 파일의 프론트매터 누락·JSON 파싱 실패 |

## 2. 왜 만들었나
계기: dev.to 10-12 [Bash(git push *) in a Claude Code subagent's disallowedTools took away all of Bash in 10 of 10 launches](https://dev.to/rulestack/bashgit-push-in-a-claude-code-subagents-disallowedtools-took-away-all-of-bash-in-10-of-10-4ihj) ([news 1번](../../news/2026-10-12.md)).

글쓴이는 Claude Code 2.1.289에서 `claude -p` 39회로 세 가지 함정을 쟀다. ① `disallowedTools: Bash(git push *)`는 10/10회 Bash 전체를 없앴다(`git status`도 0/3). ② `permissions.deny: Bash(git push *)`는 문자 그대로의 `git push`만 막고 `git -C <경로> push`는 3/3 통과했다. ③ 제한된 서브에이전트가 띄운 서브에이전트는 Bash로 2/2 푸시했다.

셋 다 **정의 파일과 설정만 보면 알 수 있는** 문제라 린터로 만들 만했다. "리뷰 에이전트에게 푸시만 막았다"고 믿는 순간 그 에이전트는 테스트도 못 돌리고, 반대로 "deny 규칙으로 푸시를 막았다"고 믿는 순간 `-C` 한 번으로 뚫린다. 어제(10-11) secret-envoy·10-10 disaster-guard가 "무엇을 막을지"를 다뤘다면 오늘은 "막는 설정이 정말 그렇게 동작하는지"를 본다.

## 3. 어떻게 만들었나
1. **규칙 정하기.** 글의 실측 표를 그대로 규칙으로 옮겼다. 측정된 것(①②③)은 AS001~003, 글이 재지 않은 `tools` 허용 목록의 지정자는 확신이 없어 AS004 warn으로 낮췄다.
2. **프론트매터 파서.** PyYAML 의존을 피하려고 필요한 형태만 읽는 작은 파서를 썼다: `key: a, b` / `key: [a, b]` / 블록 리스트. 쉼표는 괄호 바깥에서만 나눈다(`Bash(a, b)`가 쪼개지지 않게).
3. **도구 상속 모델.** `tools`가 없으면 부모 도구를 모두 물려받는다고 보고, 셸이 없어진 상태(명시적 `Bash`든 AS001의 지정자 효과든)에서 `Agent`가 남으면 AS002를 낸다. 그래서 `Bash(git push *)` 하나만 적은 정의는 AS001+AS002 두 개가 함께 뜬다 — 글의 agent-a가 정확히 이 조합이었다.
4. **AS003은 git만.** `docker`, `kubectl`도 하위 명령 앞에 전역 옵션이 오지만 글이 잰 것은 git이라 git만 본다.
5. **오탐 하나 수정.** 내 `~/.claude/agents/`에 돌려 보니 `guides/` 하위의 일반 문서가 AS000으로 걸렸다. 폴더를 훑다 만난 프론트매터 없는 `.md`는 에이전트가 아닌 문서로 보고 건너뛰게 바꿨다(파일을 직접 지정하면 여전히 경고).
6. **현재 버전에서 전제 재확인(e2e).** 글은 2.1.289, 지금은 2.1.296이다. 임시 폴더에 프로브 서브에이전트 두 개(지정자 / 제한 없음, `model: haiku`)를 만들고 Haiku 5.5 메인 세션에게 각각 한 번 부르게 해 "프롬프트 맨 위에 정의된 도구 이름"을 그대로 받았다. 첫 시도는 "호출 가능한 모든 도구"라고 물어 프로브가 지연 로드 도구 목록만 읊는 바람에(Read·Edit도 빠짐) 판단이 흐렸다. 질문을 "직접 호출 가능한 함수만, 지연 로드 제외"로 좁히자 2/2회 같은 목록이 나왔다.

사람이 정한 것: 규칙 범위(실측된 것만 error), AS004를 warn으로 둔 판단. Claude가 만든 것: 파서·린터·테스트·프로브 스크립트 초안.

## 4. 사용법
```bash
cd days/2026-10-12-agent-scope-lint
python3 agent_scope_lint.py ~/my-project            # .claude/agents/**.md + .claude/settings{,.local}.json
python3 agent_scope_lint.py ~/.claude/agents ~/.claude/settings.json
python3 agent_scope_lint.py path/to/agent.md --json
python3 agent_scope_lint.py ~/my-project --strict   # warn도 exit 1 (CI용)
# exit 0 = error 없음, 1 = error 있음(--strict면 warn 포함), 2 = 경로 없음
```

예시 (`fixtures/bad`):
```
fixtures/bad/.claude/agents/pusher.md:4: error AS001 disallowedTools의 `Bash(git push *)`는 `Bash(…)`만이 아니라 Bash 도구 전체를 없앤다
    → 셸이 필요 없으면 `disallowedTools: Bash`로 의도를 드러내고, 셸은 두고 일부 명령만 막으려면 settings의 permissions.deny + PreToolUse 훅을 쓴다
fixtures/bad/.claude/agents/pusher.md:4: warn AS002 셸이 막힌 서브에이전트가 Agent 도구를 갖고 있다. 이 에이전트가 띄우는 서브에이전트는 제한을 물려받지 않아 Bash를 쓴다
    → disallowedTools에 Agent를 추가하거나, tools 허용 목록에서 Agent/Task를 뺀다
fixtures/bad/.claude/settings.json:5: warn AS003 deny `Bash(git push *)`는 명령 문자열만 비교한다. `git -C <경로> push`, `git -c <키>=<값> push`, `git --git-dir=<경로> push`는 걸리지 않는다
    → git 전역 옵션을 걷어낸 뒤 하위 명령 `push`를 보는 PreToolUse 훅을 짝으로 두고, 꼭 막아야 하면 원격(보호 브랜치·pre-receive)에서 막는다
파일 4개 · error 1 · warn 4
```

고치는 방향:
```yaml
# 셸이 필요 없는 리뷰어
disallowedTools: Bash, Agent
# 읽기 전용 수집기
tools: Read, Grep, Glob, WebFetch
```

## 5. 테스트 결과
`bash test.sh` (키·모델 없음, CI가 돌림):
```
ok   bad 픽스처는 exit 1
ok   AS001: pusher의 Bash(git push *) 지정자 error
ok   AS002: pusher는 Bash가 통째로 빠지고 Agent는 남음
ok   AS002: 블록 리스트로 Bash만 막은 no-shell
ok   AS003: settings deny Bash(git push *) 우회 경고
ok   AS003: git이 아닌 deny(rm -rf, Read)는 경고 없음
ok   AS004: 허용 목록 지정자 경고
ok   allowlist는 Bash도 Agent도 가졌으니 AS002 없음
ok   AS003 줄 번호가 deny 규칙 줄(5)을 가리킴
ok   good 픽스처는 exit 0
ok   good 픽스처는 지적 0건
ok   warn만 있으면 exit 0
ok   --strict면 warn도 exit 1
ok   없는 경로는 exit 2
ok   split_top은 괄호 안 쉼표를 보존
ok   프론트매터 없으면 AS000
ok   Task(옛 이름)도 Agent로 취급
ok   PowerShell 지정자도 AS001
ok   직접 지정한 .md에 프론트매터가 없으면 AS000
ok   JSON 파싱 실패는 AS000
통과 20 · 실패 0
```

`bash e2e.sh` (로그인 필요, Haiku 5.5 2회, 합계 약 $0.011). CI에서는 e2e 미실행:
```
claude 2.1.296 (Claude Code)
COST 0.005331455
probe-spec:  Agent, Edit, ListAgents, Read, ReportFindings, Skill, ToolSearch, Write
COST 0.005676415000000001
probe-open: Agent, Bash, Edit, ListAgents, Read, ReportFindings, Skill, ToolSearch, Write
ok   대조군(제한 없음)은 Bash를 가짐
ok   disallowedTools: Bash(git push *) 에이전트는 Bash 전체가 없음 (AS001 전제 유지)
```
2.1.296에서도 지정자 하나로 Bash만 정확히 빠지고 나머지 도구(Agent 포함)는 그대로다 → AS001·AS002 조합이 현재 버전에서도 맞다. 같은 질문을 따로 2회 더 돌려도 probe-spec 목록이 똑같았다.

실사용: 내 `~/.claude/agents/`(7개)와 `~/.claude/settings.json` → `error 0 · warn 0` (5번 수정 전에는 `guides/tc-guide.md`가 AS000 오탐).

## 6. 한계와 다음 아이디어
- **정적 분석이다.** AS001의 "도구 전체가 사라진다"는 2.1.289(글)와 2.1.296(e2e)에서 확인한 동작이다. Claude Code가 지정자를 지원하게 바뀌면 AS001은 틀린 경고가 된다 — 그래서 `e2e.sh`가 전제가 바뀌면 `NOTE … 전제가 바뀜`을 내고 실패하도록 했다.
- **AS003(`git -C` 우회)은 e2e로 재현하지 않았다.** 실제 푸시가 일어나야 해서 글의 결과를 인용만 했다. 다음에 로컬 bare 원격으로 재현할 수 있다.
- **AS004는 추정이다.** `tools: Bash(npm test *)`가 어떻게 해석되는지 아무도 재지 않았다. 프로브 하나를 더 넣으면 확정할 수 있다.
- 프론트매터 파서는 YAML 부분 집합만 안다(여러 줄 문자열, 앵커 미지원). 필요한 키 두 개만 읽으니 실무엔 충분하다.
- `--agents` CLI 인자로 넘기는 JSON 정의, 플러그인 안의 `agents/` 폴더, managed settings는 아직 안 본다.
- 다음: AS003의 짝인 "git 전역 옵션을 걷어내고 하위 명령을 보는 PreToolUse 훅"을 disaster-guard 패턴에 더해 만들기. 그리고 `docker -H`, `kubectl --context`처럼 전역 옵션이 앞에 오는 다른 CLI로 AS003 확장.

## 7. 출처
- dev.to 10-12, Bash(git push *) in a Claude Code subagent's disallowedTools took away all of Bash in 10 of 10 launches: https://dev.to/rulestack/bashgit-push-in-a-claude-code-subagents-disallowedtools-took-away-all-of-bash-in-10-of-10-4ihj
- Claude Code 서브에이전트 문서: https://code.claude.com/docs/en/sub-agents
- Claude Code 권한 규칙 문서: https://code.claude.com/docs/en/permissions
- Claude Code changelog (2.1.295 서브에이전트 skills 32개 제한, 2.1.296 `autoCompactWindow`): https://code.claude.com/docs/en/changelog

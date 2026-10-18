# hook-exit-audit

## 1. 무엇을 만들었나
CLI 스크립트(`hook_exit_audit.py`, 표준 라이브러리만). `settings.json`(또는 `hooks.json`)의 `PreToolUse` 훅 명령을 위험 명령·정상 명령·깨진 JSON 입력으로 **실제로 실행**해 종료 코드를 표로 찍는다. Claude Code는 훅이 `exit 2`(또는 `permissionDecision: "deny"` JSON)로 끝날 때만 막으므로, "차단 문구를 찍고 `exit 1`", "깨진 입력에서 트레이스백(1)", "`jq` 없음(127)" 같은 fail-open을 찾는다. 스크립트의 정적 신호(`exit 1` 근처 차단 문구, `except` 없는 JSON 파싱, `jq` 분기 없음)와 matcher의 대소문자 오타도 본다.

## 2. 왜 만들었나
dev.to 10-18 [Claude Code Hooks: Exit Code 1 Doesn't Block. 9 of 9 Commands Ran](https://dev.to/ji_ai/claude-code-hooks-exit-code-1-doesnt-block-9-of-9-commands-ran-44h) — 글쓴이의 가드 훅이 "BLOCKED"를 찍고 `exit 1`로 끝나 9건이 전부 실행됐고, 위험 명령 40개 재생에서 `exit 1`은 0개, `exit 2`는 40개를 막았다. 가드를 "만드는" 일은 10-10 disaster-guard 등으로 했지만, 이미 깔아 둔 훅이 **정말 막는지 재는** 도구는 없었다. 우회 20변형은 같은 날 [force-push 22가지 실험](https://dev.to/teefayb/i-tried-22-ways-to-force-push-past-my-teams-claude-code-rules-7-were-hard-blocked-2b5d)에서 가져왔다.

## 3. 어떻게 만들었나
1. 종료 코드 규칙을 코드로 옮겼다: 막음 = `exit 2` 또는 `exit 0` + stdout의 `hookSpecificOutput.permissionDecision == "deny"`(`decision: "block"`도 인정). 나머지 비-0은 전부 "안 막힘".
2. **의도를 모르는 훅에도 틀린 것은 틀렸다고 말하게** 했다. 차단 문구(`block|deny|차단|거부…`)를 내면서 `exit 0/2`가 아니면 `--guard` 없이도 error(HE01). 위험 입력을 막아야 하는지는 `--guard`를 줄 때만 판정한다 — `spend-gate`처럼 명령을 안 보는 훅이 위험 명령을 통과시키는 것은 정상이라서.
3. `onFailure: "block"`이 걸린 훅은 크래시·`exit 1`을 error가 아닌 info로 낮춘다. 이는 dev.to 설정 글(10-18)의 설명("시작 실패·시간 초과·예상 밖 종료에서 막는다")을 가정한 것이며 이 도구가 e2e로 확인한 것은 아니다.
4. 훅은 `sh -c`로 실행하고 `CLAUDE_PROJECT_DIR`을 `--cwd`로 채운다. matcher가 Bash에 안 걸리면(`bash` 오타, `Edit|Write`) Bash 입력으로 돌리지 않고 이유를 적는다. `type: http` 등은 건너뛴다.
5. 막힌 점: 처음엔 각 입력마다 지적을 하나씩 내 출력이 40줄이 됐다 → 종료 코드별로 묶어 한 줄(예: "차단 문구를 내고 exit 1로 끝난 입력 5개")로 합쳤다. 또 없는 스크립트를 가리키는 `python3 no_such.py`는 python이 **exit 2**로 끝나 모든 호출을 막는다는 것을 테스트 중 알게 되어(HE05) HS04 문구에 반영했다.

## 4. 사용법
```bash
# settings.json의 PreToolUse 훅 전부 (인자 없으면 .claude/settings.json, .claude/settings.local.json, ~/.claude/settings.json)
python3 hook_exit_audit.py .claude/settings.json
# 위험 명령을 막는 가드라면 --guard (위험은 2, 정상은 0, 깨진 입력은 2여야 함), 우회 변형 20개까지 보려면 --probes basic,push
python3 hook_exit_audit.py .claude/settings.json --guard --probes basic,push
# 설정 없이 명령 하나만 / 실행하지 않고 정적 점검만 / CI에서 warn도 실패로
python3 hook_exit_audit.py --hook "python3 hooks/guard.py" --guard
python3 hook_exit_audit.py --hook "bash hooks/guard.sh" --no-run
python3 hook_exit_audit.py .claude/settings.json --guard --fail-on warn
```
종료 코드: 0 = 기준 이하, 1 = error(`--fail-on warn`이면 warn 포함), 2 = 입력 오류. `--json`으로 기계가 읽는 출력.

| 코드 | 뜻 |
|---|---|
| HE01 | 차단 문구를 내고 exit 0/2가 아닌 코드로 끝남 (막지 못함) |
| HE02 | 0·2가 아닌 코드로 끝난 입력 (크래시 포함) |
| HE03 | 시간 초과 |
| HE04 | (--guard) 깨진 입력이 막히지 않음 = fail-open |
| HE05 | (--guard) 정상 입력까지 막음 |
| HE06 | (--guard) 위험 입력을 못 막음 |
| HS01~04 | 정적: exit 1 근처 차단 문구 / jq 분기 없음 / except 없음 / 스크립트 파일 없음 |
| HX01~02 | matcher 대소문자·오타·정규식 오류 |

**주의:** 점검 대상 훅 명령은 실제로 실행된다. 입력의 `rm -rf` 같은 문자열은 훅이 읽기만 하고 이 도구가 실행하지 않지만, 훅 자체가 부작용을 일으키면(예: `spend-gate`처럼 상태를 기록) 그대로 일어난다. 모르는 훅은 `--no-run`부터.

## 5. 테스트 결과
`bash test.sh` (키·모델·claude CLI 불필요, 이 환경의 실제 실행):
```
ok   settings_bad: 없는 python 스크립트는 exit 2라 정상 입력까지 막음(HE05)
ok   settings_bad: 훅 3개
ok   settings_good: exit 0
ok   settings_good: http 훅은 건너뜀
ok   settings_good: Edit|Write는 Bash로 돌리지 않음
ok   없는 파일: exit 2
ok   --json: 파싱 가능한 JSON
ok   push 세트 20개 + 기본 아닌 것: good_exit2는 20개 중 일부 놓침
ok   인자 없고 settings도 없으면 안내 후 exit 2
ok   시간 초과: HE03

통과 36 · 실패 0
```
(전체 36개: 정상/`exit 1`/크래시/JSON deny/셸 `jq` 훅 픽스처, settings 픽스처 2개, 옵션·오류 경로)

`exit 1` 훅에 실제로 돌린 출력 (`python3 hook_exit_audit.py --hook "python3 fixtures/bad_exit1.py" --guard`):
```
## --hook · matcher=Bash
   $ python3 fixtures/bad_exit1.py
   위험: 7건 중 막음 0 · 종료 코드 0×2, 1×5
   정상: 4건 중 막음 0 · 종료 코드 0×4
   깨진입력: 4건 중 막음 0 · 종료 코드 0×1, 1×3
   error HS01 bad_exit1.py:8: 차단 문구 근처가 exit 1 — 1은 막지 못한다 (2여야 함)
   warn  HS03 bad_exit1.py: json 파싱이 있는데 except가 없다 — 깨진 입력이면 트레이스백(exit 1)으로 fail-open
   error HE01 차단 문구를 내고 exit 1로 끝난 입력 5개 (예: 'rm -rf build') — 실제로는 막지 못한다
   warn  HE04 깨진 입력 4개가 fail-open (빈 입력→1, 깨진 JSON→1, null→1, tool_input 없음→0) — 가드면 try/except로 감싸 exit 2로 보내야 한다
   warn  HE02 exit 1로 끝난 입력 3개 (예: 깨진입력:빈 입력) — 0도 2도 아니면 막히지 않는다
   error HE06 위험 입력 7개 중 7개를 못 막음: rm -rf build; rm -rf node_modules; git reset --hard; git push --force origin main …

훅 1개 · error 3 · warn 3
```

이 저장소의 기존 훅에 돌려 본 결과 (`${CLAUDE_PROJECT_DIR}/.claude/hooks`를 `hooks/`로 연결한 임시 폴더):
```
## settings.example.json · matcher=Bash
   $ ${CLAUDE_PROJECT_DIR}/.claude/hooks/danger-guard.sh
   위험: 7건 중 막음 5 · 종료 코드 0×2, 2×5
   정상: 4건 중 막음 0 · 종료 코드 0×4
   깨진입력: 4건 중 막음 0 · 종료 코드 0×1, 1×3
   warn  HE04 깨진 입력 1개가 fail-open (tool_input 없음→0) — 가드면 try/except로 감싸 exit 2로 보내야 한다
   info  HE02 exit 1로 끝난 입력 3개 (예: 깨진입력:빈 입력) — 0도 2도 아니면 막히지 않는다 (onFailure:block 가정)
   warn  HE06 위험 입력 7개 중 2개를 못 막음: rm -rf build; rm -rf node_modules

훅 1개 · error 0 · warn 2
```
```
## 2026-10-13-spend-gate/settings.example.json · matcher=*
   $ python3 ${CLAUDE_PROJECT_DIR}/.claude/hooks/spend_gate.py hook
   위험: 7건 중 막음 0 · 종료 코드 0×7
   정상: 4건 중 막음 0 · 종료 코드 0×4
   깨진입력: 4건 중 막음 0 · 종료 코드 0×1, 1×3
   info  HE02 exit 1로 끝난 입력 3개 (예: 깨진입력:빈 입력) — 0도 2도 아니면 막히지 않는다 (onFailure:block 가정)

훅 1개 · error 0 · warn 0
```
- disaster-guard: 위험 7건 중 `rm -rf build`·`rm -rf node_modules`를 통과시키는데, `rules.txt`의 `rm-rf-root` 규칙이 루트·홈·현재 디렉터리·`*`만 막고 `build/`·`node_modules/` 정리는 허용하는 설계라서 도구의 HE06 warn은 이 의도와 어긋난 것이지 훅의 결함이 아니다. 깨진 입력 중 `tool_input 없음`은 exit 0으로 통과(HE04).
- spend-gate: 위험 명령을 안 막는 것은 정상(`--guard` 없이 실행). 깨진 입력에서 exit 1이지만 `onFailure: "block"`이라 info로 분류.

**e2e:** `bash e2e.sh`는 실제 `claude -p`로 `exit 1` 훅은 `rm -rf build`를 못 막고 `exit 2` 훅은 막는지 본다. 이 환경은 로그인이 없어 `SKIP 로그인 없음 (claude -p 가 응답하지 못함)`만 출력됐고(exit 0) **실제 판정은 돌리지 못했다.** CI에서는 e2e 미실행.

## 6. 한계와 다음 아이디어
- "`exit 1`은 막지 못하고 `exit 2`만 막는다"는 이 도구의 전제는 dev.to 글과 Claude Code 훅 문서의 설명에 기댄 것이고, 로그인 없는 환경이라 e2e로 직접 확인하지 못했다. `onFailure: "block"` 하에서 `exit 1`이 막힌다는 해석도 같다.
- Bash 입력(`tool_input.command`)만 만든다. Edit/Write/MCP 훅의 `file_path` 입력은 아직 없다.
- 위험 입력은 고정 목록이다. 훅이 어떤 명령을 막으려는지는 모르므로 `--guard`에서 규칙과 다른 의도(예: 빌드 폴더 삭제 허용)는 warn으로 나온다. 규칙 파일을 읽어 기대값을 만드는 방식이 다음 과제.
- 훅 `timeout` 설정값을 읽어 `--timeout`에 쓰지 않고, 훅을 병렬(동시 12개 제한)로 돌릴 때의 상호작용도 보지 않는다. `jq` 부재는 실제로 PATH에서 빼서 재현하지 않고 정적으로만 짚는다.
- 다음: Edit/Write 입력 세트, PATH에서 `jq`를 뺀 동적 재현, 플러그인 `hooks.json` 자동 탐색.

## 7. 출처
- https://dev.to/ji_ai/claude-code-hooks-exit-code-1-doesnt-block-9-of-9-commands-ran-44h
- https://dev.to/teefayb/i-tried-22-ways-to-force-push-past-my-teams-claude-code-rules-7-were-hard-blocked-2b5d
- https://dev.to/akaranjkar08/claude-code-21293-to-21302-settings-worth-enabling-now-4job (`onFailure: "block"` 설명)
- https://code.claude.com/docs/en/changelog

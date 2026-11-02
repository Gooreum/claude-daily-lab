# hook-manners

## 1. 무엇을 만들었나
CLI 스크립트(`hook_manners.py`, 표준 라이브러리만). `settings.json`의 command 훅을 **관찰용 훅이 지켜야 할 예절** 기준으로 실제 실행해 점검한다: 깨진 입력(빈 입력·깨진 JSON·`null`·배열)에서도 `exit 0`인가, stdout에 아무것도 안 찍는가, 시간 안에 끝나는가, 설정에 `timeout`이 있는가. `Stop`/`SubagentStop` 훅은 `stop_hook_active=true`를 넣어 **또 막는지(루프)** 를 본다. `PreToolUse`·`PermissionRequest`는 막는 것이 일이라 깨진 입력 점검에서 뺀다(그쪽은 `hook-exit-audit`).

## 2. 왜 만들었나
dev.to 11-01 [8 rules for Claude Code hooks that never get in Claude's way](https://dev.to/fxdgif/8-rules-for-claude-code-hooks-that-never-get-in-claudes-way-5ap1) — 이벤트마다 도는 훅 스크립트는 항상 `exit 0`, 자체 데드라인, 의도할 때만 stdout, `Stop` 훅은 `stop_hook_active`가 참이면 다시 막지 않기 같은 규칙을 지켜야 Claude를 방해하지 않는다는 글. 10-19 `hook-exit-audit`은 차단 훅이 정말 막는지만 재고, `stop_hook_active`는 이 저장소 어디에도 없었다. 규칙 8은 위반하면 세션이 끝나지 않고 돌아 한도를 태우는 사고라, 키 없이 재현해 잡는 도구로 만들 가치가 있다고 봤다. (`news/2026-11-02.md` 2번)

## 3. 어떻게 만들었나
1. 글의 규칙 중 **기계가 확인할 수 있는 것**만 골랐다: 규칙 1(exit 0) → HM02, 2(데드라인) → HM01·HM05, 3(stdout) → HM03·HM04, 8(`stop_hook_active`) → HM06·HM07. 규칙 4(PermissionRequest 대기)는 가드 이벤트로 분류해 점검에서 뺐고, 5(윈도 따옴표)·6(의존성)·7(재시작 복구)은 자동 판정이 어려워 넣지 않았다.
2. 훅은 `sh -c`로, 현재 폴더를 프로젝트 폴더로 보고 `CLAUDE_PROJECT_DIR`을 채워 실행한다. 실행마다 새 프로세스 그룹에 넣고 시간 초과면 그룹째 죽인다(자체 데드라인 없는 훅이 자식을 남기지 않게).
3. Stop 훅은 세 가지 입력 변형(기본 / `transcript_path` 비움 / `last_assistant_message` 있음) 각각에 `stop_hook_active`를 참·거짓으로 넣는다. 참인데 `exit 2`이거나 stdout JSON에 `"decision":"block"`이면 HM06(error). 거짓일 때 막는 것은 정상이라 info성으로만 요약에 적는다("비활성 때 막음/안 막음").
4. 정적 점검(HM07)은 스크립트에 `block`이 있는데 `stop_hook_active`가 없으면 warn. 실행으로 못 잡는 분기(예: 변경된 파일이 있을 때만 막는 훅)를 보완한다.
5. 막힌 점: 처음엔 실행 위치를 빈 임시 폴더로 해서 `python3 fixtures/good_stop.py`가 전부 "파일 없음 → exit 2"로 끝났고, 도구가 **모든 훅을 error로 판정**했다. 실제 훅도 프로젝트 폴더에서 돈다는 점에 맞춰 기본 실행 위치를 현재 폴더로 바꿨다. 이때 "없는 스크립트는 `python3`이면 exit 2(모든 호출을 막음), 직접 실행이면 127"이라는 차이를 알게 되어 HM08로 따로 안내한다. 또 픽스처 주석에 `stop_hook_active`라는 글자가 들어 있어 HM07이 안 걸렸다 — 정적 점검은 주석도 본문으로 보는 한계가 있다(6절).
6. 만든 방식: Claude Code로 직접 작성·실행. 모델 호출은 없다.

## 4. 사용법
```bash
# settings.json의 command 훅 전부 (인자 없으면 .claude/settings.json, .claude/settings.local.json, ~/.claude/settings.json)
python3 hook_manners.py .claude/settings.json
# 설정 없이 명령 하나만 (이벤트 지정)
python3 hook_manners.py --event Stop --hook "python3 hooks/stop_note.py"
# 실행하지 않고 설정·정적 점검만 (모르는 훅은 이것부터)
python3 hook_manners.py .claude/settings.json --no-run
# 느림 기준·실행당 제한 시간·CI에서 warn도 실패로
python3 hook_manners.py .claude/settings.json --slow 1 --timeout 3 --fail-on warn
# 기계가 읽는 출력
python3 hook_manners.py .claude/settings.json --json
```
예시 출력(`fixtures/settings_bad.json` 일부):
```
[Stop] python3 fixtures/loop_stop.py  (관찰; 0.02s · 비활성 때 막음)
  error HM06: stop_hook_active=true인데 또 막는다(기본, transcript 없음, 메시지 있음) — Claude가 끝낼 때마다 되돌려 보내지는 루프
  warn  HM01: 설정에 timeout이 없다 — 기본 대기 시간에 기댄다. 짧게(예: 5) 적어 둘 것
```
종료 코드: 0 = 기준 이하, 1 = error(`--fail-on warn`이면 warn 포함), 2 = 입력 오류.

| 코드 | 뜻 |
|---|---|
| HM01 | 설정 `timeout` 없음 / 서두르는 이벤트에 30초 초과 |
| HM02 | 깨진 입력에서 exit 0이 아님(exit 2는 동작을 막고, 그 밖의 비-0은 훅 오류) |
| HM03 | 깨진 입력에서 stdout에 출력 |
| HM04 | 정상 입력에서 stdout이 JSON이 아닌 글자(디버그 출력) |
| HM05 | 제한 시간 안에 안 끝남 / 느림 |
| HM06 | `stop_hook_active=true`인데 Stop 계열 훅이 또 막음(루프) |
| HM07 | (정적) 스크립트가 `block`을 내면서 `stop_hook_active`를 읽지 않음 |
| HM08 | (정적) 훅이 가리키는 스크립트 파일이 없음 |

**주의:** 점검 대상 훅은 실제로 실행된다(훅이 파일을 쓰거나 서버로 보내면 그대로 일어난다). `SessionStart`·`UserPromptSubmit`은 stdout이 컨텍스트로 들어가는 것이 정상이라 stdout 점검(HM03·HM04)에서 뺀다. `type`이 `command`가 아닌 훅은 건너뛴다.

## 5. 테스트 결과
`bash test.sh` (키·모델 없음, 이 폴더에서 실행). 모범 훅 2개·나쁜 훅 5개 픽스처로 코드마다 하나씩 확인한다.
```
$ bash test.sh
ok   good: exit 0
ok   good: 훅 3개 error 0 warn 0
ok   good: PreToolUse 가드는 점검 제외로 표시
ok   good: Stop 훅이 비활성일 때는 막음(정상 동작)으로 보고
ok   bad: exit 1
ok   HM06 stop_hook_active=true인데 또 막음 (loop_stop)
ok   HM02 깨진 입력에서 exit 1 (crash_hook)
ok   HM02 깨진 입력에서 exit 2 (exit2_hook)
ok   HM05 데드라인 없이 멈춤 (slow_hook)
ok   HM01 timeout 없음 / 120초
ok   HM03 깨진 입력에서 stdout 출력 (loop_stop)
ok   HM04 stdout이 JSON 아닌 글자 (crash_hook)
ok   http 훅은 건너뜀 (훅 4개)
ok   HM07 block을 내면서 stop_hook_active를 안 읽음 (--no-run은 warn만 → exit 0)
ok   --fail-on warn이면 exit 1
ok   good_stop은 stop_hook_active를 읽으므로 HM07 없음
ok   HM08 없는 스크립트 (+깨진 입력 exit 2)
ok   HM08 직접 실행하는 없는 스크립트는 exit 127 안내
ok   PreToolUse 훅은 HM02를 내지 않는다
ok   --json이 유효한 JSON 배열
ok   settings가 없으면 exit 2
ok   훅이 없으면 exit 0

통과 22 · 실패 0
```
실제 파일에 돌린 것: 이 저장소의 `days/2026-10-10-disaster-guard/settings.example.json`을 `--no-run`으로 점검하니 `.claude/hooks/*.sh`가 이 폴더에 없다는 HM08 warn 2건만 나왔다(예시 설정이 다른 프로젝트 기준이라 예상된 결과). 이 저장소에는 자체 `.claude/settings.json`이 없어 실제 훅을 **실행**하는 점검은 픽스처로만 했다. 모델 호출이 없어 `e2e.sh`는 없다.

## 6. 한계와 다음 아이디어
- 훅이 받는 실제 입력 필드(이벤트별 전체 스키마)는 문서의 일부만 흉내 냈다. 입력 필드에 따라 분기하는 훅은 정상 입력 점검이 실제와 다른 경로를 탈 수 있다.
- Stop 훅의 막힘 조건이 저장소 상태(예: 변경된 파일 유무)에 달려 있으면 실행 점검이 못 잡는다. 정적 점검 HM07은 주석의 `stop_hook_active`도 읽은 것으로 쳐서 놓칠 수 있다.
- `exit 2`/`decision: block`만 "막음"으로 본다. `hookSpecificOutput` 형식의 다른 결정 필드는 보지 않는다.
- 이 도구의 판정 기준은 글쓴이 한 명의 경험칙이다. "관찰 훅은 항상 exit 0"은 의도적으로 실패를 알리려는 훅(예: `onFailure` 설정을 쓰는 훅)에는 맞지 않을 수 있다.
- 윈도 따옴표(규칙 5), 서버 재시작 뒤 재연결(규칙 7)은 다루지 않는다. 다음 단계로 `--hook-dir`에서 설정 없이 스크립트 모음을 한꺼번에 점검하거나 CI 예시 워크플로를 붙일 수 있다.
- `hook-exit-audit`(10-19)과 한 도구로 합치면 가드/관찰 훅을 한 번에 볼 수 있지만, 폴더 격리 원칙상 복사하지 않고 따로 뒀다.

## 7. 출처
- https://dev.to/fxdgif/8-rules-for-claude-code-hooks-that-never-get-in-claudes-way-5ap1 — 계기가 된 글
- https://code.claude.com/docs/en/hooks — Claude Code 훅 문서
- https://dev.to/ji_ai/claude-code-hooks-exit-code-1-doesnt-block-9-of-9-commands-ran-44h — 차단 훅 종료 코드(`hook-exit-audit`의 계기)
- `news/2026-11-02.md` 2번

# hook-merge

## 1. 무엇을 만들었나

CLI 스크립트(`hook_merge.py`, 표준 라이브러리만). 같은 도구 호출에 걸린 **PreToolUse 훅 여럿의 결정이 어떻게 합쳐지는지** 미리 본다. 설정 파일(`settings.json`·`settings.local.json`·플러그인 `hooks.json`)에서 호출(도구·입력)에 걸리는 훅을 matcher와 `if`로 고르고, `run`이면 command 훅을 **병렬로 실행**해 훅마다 결정(exit 2 = deny, JSON `permissionDecision` = allow·deny·ask·defer)과 끝난 순서를 표로 보여 준 뒤, 문서 우선순위 `deny > defer > ask > allow`로 합친 결과를 **대화형**과 **`claude -p`** 두 경우로 나눠 낸다. `plan`은 훅을 실행하지 않고 어느 훅이 걸리는지만 나열한다.

지적 (ID · 등급):
- `HM01 warn` 훅들의 결정이 갈림 — 우선순위로 하나만 남고 나머지는 결과에 반영되지 않는다
- `HM02 error/warn` `defer`+`ask` 쌍 — Claude Code 2.1.321 미만이면 defer가 먼저 끝날 때 ask가 사라져 확인 창 없이 실행될 수 있음(`--claude-version`이 2.1.321 미만이면 error, 버전 미지정이면 warn)
- `HM03 warn` `defer`는 `claude -p`의 도구 호출 1개일 때만 지켜지고 대화형·병렬 호출에서는 무시됨
- `HM04 warn` `ask`가 둘 이상 — 확인 창에 어느 훅의 사유가 보일지 끝나는 순서에 달릴 수 있음
- `HM05 warn` 훅이 exit 1·타임아웃 등으로 결정 없이 끝남 — 가드라면 fail-open
- `HM06 warn` exit 0인데 stdout이 JSON이 아님 — 결정으로 읽히지 않음

종료 코드: error가 있거나 설정을 못 읽으면 1(`--strict`면 warn도), 아니면 0.

## 2. 왜 만들었나

- 계기: dev.to 11-20 "On Claude Code 2.1.319, one hook's defer erased another hook's ask and the command ran. 2.1.322 shows the prompt" — https://dev.to/rulestack/on-claude-code-21319-one-hooks-defer-erased-another-hooks-ask-and-the-command-ran-21322-2b7p (news/2026-11-20.md 1번). 글쓴이는 지연이 다른 훅 쌍으로 2.1.319에서 defer가 먼저 끝나면 ask가 사라져 명령이 실행되는 것을 재현했고, 2.1.321이 이를 고쳤다.
- "직접 만들어볼 만하다"고 본 이유: 기존 `hook-exit-audit`(종료 코드)·`matcher-lint`(안 맞는 matcher)는 훅을 **하나씩** 본다. 이 저장소에 쌓인 가드 훅은 서로 겹친다 — 아래 5절에서 예제 설정 5개를 합치면 `git commit` 한 번에 훅 5개가 걸린다. "합쳐진 결정"을 보여 주는 도구는 없었다.

## 3. 어떻게 만들었나

1. 훅 문서(https://code.claude.com/docs/en/hooks)와 위 글에서 규칙을 뽑았다: 우선순위 `deny > defer > ask > allow`, exit 2는 deny(stderr가 사유), `defer`는 `claude -p` + 도구 호출 1개에서만 지켜지고 대화형에서는 경고 후 무시, 옛 최상위 `decision: approve|block`은 deprecated.
2. 설계 결정: **훅을 정말 병렬로 돌린다**(스레드 풀). 합치는 규칙만 시뮬레이션하면 "defer가 먼저 끝났나, ask가 먼저 끝났나"를 볼 수 없다. 대신 `run`은 훅 명령을 실제로 실행하므로 믿는 설정에만 쓰고, 안전한 `plan`을 따로 뒀다.
3. 합치기는 두 번 한다. 대화형은 defer를 버리고 합치고, `claude -p`는 defer를 살려 합친다(`--parallel-calls`면 `-p`도 버림). 같은 훅 쌍이 두 모드에서 `ask`와 `defer`로 갈리는 것이 글의 핵심이라 한 줄에 같이 보이게 했다.
4. matcher·`if` 판정은 `matcher-lint`의 규칙(정확 일치 목록 또는 앵커 없는 정규식)을 **복사해** 단순화했다(폴더 밖 import 금지). `if`는 `Bash(git commit*)` 같은 Bash 규칙만 판정하고 `Read(./.env)` 같은 경로 규칙은 "판단 못 함 — 맞을 수 있음"으로 표시한다.
5. 시험용 훅은 `fixtures/hooks/`의 셸 스크립트 10개(결정·지연을 인자로 받는 템플릿에서 생성)로 만들었다. defer(0초)+ask(0.4초) 쌍이 "defer가 먼저 끝나는" 상황을 만든다.
6. 막힌 지점: 실제 `claude -p`로 "합친 결과 예측 = 실제 동작"을 대조하는 `e2e.sh`는 이 환경에 로그인이 없어 돌지 못했다(5절). 판정 불가를 "불일치"로 오인하지 않도록 e2e는 로그인 오류를 exit 3(미실행)으로 구분한다.

## 4. 사용법

```bash
cd days/2026-11-20-hook-merge
# 실행 없이: 이 호출에 어떤 훅이 걸리나 (설정 여러 개를 한꺼번에 넣으면 합산)
python3 hook_merge.py plan .claude/settings.json ~/.claude/settings.json --command 'git commit -m x'
# 실제 실행: 병렬로 돌리고 결정을 합친다 (믿는 설정에만)
python3 hook_merge.py run .claude/settings.json --command 'rm -rf build' --project-dir .
python3 hook_merge.py run .claude/settings.json --tool Write --input '{"file_path":"a.txt","content":"x"}'
python3 hook_merge.py run .claude/settings.json --claude-version "$(claude --version)"   # HM02 판정
python3 hook_merge.py run .claude/settings.json --strict --json                            # CI
```

예시 출력(`fixtures/defer_ask.json`: defer 훅(0초)+ask 훅(0.4초), 버전 2.1.319):

```
hook-merge run — Bash `echo hi` · 설정 1개 · PreToolUse 훅 2개 중 2개가 걸린다
  끝난 순   결정         초  훅
  1      defer   0.01  defer_ask.json[Bash] ./fixtures/hooks/defer_fast.sh  사유: defer-fast
  2      ask     0.41  defer_ask.json[Bash] ./fixtures/hooks/ask_slow.sh  사유: ask-slow
  합친 결과: 대화형 → ask (defer 무시) · claude -p → defer
  warn  HM01  훅들의 결정이 갈린다(defer×1, ask×1) — 우선순위 deny>defer>ask>allow 로 defer 하나로 합쳐진다. 진 결정은 결과에 반영되지 않는다
  error HM02  defer+ask 쌍(defer가 먼저 끝남) + Claude Code 2.1.319 < 2.1.321: defer가 먼저 끝나면 ask가 사라져 확인 창 없이 명령이 실행될 수 있다 — 올리거나 defer를 빼라
  warn  HM03  defer는 `claude -p`에서 도구 호출이 하나일 때만 지켜진다. 대화형 세션과 한 턴에 도구 호출이 여럿인 경우에는 경고만 남기고 무시돼 보통 권한 흐름으로 간다
  요약: error 1 · warn 2
```

모델·키가 필요 없어 dry-run이 따로 없다(`plan`이 훅을 실행하지 않는 모드다).

## 5. 테스트 결과

`bash test.sh` (키·모델 없음, 가짜 훅 스크립트를 실제로 실행):

```
ok   defer+ask: exit 0 (버전 미지정은 warn)
ok   defer+ask: 훅 2개가 걸림
ok   defer+ask: defer가 1등으로 끝남
ok   defer+ask: 대화형 → ask (defer 무시)
ok   defer+ask: claude -p → defer
ok   defer+ask: HM01 갈림
ok   defer+ask: HM02 버전 미지정 warn
ok   defer+ask: HM03 defer 무시 경고
ok   2.1.319: exit 1
ok   2.1.319: HM02 error
ok   2.1.322(문장에서 추출): exit 0
ok   2.1.322: HM02 없음
ok   병렬 호출: claude -p → ask (defer 무시)
ok   ask×2+allow: 합침 ask
ok   ask×2+allow: HM04
ok   deny 승리: 합침 deny
ok   deny 승리: exit 2 사유 no-rm-rf
ok   deny 승리: 훅 3개(그룹 둘)
ok   Read 호출엔 .* 그룹의 deny 하나만
ok   조용+allow: 합침 allow, 지적 없음
ok   crash: HM05 fail-open 경고
ok   junk: HM06
ok   옛 decision:approve → allow, deprecated 표시
ok   plan: if 맞는 훅 1개만 걸림
ok   plan: if 안 맞는 훅은 제외
ok   plan: http 훅은 제외(실행 안 함)
ok   plan: 합친 결과 줄 없음(실행 안 함)
ok   plan: 판단 못 하는 if는 맞을 수 있음으로 표시
ok   없는 설정: exit 1 + 읽을 수 없다
ok   --json: merged.interactive == deny
ok   --strict: warn만 있어도 exit 1
ok   걸리는 훅 없음: exit 0
ok   plugin hooks.json 읽기
ok   페이로드 stdin 소비 후 정상 종료(rc 0)

통과 34 · 실패 0
```

**실제 설정으로 한 점검** — 이 저장소 이전 날짜 폴더의 예제 설정 5개(`disaster-guard`·`onfailure-secret-guard`·`spend-gate`·`session-bulkhead`·`read-guard`의 `settings.example.json`)를 한꺼번에 `plan`에 넣었다. 한 사람이 이 가드들을 전부 켜면 `git commit` 한 번에 훅 5개가 병렬로 걸린다는 뜻이다:

```
$ python3 hook_merge.py plan <예제 설정 5개> --command 'git commit -m x' --project-dir .
hook-merge plan — Bash `git commit -m x` · 설정 5개 · PreToolUse 훅 5개 중 5개가 걸린다
  걸림  settings.example.json[Bash] …CLAUDE_PROJECT_DIR}/.claude/hooks/danger-guard.sh
  걸림  settings.example.json[Write|Edit|Bash] …CLAUDE_PROJECT_DIR}/.claude/hooks/secret-guard.sh
  걸림  settings.example.json[*] …UDE_PROJECT_DIR}/.claude/hooks/spend_gate.py hook
  걸림  settings.example.json[Bash] $HOME/.claude/hooks/session_bulkhead.py hook
  걸림  settings.example.json[Read|Bash] ${CLAUDE_PROJECT_DIR}/.claude/hooks/read_guard.py
```

(이 폴더에서는 `plan`만 돌렸다. 그 가드들의 합쳐진 결정은 각 훅 스크립트가 이 폴더에 없어 `run`으로 돌리지 않았다.)

**e2e** (`bash e2e.sh`, 실제 `claude -p`로 "deny가 allow를 이긴다"·"allow만 있으면 실행된다" 예측을 대조) — **이 환경에서 못 돌렸다**:

```
$ bash e2e.sh
e2e 미실행(case=deny): Not logged in · Please run /login
rc=3
```

따라서 "합친 결과가 실제 Claude Code의 동작과 같다"는 이 환경에서는 **검증하지 못했다.** 합치는 규칙은 훅 문서와 dev.to 글의 표(print 모드 우선순위 표)에 맞춘 것이다.

## 6. 한계와 다음 아이디어

- 합친 결과는 문서 규칙의 **시뮬레이션**이다. 2.1.319의 "ask가 사라지는" 버그 자체는 재현하지 않는다(규칙대로 합치면 대화형은 ask). 그 버그가 날 수 있는 *조건*(defer+ask 쌍, 버전 < 2.1.321)을 HM02로 알릴 뿐이다.
- command 훅만 실행한다. `http`·`prompt`·`agent`·`mcp_tool` 훅은 "제외"로만 표시한다. 훅의 `updatedInput`(입력 고치기)이 여럿일 때의 합산, `continue:false`(전체 중단)는 다루지 않는다.
- `if`는 Bash 규칙만 판정하고, Bash 규칙의 복합 명령·`git -C` 같은 변형은 단순 글로브로 근사한다.
- 훅 `timeout`은 `--max-wait`(기본 30초)로 줄여 기다린다. 훅이 외부 서비스를 부르면 `run` 중에 실제 호출이 일어난다.
- 다음: 로그인 되는 환경에서 `e2e.sh`를 돌려 예측-실제 대조를 채운다. 사용자·프로젝트·로컬·관리형 설정을 우선순위대로 합쳐 읽는 `--user`/`--managed`를 더한다(`sandbox-lint`의 합치기 방식 참고). 모든 PreToolUse 훅 쌍의 충돌 가능성을 호출 샘플 목록으로 한꺼번에 훑는 `matrix` 모드.

## 7. 출처

- https://dev.to/rulestack/on-claude-code-21319-one-hooks-defer-erased-another-hooks-ask-and-the-command-ran-21322-2b7p
- https://code.claude.com/docs/en/hooks
- https://github.com/anthropics/claude-code/releases/tag/v2.1.329
- https://github.com/anthropics/anthropic-sdk-python/releases/tag/v2.11.0
- news/2026-11-20.md (이 저장소)

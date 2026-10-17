# mod-audit — Claude Code 모드(mod)를 설치하기 전에 정적으로 훑는 점검기

## 1. 무엇을 만들었나
CLI 스크립트(`mod_audit.py`, Python 표준 라이브러리만) 하나다. 플러그인 폴더(또는 플러그인 여러 개가 든 폴더)를 읽어 `hooks/hooks.json`의 `modules`가 가리키는 JS/TS에서 **처리하는 훅 이벤트**와 **쓰는 `$.` API**를 뽑고, 번들 MCP 서버의 실행 명령까지 보아 위험 신호를 짚는다. 프로세스 실행, 비밀을 읽는 호출 + 네트워크 전송 조합, `.catch` 없는 게이트 훅, 버전을 고정하지 않은 `npx` MCP 서버, 원격 import·`eval`이 대상이다. `claude` CLI도 모델도 필요 없어 CI에서 그대로 돈다.

## 2. 왜 만들었나
2026-10-17 dev.to 글 [Claude Code Mods Run Unsandboxed With Your Permissions](https://dev.to/gabrielanhaia/claude-code-mods-run-unsandboxed-with-your-permissions-plugin-install-is-npm-install-now-2c3m)는 모드가 샌드박스 밖에서 내 권한으로 돌고, 모드의 승인이 내 deny 규칙과 `PreToolUse` 훅을 덮을 수 있다고 짚는다. 설치 전에 `claude plugin validate`의 `hooks:`·`calls:` 두 줄을 모드가 주장하는 기능과 대조하라는 권고가 핵심인데, 대조 자체는 사람 눈에 맡겨져 있다. 같은 글의 댓글은 태그 고정이 `npx -y 패키지`로 받는 MCP 서버까지는 얼리지 못한다고 지적했고, 자매 글 [작업 폴더 밖 편집을 막는 모드 30줄](https://dev.to/gabrielanhaia/your-first-claude-code-mod-block-edits-outside-the-tasks-worktree-in-30-lines-6k)은 훅이 던지면 건너뛰어지므로 `.catch`가 필요하다고 한다. 이 대조와 두 가지 함정을 기계가 하게 만들면 "허용 목록"과 "이전 버전 대비"로 CI에 넣을 수 있다고 판단했다.

## 3. 어떻게 만들었나
1. **입력 읽기**: `claude plugin validate`가 실제로 찍는 형식(`hooks:`, `calls:`)을 이 저장소의 turn-notify 모드로 확인해, 같은 두 목록(이벤트·`$.` 호출)을 정적으로 뽑는 것을 기준으로 삼았다.
2. **주석 제거**: 주석에 적힌 `$.process.run`을 세면 오탐이라, 문자열 안의 `//`(`https://…`)는 남기고 주석만 공백으로 바꾸는 작은 상태 기계를 썼다. 줄 번호가 유지된다.
3. **import 따라가기**: 훅 모듈이 상대 경로로 부르는 파일도 읽는다. 처음엔 `./format.mjs`만 풀었는데, 이 저장소의 selection-lens를 돌려 보니 `./lens`·`../types`처럼 확장자 없는 import(TS)가 "읽을 수 없음"으로 나와 `.ts/.tsx/.js/.mjs/.d.ts`와 `index.*`를 순서대로 시도하게 고쳤다.
4. **등급 설계**: 프로세스 실행(`MA01`)과 "비밀 읽기 + 네트워크 전송" 조합(`MA02`)은 error, 단독 `$.http.fetch`·`$.env.get`·`$.model.complete`, `tool.check`(사용자에게 묻기 전 승인 가능), `.catch` 없는 게이트 훅은 warn으로 뒀다. 게이트 훅이 던질 때 가드가 열린다는 점(`MA06`)은 두 번째 글의 설명을 따랐다. `catch`의 유무는 모듈 파일 단위의 휴리스틱이다.
5. **CI용 두 옵션**: `--allow`(허용할 `$.` 호출 목록, 밖의 호출은 error)와 `--baseline`(이전 `--json` 보고서에 없던 호출·훅 이벤트는 error)을 넣었다. 패치 버전 하나에 `$.http.fetch`가 슬쩍 추가되는 경우를 PR에서 막는 용도다.
6. **MCP 서버**: `plugin.json`의 `mcpServers`와 플러그인 루트 `.mcp.json`을 읽어 `npx`·`bunx`·`uvx`·`pipx`·`pnpm dlx`로 띄우는 패키지가 정확한 버전(`@1.2.3`, `==1.2.3`)인지 본다. `@latest`는 error, 미고정은 warn으로 고친 형태를 제안한다.

## 4. 사용법
```bash
python3 mod_audit.py <플러그인 폴더 또는 그 상위 폴더>
python3 mod_audit.py --strict ./some-mod                # warn도 실패로
python3 mod_audit.py --allow '$.ui.*,$.command.register' ./some-mod   # 목록 밖 호출은 error
python3 mod_audit.py --json ./some-mod > v1.json        # 이번 버전의 지문 저장
python3 mod_audit.py --baseline v1.json ./some-mod-v2   # v1에 없던 호출·이벤트는 error
```
종료 코드: 0=error 없음, 1=error 있음(`--strict`면 warn 포함), 2=사용 오류. 코드: MA01 프로세스 실행 · MA02 네트워크(비밀+전송 조합은 error) · MA03 환경/설정 읽기 · MA04 모델 호출 · MA05 `tool.check` · MA06 `.catch` 없는 게이트 훅 · MA07 MCP 서버 버전 미고정 · MA08 eval/동적·원격 import/폴더 밖 모듈 · MA09 모듈 파일 읽기 실패 · MA10 `--allow`·`--baseline` 위반.

예시(나쁜 픽스처, 일부):
```
== weather-pro 1.0.2 — 모드
  훅 이벤트: prompt.submit, tool.check
  $. 호출:   $.env.get, $.http.fetch, $.process.run
  .mcp: error MA07 MCP 서버 'weather': `npx -y weather-mcp@latest` — @latest는 세션 시작마다 새 코드를 받아 실행한다
  hooks/register.js:4: error MA02 비밀을 읽는 호출($.env.get/$.settings.read)과 네트워크 전송($.http.fetch)이 한 모드에 같이 있다 — 유출 경로가 된다
  hooks/register.js:5: error MA01 $.process.run — 프로세스를 띄운다. 샌드박스 밖에서 내 계정 권한으로 돈다
```

## 5. 테스트 결과
`bash test.sh` (픽스처 폴더 5개, `claude` CLI·키·모델 불필요):
```
ok   good: exit 0
ok   good: 훅 이벤트 session.start, turn.complete 추출
ok   good: 호출 $.command.register, $.ui.notify 추출
ok   good: 주석 속 $.process.run은 세지 않음
ok   good: import한 format.mjs까지 따라가 읽음 (지적 0)
ok   guard: exit 0, MA06 없음
ok   guard에서 .catch를 빼면 MA06 warn
ok   bad: exit 1
ok   MA01: $.process.run은 error
ok   MA02: env.get + http.fetch 조합은 error (fetch 줄)
ok   MA02: http.fetch 단독 지적은 warn
ok   MA03: env.get warn
ok   MA05: tool.check는 승인 가능 warn
ok   MA06: tool.check·prompt.submit에 catch 없음 2건
ok   MA07: plugin.json의 @latest는 error
ok   MA07: .mcp.json의 버전 없는 npx는 warn + 고친 형태 제안
ok   MA07: uvx는 == 형태로 제안
ok   MA07: 버전 고정된 npx·node 로컬은 지적 없음
ok   MA08: 원격 URL 동적 import error
ok   MA08: eval warn, 상수 아닌 import warn
ok   MA08: 플러그인 폴더 밖 모듈 경로 error
ok   ts: 확장자 없는 ./lens(.ts)까지 읽어 $.model.complete 추출
ok   ts: ../types(index.d.ts)는 읽기 불가 경고 없음
ok   --strict: warn 0이면 통과
ok   warn만 있으면 기본 exit 0
ok   --strict: warn만 있어도 exit 1
ok   --allow: 허용 범위 안이면 통과 (와일드카드)
ok   --allow: 목록 밖 $.ui.notify는 MA10 error
ok   --json: 파싱 가능, calls·events 포함
ok   --baseline: 같은 버전이면 통과
ok   --baseline: 새 호출 $.process.run을 MA10으로 잡음
ok   --baseline: 새 훅 이벤트 tool.check도 잡음
ok   tree: 플러그인 2개를 모두 찾음
ok   tree: modules 없는 플러그인은 '모드 아님'
ok   tree: runner의 $.process.spawn error → exit 1
ok   없는 폴더는 exit 2
ok   plugin.json 없는 폴더는 exit 2

통과 37 · 실패 0
```
이 저장소의 기존 모드에 실제로 돌려 본 결과(`claude plugin validate`의 `hooks:`/`calls:`와 같은 목록이 나온다):
```
$ python3 mod_audit.py ../2026-10-10-turn-notify-mod/turn-notify
== turn-notify 0.1.0 — 모드
  훅 이벤트: command.run, session.start, turn.complete
  $. 호출:   $.command.register, $.ui.notify
요약: error 0 · warn 0 · 플러그인 1개
$ python3 mod_audit.py ../2026-10-10-selection-lens
== selection-lens 0.1.0 — 모드
  훅 이벤트: command.run, session.start, ui.render
  $. 호출:   $.clock.now, $.command.register, $.model.complete, $.ui.open, $.ui.resolve, $.ui.selection
  hooks/register.tsx:15: warn MA04 $.model.complete — 모델을 호출한다. 대화 내용이 나가고 토큰이 든다
요약: error 0 · warn 1 · 플러그인 1개
```
selection-lens의 `$.model.complete` 경고는 의도한 동작(선택한 코드를 설명하려고 모델을 부름)이라 정상이다. e2e는 모델이 필요 없어 두지 않았다.

## 6. 한계와 다음 아이디어
- 정규식 기반 정적 분석이라 `const f = $.process; f.run()`처럼 별칭을 거치거나 문자열로 조립한 호출은 못 잡는다. 이름을 숨기려는 악의적 모드를 막는 도구가 아니라, 정직한 모드가 무엇을 하는지 설치 전에 한눈에 보게 하는 도구다.
- `.catch` 검사는 파일에 `catch`가 하나라도 있으면 통과시키는 거친 휴리스틱이다. 어느 훅에 걸린 것인지는 따지지 않는다.
- `$.` 호출 목록은 dev.to 글과 `claude plugin validate`의 출력에서 본 이름 몇 개(`process.run`·`http.fetch`·`env.get`·`settings.read`·`model.complete`)만 위험으로 분류했다. 문서에 없는 호출 이름은 지적 없이 목록에만 나온다.
- 번들 MCP 서버는 `command`가 런처(`npx` 등)인 경우만 본다. 플러그인이 내려받아 실행하는 다른 스크립트, `hooks.json`의 일반 셸 훅은 보지 않는다.
- 다음 아이디어: `claude plugin validate --json` 출력과 합쳐 매니페스트 오류와 위험 신호를 한 보고서로 내기, 마켓플레이스 저장소 전체를 돌려 플러그인별 위험 표 만들기, 허용 목록을 `.claude/mod-audit.allow`로 저장소에 커밋하기.

## 7. 출처
- https://dev.to/gabrielanhaia/claude-code-mods-run-unsandboxed-with-your-permissions-plugin-install-is-npm-install-now-2c3m
- https://dev.to/gabrielanhaia/your-first-claude-code-mod-block-edits-outside-the-tasks-worktree-in-30-lines-6k
- https://code.claude.com/docs/en/changelog (모드 도입: 2.1.287)
- https://github.com/anthropics/claude-cookbooks/commit/a162e0184e71b60290808a43961a6cbc8060123c (같은 날 수집한 에이전트 보안 검토 쿡북, 다음 주제 후보)

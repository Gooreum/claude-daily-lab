# matcher-lint

## 1. 무엇을 만들었나

CLI 스크립트(`matcher_lint.py`, 표준 라이브러리만). 훅 설정 파일(`.claude/settings.json`·`settings.local.json`·플러그인 `hooks/hooks.json`)의 `matcher`를 Claude Code 문서의 평가 규칙대로 읽어 **절대 안 맞는 것**을 찾는다. 훅은 실행하지 않고 읽기만 한다.

잡는 것 (ID · 등급):
- `ML01 error` 도구 이름이 정확히 일치하지 않음(`bash`는 `Bash`가 아니다), `mcp__서버`는 정확 일치라 어떤 MCP 도구와도 안 맞음(→ `mcp__서버__.*`). `Task`·`MultiEdit`처럼 지금 도구 목록에 없는 옛 이름은 warn
- `ML02 error` 정규식으로 해석되지 않거나(`*.ts`) 어떤 도구 이름에도 안 맞는 정규식
- `ML04 error` `Bash(git commit*)`처럼 인자 조건을 matcher에 씀(→ matcher는 `Bash`, 조건은 핸들러의 `if`)
- `ML07 error` 핸들러 `if`의 도구와 matcher가 겹치지 않아 훅이 한 번도 안 돎, `if` 안의 도구 이름 오타
- `ML00 error` matcher가 문자열이 아님 · `ML90 error` 설정 파일을 못 읽음
- `ML03 warn` matcher를 지원하지 않는 이벤트(`UserPromptSubmit`·`Stop` 등)에 matcher를 씀 → 조용히 무시되어 매번 실행됨
- `ML05 warn` `SessionStart`·`Notification`·`StopFailure` 같은 값 목록이 닫힌 이벤트에서 목록에 없는 값(대소문자 포함)
- `ML06 warn` 앵커 없는 정규식 `Edit.*`가 `NotebookEdit`도 잡음

종료 코드: error가 있으면 1(`--strict`면 warn도), 없으면 0. `--json`, `--extra-tool NAME`(사내 도구 이름 추가), `--user`(`~/.claude/settings*.json`도 점검).

## 2. 왜 만들었나

- 계기: Claude Code v2.1.327(11-17) — https://github.com/anthropics/claude-code/releases/tag/v2.1.327 . 이 버전부터 `/status`가 깨진 스킬·에이전트 파일, 무시된 권한 설정과 함께 "절대 맞지 않는 훅 matcher"를 목록으로 보여 준다. (news/2026-11-19.md 1번)
- "직접 만들어볼 만하다"고 본 이유: `/status`는 세션 안에서 사람이 열어야 보인다. CI·PR에서 자동으로 걸러 낼 수단이 없고, 이 저장소처럼 훅 가드(`verify-gate`, `read-guard` 등)가 쌓일수록 matcher 오타 하나로 가드가 조용히 꺼진다. 기존 `hook-exit-audit`·`hook-manners`는 훅이 "돈 뒤"의 동작을 보고, "아예 안 도는" 훅은 못 본다.

## 3. 어떻게 만들었나

1. 훅 문서(https://code.claude.com/docs/en/hooks)의 "Matcher patterns" 절을 받아 평가 규칙을 표로 옮겼다. 핵심은 "글자·숫자·`_`·`-`·공백·`,`·`|`만 있으면 정확 일치, 그 밖의 문자가 하나라도 있으면 앵커 없는 JS 정규식", `FileChanged`·`StopFailure`는 정확 일치 문자 집합이 더 좁다는 것. 이 판별이 `matcher_lint.py`의 중심이다.
2. 도구 이름은 도구 참조 문서(https://code.claude.com/docs/en/tools-reference)의 표에서 뽑아 `TOOLS`로 박았다(2026-11-19 확인). 도구가 늘면 `--extra-tool`로 더하거나 목록을 고친다.
3. 정규식 경로는 파이썬 `re`로 컴파일하고(이름 붙은 그룹 `(?<n>…)`만 보정), 알려진 도구 이름 전체에 `search`해서 "아무것도 안 맞음"과 "앵커 없어 더 잡음"을 판정한다.
4. 값 목록이 닫힌 이벤트(`SessionStart` 등)는 새 버전이 값을 늘릴 수 있어 error가 아니라 warn으로만 알린다. 도구 이름은 error, 옛 이름(`Task`→`Agent`, `MultiEdit`→`Edit`)은 warn — 처음엔 `MultiEdit`을 error로 냈다가, 이전 날짜 폴더(`2026-10-10-disaster-guard`)의 실제 설정에 걸려 "옛 버전용일 수 있다"고 보고 warn으로 낮췄다.
5. `Bash`와 `Monitor`는 같은 규칙 묶음이라 `if`와 matcher 겹침 판정에서 한 쌍으로 취급한다(도구 참조의 "Bash, Monitor" 행).
6. 막힌 지점: 실제 Claude Code가 matcher를 건너뛰는지 확인하는 `e2e.sh`는 이 환경에 로그인이 없어 돌지 못했다(5절). 대신 `claude doctor`(v2.1.328)를 설정 파일에 돌려 비교했다.

## 4. 사용법

```bash
cd days/2026-11-19-matcher-lint
python3 matcher_lint.py .                       # 폴더: .claude/settings*.json, hooks/hooks.json을 찾는다
python3 matcher_lint.py .claude/settings.json   # 파일 직접
python3 matcher_lint.py --user                  # ~/.claude/settings*.json까지
python3 matcher_lint.py --strict .              # warn도 실패로 (CI)
python3 matcher_lint.py --json . | jq .errors
python3 matcher_lint.py --extra-tool MyTool .   # 사내 도구 이름 허용
```

예시 출력(`fixtures/bad.json` 일부):

```
error ML01: fixtures/bad.json PreToolUse[0] matcher='bash'
      "bash"는 도구 이름과 정확히 일치하지 않는다 — 대소문자를 구분한다. "Bash"를 뜻했다면 그렇게 쓴다
error ML04: fixtures/bad.json PreToolUse[3] matcher='Bash(git commit*)'
      matcher는 도구 이름만 거른다. 인자 조건은 핸들러의 if에 쓴다 — matcher "Bash", if "Bash(git commit*)"
warn  ML06: fixtures/bad.json PreToolUse[5] matcher='Edit.*'
      앵커가 없어 NotebookEdit도 맞는다 — 한 도구만 뜻했다면 ^…$ 로 감싼다
파일 1개 · matcher 그룹 15개 · error 9 · warn 6
```

CI 한 줄: `python3 days/2026-11-19-matcher-lint/matcher_lint.py --strict .` (이 도구는 `fixtures/`·`node_modules`·`.git` 폴더를 건너뛴다). 모델·키가 필요 없어 dry-run이 따로 없다.

## 5. 테스트 결과

`bash test.sh` (키·모델 없음):

```
ok   good: exit 0
ok   good: 그룹 11개 · error 0 · warn 0
ok   bad: exit 1
ok   ML01 대소문자 bash → Bash
…(중략: 규칙마다 1건씩 확인)…
ok   요약: error 9 · warn 6
ok   mcp: plugin 범위·와일드카드는 통과, mcp__brave-search 만 error 1
ok   warn만: exit 0
ok   --strict: warn도 exit 1
ok   폴더 지정: .claude/settings.json 발견 (파일 1개)
ok   깨진 JSON: ML90 error 후에도 계속, exit 1
ok   --json: 파싱되고 errors 9
ok   알 수 없는 도구 MyTool 은 error
ok   --extra-tool MyTool 이면 통과
ok   설정 파일이 없으면 exit 0
ok   훅 명령을 실행하지 않는다
---
통과 28 · 실패 0
```

**실제 설정으로 한 점검** — 이 저장소 이전 날짜 폴더의 훅 설정 9개(matcher 그룹 21개):

```
$ python3 matcher_lint.py $(grep -rlE '"hooks"' ../*/ --include=*.json | grep -v 2026-11-19)
error ML01: ../2026-10-10-disaster-guard/settings.example.json PostToolUse[0] matcher='Write|Edit|MultiEdit'   (이 때는 error 등급이었고, 지금은 옛 이름 warn)
error ML01: ../2026-10-19-hook-exit-audit/fixtures/settings_bad.json PreToolUse[0] matcher='bash'              (일부러 나쁘게 만든 픽스처)
파일 9개 · matcher 그룹 21개 · error 2 · warn 0
```

`disaster-guard`의 예시 설정이 `MultiEdit`을 쓰는데 지금 도구 목록에는 없다(옛 버전 도구일 수 있음). 이전 날짜 폴더는 건드리지 않았다.

**`claude doctor`와 비교** (Claude Code 2.1.328, 로그인 없이): 같은 나쁜 설정에서 matcher가 *배열*이면 `claude doctor`가 `Invalid hook matcher … expected string, received array`로 잡는다(→ `ML00`과 같은 결론). 그러나 문자열 matcher만 남긴 14그룹(`bash`, `mcp__memory`, `Bash(git commit*)`, `Startup` 등)은 `claude doctor` 출력에 지적이 **0건**이었고, `matcher-lint`는 error 8 · warn 6을 냈다. `/status`의 "never match" 목록은 세션 안에서만 볼 수 있어 확인하지 못했다.

`bash e2e.sh` (실제 `claude -p`로 "죽었다고 한 훅이 정말 안 도는지" 마커 파일로 확인):

```
== claude -p 실행 (Bash 도구로 echo 한 번)
{"…","terminal_reason":"api_error",…"result":"Not logged in · Please run /login",…}
SKIP: claude가 로그인돼 있지 않다(모델 호출 불가). 마커 검사는 건너뛴다
```

즉 **e2e는 이 환경에서 실행되지 못했다.** 마커 검사 4개(실제 Bash 호출은 마커가 생기고, 소문자 `bash`·`Bash(echo *)`·겹치지 않는 `if` 훅은 안 생겨야 함)는 로그인된 환경에서 `bash e2e.sh`로 돌려야 확인된다. CI에서는 e2e 미실행.

## 6. 한계와 다음 아이디어

- 규칙은 문서를 읽고 옮긴 것이다. 실제 Claude Code가 그렇게 평가하는지는 e2e(로그인 필요)로만 확인할 수 있고 이번엔 못 했다. `claude doctor` 비교는 "doctor가 못 잡는다"까지만 보인다.
- 도구 이름 목록은 2026-11-19 문서 기준 고정값이다. 새 도구가 생기면 오탐(error)이 난다 → `--extra-tool`로 우회, 장기적으로는 `/status` 목록이나 도구 참조 페이지에서 갱신.
- 정규식은 JS가 아니라 파이썬 `re`로 평가한다. 룩비하인드·유니코드 속성 같은 문법 차이는 놓친다.
- 스킬·에이전트 frontmatter의 `hooks:`(YAML)와 `mcp_tool` 훅의 서버·도구 이름 검증은 보지 않는다.
- 플러그인이 번들한 MCP 서버의 matcher는 `mcp__plugin_<플러그인>_<서버>__.*` 꼴이어야 하지만 서버 이름을 알 수 없어 맞는지 확인하지 못한다(정규식이면 통과시킨다).
- 다음 아이디어: `/status`의 "never match" 출력을 `claude -p`로 뽑을 수 있게 되면 이 도구와 교차 검증, pre-commit 훅으로 묶기, 지적마다 자동 수정 제안(`--fix`).

## 7. 출처

- https://github.com/anthropics/claude-code/releases/tag/v2.1.327 — `/status`의 깨진 파일·"never match" 훅 matcher 목록, `.mcp.json` 키 삭제 수정
- https://code.claude.com/docs/en/hooks — "Matcher patterns", 이벤트별 matcher 값, `if` 필드
- https://code.claude.com/docs/en/tools-reference — 도구 이름 표
- https://dev.to/raxxostudios/claude-code-21327-fixes-a-bug-that-deleted-env-files-in-worktrees-5787 — v2.1.327 해설(worktree `.env` 삭제 수정)
- 이 저장소 `news/2026-11-19.md` 1번 항목

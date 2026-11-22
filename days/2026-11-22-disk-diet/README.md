# disk-diet

## 1. 무엇을 만들었나
CLI 스크립트(`disk_diet.py`, 표준 라이브러리만). Claude Code가 로컬에 쌓는 것 — `~/.claude/projects`의 대화 기록(`*.jsonl`), `~/.claude/worktrees`의 worktree 복제본, `~/.local/share/claude/versions`의 옛 실행 파일 — 을 **읽기 전용**으로 재서 표로 보여 주고, 세션마다 base64 이미지가 차지하는 몫과 "오래 안 쓴 worktree·옛 버전" 후보를 뽑는다.
하위 명령은 셋이다. `audit`(표·`--json`·`--oneline`·`--budget-mb`), `plan`(정리 명령을 **출력만** 한다), `slim`(base64 이미지를 뺀 사본을 **새 파일**로 쓴다). 이 도구는 어떤 파일도 지우거나 고치지 않는다.

## 2. 왜 만들었나
- 소식: dev.to 11-22 CleanBit — "AI 코딩 에이전트는 대화 기록·옛 바이너리·worktree 복제본·모델 가중치 네 군데에서 디스크를 먹는다" (https://dev.to/fastlog/claude-code-cursor-and-codex-eating-disk-space-on-your-mac-heres-where-it-goes-51a7). `news/2026-11-22.md` 1번.
- 글이 든 사례는 `~/.claude/projects` 11GB, 스크린샷이 박힌 세션 하나 262MB, 에이전트 worktree가 키운 작업 공간 95GB다. 글은 자기 앱 홍보를 겸하므로 숫자는 한 사람의 측정으로만 읽었다.
- "직접 만들어볼 만하다"고 본 이유: 글이 권하는 것이 "지우기 전에 읽기 전용으로 먼저 재라"인데, 설정·인증 토큰·프로젝트 메모리가 지울 캐시와 같은 폴더에 섞여 있어 `du` 한 줄로는 어디까지가 안전한지 알 수 없다. 이 저장소의 결과물은 비용·권한·훅 쪽이었고 로컬 디스크는 비어 있었다.

## 3. 어떻게 만들었나
1. **측정과 삭제를 분리**: `audit`·`plan`은 읽기만 한다. 지우는 일은 `rm -rf -- '<경로>'` 줄을 출력만 하고 사람이 실행한다. 설정·인증·`CLAUDE.md`·프로젝트 `memory/`는 크기 합계에는 들어가지만 후보 목록·plan에는 절대 올리지 않는다(테스트로 고정).
2. **이미지 세기**: 세션 파일을 줄 단위로 읽고, `"base64"`가 든 줄만 JSON으로 파싱해 `type: image` · `source.type: base64` 블록을 재귀로 찾는다. 사용자 메시지 바로 아래뿐 아니라 `tool_result` 안에 중첩된 이미지도 센다. 이미지 표시는 있는데 JSON이 깨진 줄(잘린 기록)은 세지 않고 `broken_lines`로 따로 알린다.
3. **worktree 나이는 파일 기준**: 처음에는 폴더 mtime을 섞었는데, 폴더에 심볼릭 링크 하나만 만들어도 mtime이 오늘로 바뀌어 40일 묵은 worktree가 "최근 활동"으로 보였다. 테스트가 잡았고, 파일 mtime의 최댓값만 쓰도록 고쳤다(파일이 하나도 없을 때만 폴더 시각).
4. **심볼릭 링크는 따라가지 않고 크기에도 넣지 않는다**: 밖의 큰 파일을 가리키는 링크가 worktree 크기를 부풀리지 않고, 자기 폴더를 가리키는 순환 링크에서 멈추지 않는다.
5. **`slim`은 새 파일만 쓴다**: 이미지 줄만 다시 직렬화하고 나머지는 바이트 그대로 복사한다. 이미지 블록은 `{"type":"text","text":"[disk-diet: 이미지 제거 image/png base64 300000자]"}`로 바꿔 줄 수와 나머지 구조를 유지한다. 이미 있는 출력·원본과 같은 경로는 거부한다.
6. 사용한 것: Python 3 표준 라이브러리, `test.sh`용 가짜 홈 생성기(`make_fixture.py`). 모델·키는 쓰지 않는다.

## 4. 사용법
```bash
cd days/2026-11-22-disk-diet
python3 disk_diet.py audit                       # 표(읽기 전용)
python3 disk_diet.py audit --oneline             # 로그용 한 줄
python3 disk_diet.py audit --json --top 10       # 기계가 읽는 형태
python3 disk_diet.py audit --budget-mb 5000      # ~/.claude + 실행 파일이 5GB 넘으면 exit 1
python3 disk_diet.py audit --home /다른/홈 --days 14 --keep-versions 3
python3 disk_diet.py plan                        # 정리 명령 출력만(실행 안 함)
python3 disk_diet.py slim ~/.claude/projects/<프로젝트>/<세션>.jsonl -o ./세션.slim
```
출력 예(가짜 홈, `test.sh`의 픽스처):
```
| 자리 | 크기 | 비고 |
| ~/.claude 전체 | 595.7KB | 설정·인증이 섞여 있어 통째로 지우지 않는다 |
| 대화 기록(projects/*.jsonl) | 493.1KB | 세션 3개 · base64 이미지 3장 489.3KB |
| worktree(~/.claude/worktrees) | 102.5KB | 2개 중 21일 넘게 손 안 댄 것 1개 |
| 옛 실행 파일(~/.local/share/claude/versions) | 195.3KB | 4개 중 최신 2개 남기면 2개가 후보 |
되찾을 수 있는 후보: 686.5KB (이미지 489.3KB · 옛 버전 97.7KB · 오래된 worktree 99.6KB)
```
`slim`한 사본은 직접 열어 확인한 뒤 원본과 바꿔야 공간이 확보된다(자동으로 바꾸지 않는다). 사본은 `~/.claude/projects` **밖**에 둔다(안에 두면 Claude Code가 세션으로 읽는지 시험하지 않았으므로 피한다).

## 5. 테스트 결과
`bash test.sh` (키·모델 없음, 가짜 홈 폴더 사용). 이 도구는 모델을 부르지 않아 `e2e.sh`는 없다. 실행 환경: GitHub Actions 러너(Linux), Python 3.12.

```
$ bash test.sh
ok   audit --json: exit 0
ok   대화 기록 파일 3개
ok   이미지 3장 · base64 501000자(중첩 tool_result 포함)
ok   이미지 표시가 있는 깨진 줄 1개를 따로 센다
ok   가장 큰 세션이 맨 위(이미지 많은 aaaa)
ok   실행 파일 4개 중 최신 2개 유지 → 옛 버전 2개 100000바이트
ok   옛 버전은 1.0.1·1.0.2
ok   오래된 worktree는 old-wt뿐
ok   old-wt 크기 102000(심볼릭 링크 900000 제외)
ok   old-wt는 링크를 만들어도 40일 전으로 본다
…(중략: plan·slim·예산·빈 홈 검사)
ok   slim: 이미지 없는 파일은 0장·사본이 바이트까지 같다
ok   인자 없이 실행: 도움말과 exit 2

통과 45 · 실패 0
```
- 처음 돌렸을 때 2건이 실패했다. 원인은 도구가 아니라 테스트의 기대값이었다(Python 리스트 출력은 작은따옴표인데 큰따옴표로 비교). 출력 확인 뒤 비교 방식을 문자열 이어붙이기로 고쳤다.
- 이 러너의 실제 홈을 읽기 전용으로 돌린 결과: `disk-diet: ~/.claude 3.8MB · 대화 기록 794.7KB · 되찾을 후보 0B` (이미지·worktree·옛 버전 없음).
- 검증한 것: 이미지 개수·글자 수(중첩 포함), 깨진 줄 분리, 옛 버전·오래된 worktree 판정, 링크 제외·순환 링크, `plan`이 파일을 바꾸지 않음과 보호 파일 미포함, `slim`의 원본 불변·덮어쓰기 거부·비이미지 줄 바이트 일치, 예산 초과 exit 1.

## 6. 한계와 다음 아이디어
- **진짜 환경에서는 확인하지 못했다.** 가짜 홈 폴더로만 시험했다. 이미지가 수백 MB 든 진짜 세션, 맥의 `~/Library/Application Support/Claude`·`~/.cursor`·`~/.codex`는 보지 않는다. Claude Code가 세션 파일을 다른 위치·형식으로 두는 버전에서는 후보가 비게 나온다(그때는 오탐이 아니라 "없음"으로 나온다).
- 이미지 블록의 모양(`type: image` · `source.type: base64`)은 이 저장소의 다른 도구와 Messages API 형식을 따른 가정이며 실제 세션 파일로는 확인하지 못했다. 실제 세션 파일이 이미지를 다른 필드로 저장하면 세지 못한다.
- `slim`한 세션을 `--resume` 하면 모델은 이미지를 못 본다(대신 제거 표시만 본다). 이미지가 맥락의 핵심인 세션에는 쓰지 않는다. 이 동작(재개가 정상인지)은 시험하지 않았다.
- `plan`의 worktree 삭제는 "커밋 안 한 변경이 없는지"를 검사하지 않고 안내만 한다. worktree를 지운 뒤에는 원래 저장소에서 `git worktree prune`이 필요하다.
- "옛 버전 = 최신 N개 외 전부"는 단순 규칙이다. 지금 실행 중인 버전을 지우지 않도록 `claude --version`과 대조하지 않는다.
- 다음 아이디어: `--exclude-active`(최근 N분 내 수정된 세션 제외), 크기 변화 추이를 매일 한 줄씩 남기는 `--log`, 같은 대화가 담긴 세션 중복 탐지. 오늘 news 2번(강제 푸시 훅)에서 찾은 우회 4건(`-fu`, `+main`, `git -C`, `--mirror`)은 별도 후보 `guard-bypass`로 남긴다.

## 7. 출처
- https://dev.to/fastlog/claude-code-cursor-and-codex-eating-disk-space-on-your-mac-heres-where-it-goes-51a7 — 계기가 된 글 (11-22, CleanBit)
- https://dev.to/cybermax/stop-claude-code-from-force-pushing-a-20-line-hook-with-a-test-4b7e — 같은 날 수집한 훅 글(6절 후속 후보의 근거)
- https://code.claude.com/docs/en/changelog — Claude Code 변경 기록(최신 v2.1.330 확인)

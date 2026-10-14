# session-bulkhead

## 1. 무엇을 만들었나
Claude Code **PreToolUse 훅**(Python 표준 라이브러리 한 파일). 세션마다 장부 파일(작업 트리·잡은 포트·최근 빌드 시각)을 남기고, Bash 명령을 실행하기 전에 "지금 살아 있는 다른 세션"의 장부와 대조해 네 가지를 exit 2로 막는다. 막는 이유와 대안은 stderr로 낸다.

| 규칙 | 막는 것 | 안내하는 대안 |
|---|---|---|
| `name-kill` | `pkill`·`killall`·`taskkill /IM`·`kill $(pgrep …)`·`ps\|grep\|xargs kill` (다른 세션이 있을 때만) | `$!`로 적어 둔 PID로 `kill`, 또는 패턴에 이 작업 트리 절대경로 넣기(그러면 통과) |
| `port` | 다른 세션이 잡은 포트로 서버 띄우기, 그 포트를 `lsof\|xargs kill`·`fuser -k`로 죽이기 | 비어 있는 다음 포트 번호 |
| `heavy` | 빌드·테스트(`npm run build`, `cargo build`, `pytest`, `docker build` 등)를 다른 세션 2개가 최근 120초 안에 시작했을 때, 또는 여유 메모리 < 1GB | 잠시 뒤 재시도 |
| `shared-git` | 다른 세션과 같은 작업 트리에서 `checkout`·`switch`·`reset --hard`·`clean`·`stash`·`restore`·`rebase`·`merge`·`pull` | `git worktree add ../이름 -b 브랜치` |

그 밖에 `status`(살아 있는 세션 표), `check "명령"`(장부를 건드리지 않고 판정만), `end`(SessionEnd 훅으로 장부 삭제), `SESSION_BULKHEAD_DRY_RUN=1`(막지 않고 말만)이 있다.

## 2. 왜 만들었나
- GeekNews 10-13 [claude-bulkhead: 병렬 Claude Code 세션의 프로세스·포트·메모리 충돌 방지](https://news.hada.io/topic?id=35290) (curl은 403, WebFetch로 열람): worktree마다 세션을 띄워 쓰던 작성자가 한 에이전트의 `taskkill /F /IM node.exe`로 다른 세션의 개발 서버가 같이 죽고, 세 세션이 동시에 빌드해 PC가 멈춘 일을 겪고 플러그인을 만들었다.
- 같은 날 dev.to [Claude Code와 Codex 병렬 실행: worktree 함정](https://dev.to/offrun/running-claude-code-and-codex-in-parallel-on-one-repo-git-worktree-gotchas-and-cross-review-41eg)과 Anthropic 엔지니어링의 자체 버전 관리 시스템 글(에이전트 병렬화가 병목이 됐다)이 같은 방향이다. 병렬 세션은 점점 기본값이 되는데, 세션끼리 서로를 모른다는 게 빈틈이다.
- 기존 결과물과 다르다: disaster-guard는 명령 하나만 보고(세션 간 상태를 모른다), spend-gate는 비용만 본다. "다른 세션이 있다"를 아는 훅은 처음이다.
- 같은 날 공식 플러그인 security-guidance 커밋([8d392c8](https://github.com/anthropics/claude-plugins-official/commit/8d392c8169665866be1d95f2bfeda5aaae7149dd))에서 비동기 훅은 `additionalContext`가 아니라 stderr를 모델이 본다는 점을 배워 차단 이유를 stderr로만 낸다.

## 3. 어떻게 만들었나
1. **장부 = 세션당 JSON 한 파일**(`~/.claude/session-bulkhead/<session_id>.json`). 잠금 없이 임시 파일 → `os.replace`로 원자적으로 쓰고, 읽을 때 깨진 파일은 건너뛴다. 마지막 활동이 1시간(TTL) 넘은 세션은 죽은 것으로 본다. `SessionEnd` 훅이 정상 종료 때 바로 지운다.
2. **명령 텍스트는 저장하지 않는다.** 장부에는 cwd·git 최상위 폴더·포트·시각만 있다(명령에 비밀값이 섞일 수 있어서. 테스트로 고정).
3. **명령 해석은 정규식 + `shlex`.** `;` `&&` `|` `$()` 백틱으로 조각내고 `VAR=값`·`sudo`·`nohup` 같은 앞 래퍼를 벗겨 첫 단어로 판정한다. `curl`·`lsof`·`ssh` 같은 클라이언트·조회 명령은 포트를 "잡는" 것으로 치지 않는다.
4. **오탐을 줄이는 결정들**
   - `pkill`은 다른 세션이 있을 때만 막는다(혼자일 땐 무해). `SESSION_BULKHEAD_STRICT=1`이면 혼자여도 막는다.
   - `pkill -f <이 작업 트리 절대경로>`는 통과시킨다 — 범위가 내 트리로 좁혀지므로.
   - 포트 클레임은 막힌 명령에서는 하지 않는다. 오래된 클레임(120초 초과)은 `/proc/net/tcp`로 실제 LISTEN 중일 때만 유효로 본다(죽은 서버가 포트를 영원히 쥐지 않게). macOS처럼 `/proc`이 없으면 클레임을 그대로 믿는다.
   - 빌드는 "메모리가 모자라다"만으로는 부족하다 — 동시에 시작하는 세션들은 아직 메모리를 안 먹은 상태라서. 그래서 **최근 N초 안에 시작한 다른 세션의 빌드 수**를 센다(근거: 세 세션이 동시에 빌드해 멈췄다는 원 사례).
5. **fail-closed**: 입력 JSON이 깨지거나 설정이 잘못되면 exit 1 → `settings.example.json`의 `onFailure: "block"`(2.1.295)이 막는다. 장부 파일 하나가 깨진 것은 훅 실패가 아니라 "그 세션은 없는 것"으로 처리한다.
6. 만든 뒤 **규칙 한 줄을 일부러 망가뜨려**(혼자일 때도 name-kill 차단) 테스트 3개가 실패하는 것을 확인하고 원복했다.

## 4. 사용법
```bash
mkdir -p ~/.claude/hooks && cp hooks/session_bulkhead.py ~/.claude/hooks/
# ~/.claude/settings.json 에 settings.example.json 의 "hooks" 블록을 합친다 (PreToolUse: Bash, SessionEnd)

python3 ~/.claude/hooks/session_bulkhead.py status                 # 살아 있는 세션
python3 ~/.claude/hooks/session_bulkhead.py check "pkill node"     # 판정만 (exit 2=차단)
SESSION_BULKHEAD_DRY_RUN=1 claude                                  # 막지 않고 stderr로 경고만
SESSION_BULKHEAD_DISABLE=heavy claude                              # 규칙 끄기 (name-kill,port,heavy,shared-git)
```
임계값(`ttl_s`·`max_heavy`·`heavy_window_s`·`min_mem_mb`·`port_grace_s`)은 `hooks/session-bulkhead.json`이나 `SESSION_BULKHEAD_*` 환경변수로 바꾼다.
Claude Code 없이 두 세션 충돌을 재현: `bash demo.sh`.

## 5. 테스트 결과
`bash test.sh` (키·모델 불필요, 단위 + 훅 프로세스 43건):
```
test_mutating_git_in_shared_tree_blocked (test_session_bulkhead.SharedGit.test_mutating_git_in_shared_tree_blocked) ... ok
test_read_only_and_soft_ok (test_session_bulkhead.SharedGit.test_read_only_and_soft_ok) ... ok
test_separate_worktree_ok (test_session_bulkhead.SharedGit.test_separate_worktree_ok) ... ok

----------------------------------------------------------------------
Ran 43 tests in 1.009s

OK
```
`bash demo.sh` (훅 프로토콜 그대로 stdin JSON → exit code·stderr):
```

$ [sessionA-1111] npm run dev -- --port 3000
  -> exit 0

$ [sessionB-2222] npm run dev -- --port 3000
[session-bulkhead:port] 포트 3000은 다른 세션(sessionA, /tmp/…/repo)이 쓰는 중이다. 다른 포트(예: 3001)로 띄우거나, 그 포트의 프로세스는 건드리지 마라.
  -> exit 2

$ [sessionB-2222] pkill node
[session-bulkhead:name-kill] 이름 기반 프로세스 종료는 막혀 있다: `pkill node`. 지금 이 기기에 다른 Claude Code 세션이 1개 살아 있어서 그 세션의 개발 서버·테스트까지 함께 죽는다. 내가 직접 띄운 프로세스의 PID(`$!`나 `echo $!`로 적어 둔 값)로 `kill <pid>`를 쓰거나, 패턴에 이 작업 트리 절대경로를 넣어 범위를 좁혀라.
  -> exit 2

$ [sessionB-2222] git checkout -b feature-x
[session-bulkhead:shared-git] `git checkout`는 작업 트리(/tmp/…/repo)의 파일과 HEAD를 바꾼다. 이 트리를 다른 세션(sessionA)도 쓰고 있어 그 세션의 작업이 뒤엉킨다. `git worktree add ../<이름> -b <브랜치>`로 따로 작업 트리를 만들어 거기서 하라.
  -> exit 2

$ [sessionB-2222] kill 4242
  -> exit 0

$ [sessionB-2222] npm run dev -- --port 3001
  -> exit 0

세션            마지막 활동  작업 트리                                    포트
sessionB         0초  /tmp/…/repo                 3001
sessionA         0초  /tmp/…/repo                 3000
```
- 변이 확인: name-kill의 "다른 세션이 있을 때만" 조건을 지우면 3건 실패(`test_allowed_alone` 등), 원복 후 43건 통과.
- 이 환경의 `/proc/meminfo` 실측: MemAvailable 약 14.7GB → `check "npm test"` 통과.
- **`e2e.sh`는 미실행**: CI 러너의 `claude 2.1.296`이 로그인되어 있지 않아 `claude에 로그인되어 있지 않다. e2e 미실행(exit 3)`로 끝났다. 즉 **실제 Claude Code 세션에서 차단 이유(stderr)가 모델에게 전달되는지는 아직 확인하지 못했다.** 로그인된 환경에서 `bash e2e.sh`를 돌리면 확인된다.

## 6. 한계와 다음 아이디어
- **실제 세션 e2e 미확인**(위). 훅 입력 JSON의 `session_id`·`cwd` 필드 이름은 Claude Code 문서와 기존 훅(spend-gate)의 가정을 따랐다.
- 명령 해석은 정규식이라 우회가 가능하다: `bash -c "pkill node"`, 스크립트 파일 안의 `pkill`, `cd 다른폴더 && git checkout`(`git -C`만 해석), 별칭·함수. 방어선이 아니라 **사고 방지 안전망**이다.
- 포트 클레임은 "명령에 적힌 포트"만 안다. 프레임워크 기본 포트(`npm run dev`가 알아서 3000)는 못 잡는다 → 다음: 명령 실행 뒤 `/proc/net/tcp`나 `lsof` 스냅샷 차이로 실제로 열린 포트를 장부에 기록(PostToolUse).
- 빌드 동시 상한은 "시작 시각 120초"로 어림한다. 빌드가 끝났는지는 모른다 → 다음: PostToolUse에서 `heavy_end` 기록.
- 이름 기반 종료 차단은 다른 세션의 *프로세스 소유*를 모른다. 다음: 세션이 띄운 PID를 장부에 모아 "남의 PID를 죽이는 `kill`"만 막기.
- 장부는 단일 기기용이다. 원격(SSH) 에이전트에는 장부 폴더를 공유 마운트해야 한다.
- Windows는 경로·`/proc`이 달라 미지원(`taskkill /IM` 패턴만 인식).

## 7. 출처
- https://news.hada.io/topic?id=35290 (claude-bulkhead 소개, curl 403 · WebFetch로 확인)
- https://dev.to/offrun/running-claude-code-and-codex-in-parallel-on-one-repo-git-worktree-gotchas-and-cross-review-41eg
- https://github.com/anthropics/claude-plugins-official/commit/8d392c8169665866be1d95f2bfeda5aaae7149dd
- https://news.hada.io/topic?id=35309 (Anthropic 자체 버전 관리 시스템 Scion 소개, curl 403 · WebFetch로 확인)
- https://www.anthropic.com/engineering
- https://code.claude.com/docs/en/changelog (`onFailure: "block"` 2.1.295)

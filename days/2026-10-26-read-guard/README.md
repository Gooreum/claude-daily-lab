# read-guard

## 1. 무엇을 만들었나
Claude Code `PreToolUse` 훅(`read_guard.py`, 표준 라이브러리만 사용)이다. `Read`와 `Bash`(`cat`/`less`/`more`/`bat`/`nl`) 호출이 락 파일(`package-lock.json`, `yarn.lock`, `Cargo.lock` 등)·`*.min.js`·`*.map`·`node_modules/`·`dist/` 같은 의존성·빌드 폴더·압축/바이너리 파일을 **통째로** 읽으려 하면 exit 2로 거부하고, 대신 쓸 명령을 모델에게 알려 준다. `offset`/`limit`(≤200줄)로 일부만 읽는 호출, 8KB 미만 파일, 없는 파일, `| head`·`grep`·`wc`는 통과한다. 같은 스크립트가 `--audit DIR`(`.claudeignore`가 있는데 `Read` deny 규칙이 없으면 알리고 옮길 규칙을 출력)과 `--stats LOG`(차단 로그 요약)도 한다.

## 2. 왜 만들었나
2026-10-25 dev.to 글 [Cutting Claude Code token usage, the parts that actually matter](https://dev.to/humaki/cutting-claude-code-token-usage-the-parts-that-actually-matter-41oo) (news/2026-10-26.md 1번)이 계기다. 낭비의 대부분이 락 파일·번들·소스맵 같은 "중간 크기의 쓸모없는 읽기"이고, 훅은 전체 읽기와 부분 읽기를 구분할 수 있지만 `permissions` deny 규칙은 둘을 구분하지 못하며, `.claudeignore`는 Claude Code에서 효과가 없다는 점이 직접 만들어 볼 만했다. 이 저장소에는 비밀값 차단(`onfailure-secret-guard`)과 재난 명령 차단(`disaster-guard`) 훅은 있어도 토큰 낭비를 막는 읽기 가드는 없었다. 글은 절약률을 측정하지 않았으므로 이 도구도 절약 효과를 주장하지 않고 차단 로그와 바이트÷4 추정만 낸다.

## 3. 어떻게 만들었나
1. 판정을 "무거운 종류인가"(`classify`)와 "그래도 통과시킬 이유가 있나"로 나눴다. 통과 이유는 부분 읽기(`limit` 1~200), 작은 파일(기본 8KB 미만), 존재하지 않는 파일이다. 없는 파일은 판단을 보류한다(훅이 에러 메시지를 가로채지 않게).
2. 바이너리(`.zip`, `.pyc`, `.wasm` 등)는 작아도 거부한다. 이미지·PDF는 Claude가 실제로 읽을 수 있으므로 대상에서 뺐다.
3. `Bash`는 `shlex`로 쪼개 `;`·`&&`·`||`·`&`로 명령을 나누고, `|` 앞 세그먼트는 출력이 걸러진다고 보아 통과시킨다. 따옴표가 깨진 명령은 막지 않는다. 훅 입력이 깨졌을 때도 작업을 막지 않는다(fail-open). 보안 훅이 아니라 낭비 방지 훅이라서다.
4. 거부 이유(stderr)에 파일 크기와 대안 명령(`grep -n`, `head -n 50`, `Read offset/limit`)을 넣어, 모델이 같은 호출을 되풀이하지 않고 부분 읽기로 바꾸게 한다.
5. `READ_GUARD_LOG`를 주면 차단만 JSONL로 남기고 `--stats`가 건수·종류·파일별 상위·추정 절약 토큰을 보여 준다.
6. `.claudeignore` 항목을 `Read(./dir/**)`·`Read(./**/*.ext)` 형식 deny 규칙으로 바꿔 주는 `--audit`을 더했다. 두 도구의 역할은 다르다. deny 규칙은 부분 읽기까지 막으므로 비밀 파일용이고, 락 파일처럼 가끔 일부는 읽어야 하는 것은 훅이 맡는다.

## 4. 사용법
```bash
mkdir -p .claude/hooks && cp read_guard.py .claude/hooks/
# .claude/settings.json 에 settings.example.json 의 hooks 블록을 병합
```
```json
{"hooks":{"PreToolUse":[{"matcher":"Read|Bash","hooks":[{"type":"command","command":"python3 ${CLAUDE_PROJECT_DIR}/.claude/hooks/read_guard.py","timeout":10}]}]}}
```
거부될 때 모델이 보는 메시지 예:
```
read-guard: package-lock.json (70,000 bytes, lockfile) 전체 읽기는 컨텍스트를 낭비합니다. 필요한 부분만 읽으세요: Grep으로 찾은 뒤 Read에 offset/limit(≤200줄)을 주거나, `grep -n <패턴> package-lock.json`, `head -n 50 package-lock.json`, `wc -l package-lock.json`를 쓰세요.
```
환경 변수: `READ_GUARD_MIN_BYTES`(기본 8192), `READ_GUARD_MAX_LIMIT`(기본 200), `READ_GUARD_LOG`(차단 기록 파일).
```bash
python3 read_guard.py --audit .            # .claudeignore·deny 규칙·훅 등록 점검 (문제 있으면 exit 1)
python3 read_guard.py --audit . --json
READ_GUARD_LOG=/tmp/guard.jsonl claude    # 세션 후
python3 read_guard.py --stats /tmp/guard.jsonl
```

## 5. 테스트 결과
`bash test.sh` (키·모델 없이 실행, 훅 입력 JSON을 직접 넣는다):
```
== Read 차단 (exit 2)   ✅ 8개 (락 파일·상대 경로+cwd·node_modules·*.min.js·*.map·작은 .zip·limit 5000·offset만)
== Read 통과 (exit 0)   ✅ 5개 (offset=1 limit=3·limit=200 경계·작은 락 파일·큰 일반 소스·없는 파일)
== Bash 차단 (exit 2)   ✅ 5개 (cat·cat -n·less·&& 뒤의 cat·여러 파일 중 하나가 무거움)
== Bash 통과 (exit 0)   ✅ 7개 (cat|head·grep -c·wc -l·head -n 3·작은 파일·평범한 명령·따옴표 깨짐)
== 방어 (exit 0)       ✅ 3개 (Write·깨진 JSON·빈 입력)
== 로그와 --stats       ✅ 5개 (차단 3건·lockfile 2건·bundle 1건·파일별 2건·MIN_BYTES 환경변수)
== --audit             ✅ 6개 (.claudeignore만 있으면 exit 1·status·규칙 3개·규칙 형식·모두 있으면 exit 0·훅 없으면 exit 1)
== 결과: pass=39 fail=0
```
`bash e2e.sh` (실제 Claude Code로 훅이 `Read`를 거부하는지) — **실행하지 못했다.** 이 러너에는 `claude` 2.1.310이 있지만 로그인이 없다. 출력 그대로:
```
claude: 2.1.310 (Claude Code)
== 1) 훅 설치 → 전체 읽기 거부 기록 (lock 86534 bytes)
   | Not logged in · Please run /login
  ⏭ 로그인 없음 — e2e 건너뜀(exit 3). 로그인 후 다시 실행
```
CI에서는 e2e 미실행. 따라서 **훅 입력 JSON의 필드 이름(`tool_name`, `tool_input.file_path/offset/limit`, `cwd`)과 "exit 2의 stderr가 모델에게 전달된다"는 동작은 이 저장소의 기존 훅(`onfailure-secret-guard`)과 문서 관례를 따랐을 뿐, 이번에 실제 세션에서 확인하지 못했다.**

## 6. 한계와 다음 아이디어
- 실제 세션 e2e 미확인(위). 로그인된 환경에서 `bash e2e.sh`로 "훅 설치 시 차단 기록이 남고, 없으면 안 남는다"를 먼저 확인해야 한다.
- 절약 효과는 측정하지 않았다. `--stats`의 토큰은 바이트÷4 추정이며, 원 글도 절약률을 재지 않았다. `/context`를 훅 전후로 비교하는 실험이 필요하다.
- 셸 우회는 일부만 막는다. `cat`류만 보고 `python -c "open(...).read()"`, `sed -n p`, `xargs cat`은 보지 못한다. 변수·글롭(`cat *.lock`)도 펼치지 않는다.
- 판정이 파일 이름·경로 규칙뿐이다. 이름이 평범한 거대 파일(`data.json` 5MB)은 통과한다. 크기 상한만으로 막는 옵션이 후보다.
- fail-open이다. 입력이 깨지면 통과시키므로 보안 목적에 쓰면 안 된다. 비밀 파일은 `permissions.deny`로 막아야 한다.
- 다음 후보: 팀 설정용 패턴 파일(`read-guard.json`)로 거부 목록 확장, 같은 파일을 두 번 차단한 뒤에는 부분 읽기를 강제하는 힌트 강화.

## 7. 출처
- https://dev.to/humaki/cutting-claude-code-token-usage-the-parts-that-actually-matter-41oo — 계기가 된 글
- https://code.claude.com/docs/en/hooks — 훅 문서

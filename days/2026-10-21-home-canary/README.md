# home-canary

## 1. 무엇을 만들었나
셸 스크립트가 진짜 홈 디렉터리를 지우는 사고를 두 방향에서 막는 CLI 스크립트(`home_canary.py`, 표준 라이브러리만 사용)다.
- `lint PATH...` — 정적 검사. 가드 없이 변수가 경로의 뿌리인 `rm -r…`(`rm -rf "$dir"/*`)을 찾고(`unguarded-rm`), 그런 스크립트에 `$HOME`·`~`·`/`를 넘기는 테스트(`real-path-to-destructive`)와 `mktemp` 없이 고정 경로로 부르는 테스트(`no-tmpdir`)를 지적한다.
- `run [--keep] [--dry-run] [--json] -- CMD...` — 동적 검사. 임시 가짜 HOME에 미끼 파일 5개(`.ssh/id_canary`, `work/project/.git/HEAD` 등)를 심고 `HOME`을 그곳으로 바꿔 CMD를 돌린 뒤 미끼가 지워지거나 바뀌었는지 보고한다. 훼손이 있으면 종료 코드 3, 없으면 CMD의 종료 코드를 그대로 낸다.

## 2. 왜 만들었나
dev.to 10-20 [「My Mac's files were deleted while Claude Code was building a guard against deleting files」](https://dev.to/ryodevapp/my-macs-files-were-deleted-while-claude-code-was-building-a-guard-against-deleting-files-df9)에서, "인자가 홈이면 멈추는 가드"를 추가하던 서브에이전트가 가드를 쓰기 전(RED 단계)에 테스트를 돌렸고, 그 테스트가 진짜 홈을 `rm -rf` 스크립트에 넘긴 것으로 글쓴이는 추정한다(단정은 아님). 권한 규칙·치명 경로 보호·auto 분류기는 Claude가 친 명령 한 줄만 보므로 스크립트 안의 삭제를 못 본다. 이 저장소의 `disaster-guard`도 같은 한계가 있어, 스크립트 **내부**를 보는 보완 도구가 필요하다고 판단했다.

## 3. 어떻게 만들었나
1. 사고 재현용 픽스처부터 만들었다: 가드 없는 `bad_wipe.sh`, 가드 있는 `good_wipe.sh`, 진짜 HOME을 넘기는 `test_bad.sh`, `mktemp`를 쓰는 `test_good.sh`.
2. `run`은 `HOME`·`USERPROFILE`·`XDG_CONFIG_HOME`을 가짜 폴더로 바꿔 자식 프로세스를 돌리고, 끝난 뒤 SHA-256으로 미끼의 삭제·수정을 비교한다. 임시 폴더는 기본으로 지운다(`--keep`으로 남김).
3. 처음 만든 lint는 "줄에 rm -r와 `$`가 있으면 지적"이라 이 저장소 자신의 `rm -rf "$tmp"`(mktemp 뒤)와 `rm -rf /tmp/x.$$`를 오탐했다. 그래서 (a) `rm`이 명령 위치에 있을 때만 보고(문자열·주석 속 제외), (b) 변수가 경로의 뿌리일 때만 지적하고, (c) 같은 파일에서 `mktemp`로 만든 변수는 안전으로 보게 고쳤다. 가드 판정은 앞쪽 줄에 `$HOME`·`"/"`·`-z "$…`·`realpath` 등이 있는지로 아주 단순하게 했다.
4. 오탐 관용구를 `fixtures/idioms.sh`로 고정해 회귀 테스트에 넣었다.

## 4. 사용법
```bash
cd days/2026-10-21-home-canary
python3 home_canary.py lint path/to/repo            # 위험한 삭제·테스트 호출 찾기 (지적 있으면 exit 1)
python3 home_canary.py lint . --json                # 기계가 읽는 출력
python3 home_canary.py run -- bash tests/cleanup_test.sh   # 가짜 HOME에서 실행, 미끼 훼손 시 exit 3
python3 home_canary.py run --dry-run -- bash tests/cleanup_test.sh  # 실행 없이 가짜 HOME 구성만 확인
```
예시 출력(사고 재현):
```
$ python3 home_canary.py run -- bash fixtures/test_bad.sh
가짜 HOME: /tmp/home-canary-kcs5cwyj/home (미끼 5개)
미끼 훼손 5개 — 이 명령은 진짜 HOME에서 돌리면 위험하다
  deleted: ~/.ssh/id_canary
  deleted: ~/Documents/notes.txt
  deleted: ~/work/project/.git/HEAD
  deleted: ~/work/project/src/main.txt
  deleted: ~/.config/app/settings.json
```
CI에서는 `lint`를 단계로 넣고, 의심스러운 테스트는 `run -- …`으로 감싼다. API 키·모델은 필요 없다.

## 5. 테스트 결과
`bash test.sh` (키·모델 없이 CI에서 돈다):
```
ok   lint: 가드 없는 rm -rf → exit 1
ok   lint: 진짜 HOME을 넘기는 테스트를 지적
ok   lint: 임시 폴더 없는 테스트를 지적
ok   lint: mktemp 변수·/tmp/x.$$·trap·문자열 속 rm은 오탐 아님
ok   run: 사고 재현 → exit 3
ok   run: .git/HEAD 삭제도 잡음
ok   run: 진짜 HOME은 무사
ok   run: 내용 수정도 잡음(modified)
ok   run: 훼손 없으면 명령 종료 코드 그대로(7)
ok   run --dry-run: 실행 안 하고 exit 0
...
---
통과 26 · 실패 0
```
이 저장소 `days/` 전체(59개 셸 파일)에 `lint`를 돌려 보니 지적은 이 폴더의 의도적 픽스처 5건뿐이었다(오탐 수정 전에는 29건). e2e는 모델 호출이 필요 없어 만들지 않았다.

## 6. 한계와 다음 아이디어
- `run`은 `HOME`을 바꾸는 방식이라 `~`·`$HOME`을 거치는 경로만 막는다. 스크립트가 `/Users/me`처럼 절대 경로를 하드코딩하거나 `getent passwd`로 홈을 찾으면 가짜 HOME을 우회한다. 완전한 격리는 OS 샌드박스(`sandbox.enabled`)나 컨테이너가 맡아야 한다. 이 도구는 샌드박스를 대신하지 않는다.
- `lint`는 정규식 휴리스틱이다. `rm`을 함수·`find -delete`·`xargs rm`·파이썬 `shutil.rmtree`로 쓰면 못 본다. 가드 판정도 "앞쪽 줄에 `$HOME`·`realpath` 등이 나온다"까지만이라, 가드가 있어도 틀린 경우나 없는데 우연히 통과하는 경우가 있다.
- 다음 아이디어: `find -delete`·`rmtree` 규칙 추가, Claude Code PreToolUse 훅으로 "테스트 명령을 `run`으로 감싸서 다시 실행"하게 만들기, 미끼에 `chattr`/읽기 전용 표식 추가.

## 7. 출처
- https://dev.to/ryodevapp/my-macs-files-were-deleted-while-claude-code-was-building-a-guard-against-deleting-files-df9
- https://code.claude.com/docs/en/sandboxing
- https://code.claude.com/docs/en/permissions

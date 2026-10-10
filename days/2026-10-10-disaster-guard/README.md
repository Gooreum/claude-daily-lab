# disaster-guard — 재난을 막는 Claude Code 훅 묶음

## 1. 무엇을 만들었나

한 저장소에 `bash install.sh <repo>` 한 번으로 까는 훅 묶음.

| 파일 | 역할 |
|------|------|
| `hooks/danger-guard.sh` + `hooks/rules.txt` | **PreToolUse(Bash)**. 파괴적 명령을 규칙 18개로 잡아 exit 2로 막는다. `onFailure: "block"`이라 훅 스크립트가 없거나 깨져도 통과하지 않는다 |
| `hooks/auto-format.sh` | **PostToolUse(Write·Edit·MultiEdit)**. 방금 쓴 파일을 확장자별 포맷터(ruff/black, prettier, shfmt, gofmt)로 정리. 포맷터가 없으면 조용히 통과, 어떤 경우에도 exit 0 |
| `settings.example.json` | 위 두 훅 + 권한 규칙: `npm run *`·`npm test`는 묻지 않고 허용, `npm install`·`pip install`·`pnpm add`는 묻기 |
| `install.sh` | `.claude/hooks/`에 복사하고 `settings.json`이 없으면 예시를 그대로, 있으면 합칠 JSON을 보여 준다 |

규칙 18개: git force push(`--force-with-lease` 포함)·reset --hard·clean -f·checkout/restore `.`·branch -D·push --delete, SQL DROP/TRUNCATE·WHERE 없는 DELETE/UPDATE, `curl|sh`·`wget|bash`, `rm -rf` 루트·홈·`.`·`*`, `chmod -R 777`, kubectl 네임스페이스 삭제·prod 변경, terraform destroy/`-auto-approve`, psql/mysql/mongo prod, docker prune -a, mkfs/dd. 규칙은 `이름<TAB>이유<TAB>플래그<TAB>ERE` 한 줄이라 팀이 추가·삭제한다.

## 2. 왜 만들었나

dev.to의 10월 9일 글 "재난을 막는 Claude Code 훅 3개"(10월 수집 27번)가 파괴적 명령 차단·비밀값 가드·자동 포맷 세 훅을 보여 줬고, 현실 적용 1번이 "세 훅을 settings 템플릿으로 배포하고 `onFailure: "block"`을 붙이기"였다. 비밀값 가드는 같은 날 onfailure-secret-guard로 이미 만들었으니 이 묶음은 나머지 둘(명령 차단, 포맷)과 글에서 같이 언급된 권한 규칙(`npm run *` 허용, `npm install` 묻기)을 담는다.

글이 못 박은 원칙을 그대로 따른다. **정규식 차단은 조기 경보다.** 되돌릴 수 없는 작업의 진짜 방어선은 브랜치 보호·DB 권한처럼 서버 쪽에 둔다.

## 3. 어떻게 만들었나

1. **danger-guard**: stdin JSON에서 `tool_name`이 Bash일 때만 `tool_input.command`를 꺼낸다(python3). 줄바꿈·탭을 공백으로 접어 heredoc 안의 `DROP TABLE`도 본다. 규칙을 위에서부터 `grep -E`로 검사해 처음 걸린 규칙 이름과 이유를 stderr에 쓰고 exit 2. JSON이 아니거나 규칙 파일이 없으면 exit 1 — `onFailure: "block"`과 합쳐 fail-closed.
2. **플래그 열**: 처음엔 전부 대소문자 무시였는데 `git branch -d`(안전)가 `-D` 규칙에 걸렸다. 규칙마다 `i`/`cs`를 두고, WHERE 없는 DELETE/UPDATE는 ERE로 "WHERE가 없다"를 못 쓰니 `nowhere` 플래그로 "명령에 `\bwhere\b`가 있으면 통과"를 따로 검사한다.
3. **오탐 테스트를 차단 테스트만큼 둔다.** `rm -rf node_modules`, `git push -u origin feat`, `curl … | jq`, `kubectl get pods -n prod`, `DELETE … WHERE`, `grep production src/` 같은 22개가 통과해야 한다. 가드가 자주 틀리면 사람이 끄기 때문이다.
4. **auto-format**: PostToolUse는 막을 이유가 없어 항상 exit 0. 포맷터 호출은 테스트에서 PATH에 가짜 `ruff`를 넣어 호출 인자만 확인한다(이 머신에 포맷터가 하나도 없다).
5. **e2e**: 임시 git 저장소에 `install.sh`로 깔고 `claude -p`로 세 장면을 돌린다. 배운 것: 신뢰(trust)하지 않은 작업 폴더에서는 프로젝트 `settings.json`의 `permissions.allow`는 무시된다는 경고가 뜨지만 **훅은 그대로 실행된다**. `--allowedTools "Bash(git *)"`로 CLI에서 허용을 줘야 2번 장면이 돈다. macOS는 `/var/…`가 `/private/var/…`로 바뀌어 훅이 받는 경로가 다르다.

## 4. 사용법

```bash
cd days/2026-10-10-disaster-guard
bash install.sh ~/Code/my-repo        # .claude/hooks/ 3파일 + settings.json (없을 때만)
# 규칙 추가: hooks/rules.txt 에 한 줄.  예) aws-delete<TAB>버킷을 지운다<TAB>i<TAB>\baws\s+s3\s+rb\b
printf '{"tool_name":"Bash","tool_input":{"command":"git push -f"}}' | bash hooks/danger-guard.sh; echo "exit=$?"

bash test.sh   # 훅 단위 60건 (차단 28·통과 22·입력 이상 3·포맷 4·설정 1·설치 2), 모델 호출 없음
bash e2e.sh    # 실제 Claude Code 세션 3회 (Haiku, 1센트 미만)
```

## 5. 테스트 결과

`bash test.sh` (2026-10-10, Claude Code 2.1.296):

```
== 1) danger-guard: 차단 (exit 2)                                  … 28건 ✅
== 2) danger-guard: 통과 (exit 0) — 흔한 안전 명령이 오탐되지 않는다   … 22건 ✅
== 3) danger-guard: Bash 아닌 도구는 통과, 깨진 입력은 exit 1        … 3건 ✅
== 4) auto-format: 가짜 포맷터로 호출 확인, 포맷터 없으면 아무 일 없음  … 4건 ✅
== 5) settings.example.json: 유효한 JSON, 가드에 onFailure:block     … ✅
== 6) install.sh: 빈 저장소에 설치                                   … 2건 ✅
== 결과: pass=60 fail=0
```

`bash e2e.sh` (실제 Claude Code, Haiku):

```
== 1) git push --force → danger-guard가 막는다
   | Blocked: the PreToolUse hook `danger-guard.sh` rejected `git push --force origin main` with "BLOCKED [git-force-push] 원격 이력을 덮어쓴다 (--force-with-lease 포함). 사람이 직접 실행한다." …
  ✅ 차단 메시지가 모델에게 전달됨
== 2) git status → 통과
   | On branch main
  ✅ 안전한 명령은 그대로
== 3) Write a.py → auto-format 훅이 (가짜) ruff를 부른다
   | done
  ✅ PostToolUse → ruff format a.py
== 결과: pass=3 fail=0
```

처음 돌렸을 때 단위 2건 실패: `git branch -d`가 대소문자 무시 때문에 `-D` 규칙에 걸렸고, `UPDATE … WHERE id = 3`이 "WHERE 없음" 규칙에 걸렸다. 플래그 열(`cs`, `nowhere`)을 넣어 고쳤다. e2e 3번은 훅이 실제로 돌았는데 경로가 `/private/var`로 바뀌어 검사만 실패해 파일 이름으로 비교하게 바꿨다.

## 6. 한계와 다음 아이디어

- 정규식은 우회된다. `git push --forc$(echo e)`, 변수에 넣은 명령, 스크립트 파일 실행은 못 본다. 이 가드는 "실수로 치는 것"을 막지 "작정한 우회"를 막지 않는다. 서버 쪽 보호가 먼저다.
- `rm -rf $DIR` 같은 변수 삭제는 못 잡는다. 변수가 비면 `rm -rf /`가 된다. `set -u`를 강제하는 규칙을 추가할 수 있다.
- 포맷터는 파일 전체를 다시 쓰므로 Edit 한 줄이 diff 수백 줄이 될 수 있다. `--diff`만 출력하는 모드나 변경 범위 포맷(`ruff format --range`)이 다음.
- 다음: 규칙 파일을 조직 공통 저장소에서 내려받아 갱신하는 `update-rules.sh`, 차단 로그를 `$.store`에 쌓는 모드판(agent-radar처럼 pane에 "오늘 막은 것 N건"), 10-10 수집 2번의 `prompt` 훅으로 정규식이 못 잡는 규칙("prod처럼 보이는 호스트")을 자연어로.

## 7. 출처

- dev.to "3 Claude Code hooks that prevent disasters" (10-09): https://dev.to/luijhy_michaelguerraflo/3-claude-code-hooks-that-prevent-disasters-with-code-178b
- Claude Code 훅 문서 (PreToolUse/PostToolUse 입력·exit 2·`onFailure`): https://code.claude.com/docs/en/hooks
- Claude Code changelog 2.1.295 `onFailure: "block"`: https://code.claude.com/docs/en/changelog
- 10월 수집 27번·28번 항목: ../../news/2026-10-october-all.md
- 같은 날의 비밀값 가드 (패턴 목록은 거기): ../2026-10-10-onfailure-secret-guard/

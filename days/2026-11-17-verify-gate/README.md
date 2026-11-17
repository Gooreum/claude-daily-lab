# verify-gate

`git commit` 직전에 "이 세션에서 검증했다"는 증거가 있는지 보고, 없으면 기록하거나 막는 Claude Code `PreToolUse` 훅.

## 1. 무엇을 만들었나

Python 표준 라이브러리만 쓰는 훅 스크립트 한 개(`verify_gate.py`). Bash 도구 호출이 `git commit`이면 훅 입력의 `transcript_path`(세션 기록 JSONL)를 읽어, 마지막 파일 수정 **뒤에** `/verify`·`/code-review` 실행(슬래시 명령 또는 Skill 호출)이 있었는지 판정한다. 판정은 `verified`(증거가 수정보다 뒤) / `stale`(증거는 있으나 그 뒤에 또 수정) / `none`(증거 없음) / `waived`(커밋 메시지에 `Unverified: 이유`) / `unknown`(기록을 못 읽음, 열어 둠)이다.

동작은 모드로 정한다: `off`(아무것도 안 함), `observe`(기본. 막을 뻔한 커밋만 로그에 남김), `enforce`(종료 코드 2로 차단하고 이유와 해결법을 Claude에게 돌려줌). 한 세션에서 `max_blocks`(기본 2)번 막으면 다음 커밋은 통과한다. 하위 명령: `check`(기록 하나를 판정), `report`(로그 요약), `print-settings`(훅 등록 JSON).

## 2. 왜 만들었나

- 소식: [How the Claude Code team thinks about verification](https://claude.dev/blog/how-the-claude-code-team-thinks-about-verification/) (claude.dev 블로그, 2026-11-16, Addy Osmani)
- 글은 Claude Code 팀이 `/code-review`나 `/verify`가 세션에 없으면 커밋을 막는 게이트를 off·observe·enforce 세 단계로 도입하고, 두 번 막히면 세 번째는 통과시키며, 오래된 커밋에 대한 통과는 의미 없다고 말한다. 한 사람이 감당할 수 있는 Claude 수를 "검증 루프가 있느냐"가 정한다는 논지다.
- 이 저장소의 `/daily-lab` 루틴은 사람 없이 매일 커밋·푸시한다. 푸시 직전 재확인이 있지만 "그 재확인을 돌렸다"는 증거를 남기지 않는다. 글의 게이트는 규칙이 아니라 **기록을 읽는** 장치라 작게 만들어 시험하기 좋았다.
- 기존 `review-gate`(PR 리뷰 체크런으로 병합을 막음)는 커밋보다 뒤 단계를 본다. 커밋 직전 단계는 비어 있었다.

## 3. 어떻게 만들었나

1. **입력 형식부터 확인.** 이 세션의 진짜 기록(`~/.claude/projects/…/<세션>.jsonl`)을 열어 슬래시 명령은 user 메시지 문자열 안의 `<command-name>/이름</command-name>`, 도구 호출은 assistant 메시지의 `tool_use` 블록, 도구 결과는 user 메시지의 `tool_result`(`is_error`)임을 확인하고 파서를 그에 맞췄다.
2. **커밋 판별.** 정규식 하나로 `git commit`을 찾으면 `echo git commit`·`git log --grep="commit"`이 걸린다. 따옴표를 존중해 `; & | ( )`와 줄바꿈으로 명령을 나눈 뒤 `git`의 전역 옵션(`-C`, `-c`)을 건너뛰고 하위 명령이 `commit`인지 본다. `FOO=1 git commit`, `bash -c "git commit"`도 본다. `git commit-tree`는 제외한다.
3. **stale 판정.** 증거의 줄 번호가 마지막 수정 줄보다 커야 `verified`. 글의 "오래된 커밋에 대한 통과는 의미 없다"를 그대로 옮겼다.
4. **막힌 지점 두 개(진짜 기록으로 시험하다 발견).**
   - 이 세션은 파일을 전부 Bash heredoc으로 썼는데 처음엔 `Edit`·`Write`만 수정으로 세서 `마지막 수정 줄=-1`이 나왔다. 셸로 쓴 변경(`> 파일`, `tee`, `sed -i`, `mv`/`cp`/`rm`, `git apply`)도 수정으로 세도록 하고(`bash_edits`, 기본 켬) 따옴표 안의 `>`·`2>&1`·`/dev/null`은 제외했다.
   - 증거용 Bash 정규식(`bash test\.sh`)이 heredoc 본문에 적힌 글자에 반응했다. heredoc 본문을 지우고, 명령 맨 앞에서만 맞도록 `re.match`로 바꿨다. 이 수정을 일부러 되돌려(돌연변이) 테스트가 잡는지도 확인했다.
5. **빈 면제 버그.** `Unverified:` 뒤에 이유가 없고 닫는 따옴표만 오면 `"`를 이유로 읽어 면제되던 것을 테스트가 잡아 고쳤다.
6. **열어 두는 쪽을 기본으로.** 입력이 JSON이 아니거나, 세션 기록이 없거나, 설정 파일이 깨졌거나, mode가 이상하면 커밋을 막지 않고(`unknown`/observe) 로그·경고만 남긴다. 가드가 커밋을 못 쓰게 만드는 쪽이 더 나쁘다고 봤다.

설정·상태: `.claude/verify-gate.json`(`mode`, `slash`, `skills`, `bash`, `max_blocks`, `bash_edits`), 환경변수 `VERIFY_GATE_MODE`가 mode를 덮어쓴다. 로그와 세션별 차단 횟수는 `.claude/verify-gate/`(로그에는 판정·처리·면제 이유만, 명령 전체는 남기지 않는다. 이 폴더는 `.gitignore`에 넣을 것).

## 4. 사용법

```bash
# 1) 훅 등록 조각을 만들어 .claude/settings.json 에 합친다
python3 verify_gate.py print-settings

# 2) 처음엔 observe(기본): 막지 않고 기록만
echo '{"mode":"observe"}' > .claude/verify-gate.json

# 3) 며칠 뒤 로그를 본다
python3 verify_gate.py report            # 건수·검증 안 된 비율·최근 사례
python3 verify_gate.py report --json

# 4) 오탐이 없으면 enforce로 올린다
echo '{"mode":"enforce","max_blocks":2}' > .claude/verify-gate.json
# 또는 한 번만: VERIFY_GATE_MODE=enforce claude
```

테스트 실행을 증거로 인정하려면(예: `bash test.sh`가 성공했을 때):

```json
{"mode": "observe", "slash": ["verify", "code-review"], "bash": ["bash test\\.sh"]}
```

차단되면 Claude는 다음 메시지를 받는다.

```
verify-gate: 커밋을 막았다 — 이 세션에 /verify나 /code-review를 돌린 흔적이 없다.
  1) /verify 또는 /code-review를 돌린 뒤 다시 커밋하거나
  2) 검증하지 않는 이유가 있으면 커밋 메시지에 `Unverified: <이유>`를 적어라.
  (이 세션에서 1번 더 막히면 다음 커밋은 통과한다.)
```

기록 하나를 직접 판정: `python3 verify_gate.py check -t <세션>.jsonl` (verified면 종료 0, 아니면 1). 모델·키·네트워크가 필요 없다.

## 5. 테스트 결과

`bash test.sh` (이 폴더에서, 키·모델 없음) — 가짜 세션 기록 파일로 시험한다:

```
$ bash test.sh
ok   - 커밋으로 인식: git commit -m x
ok   - 커밋으로 인식: git -C repo commit -am x
...
ok   - 같은 세션: 차단, 차단, 통과
ok   - released 기록
ok   - 다른 세션은 처음부터 다시 센다
...
ok   - stale도 enforce에서 차단
ok   - 세션 기록이 없으면 통과
ok   - 알 수 없는 mode는 observe로 대체
커밋 3건 (읽지 못한 줄 0)
  verified    1
  none        2
처리: allowed 1, blocked 1, would-block 1
검증 안 된 비율(stale+none): 67%
...
ok   - print-settings: 올바른 JSON 훅 등록

통과 73 / 실패 0
```

- 처음 돌렸을 때 66개 중 3개가 실패했고(`is_error` 만드는 테스트 코드 버그, 건수 오산, **빈 `Unverified:`가 면제되는 진짜 버그**) 모두 고친 뒤 통과했다.
- heredoc 본문 오탐 수정을 일부러 되돌리자 `FAIL - heredoc 본문이 증거로 잡혔다`로 72/73이 되어 테스트가 그 버그를 잡는 것을 확인했다.
- **이 세션의 진짜 기록으로 `check`를 돌린 결과**(파서가 실제 형식을 읽는지 확인):

```
$ cfg={}                       → none  증거=-  마지막 수정 줄=217
$ cfg={"slash":["daily-lab"]}  → stale 증거=슬래시 /daily-lab  마지막 수정 줄=217
$ cfg={"slash":["nope"],"bash":["bash test\\.sh"],"bash_edits":false}
                               → verified 증거=Bash bash test.sh > /tmp/vg_test.txt 2>  마지막 수정 줄=-1
```

- `bash e2e.sh`(실제 Claude Code에 훅을 걸어 enforce가 커밋을 막는지 보는 시험): **이 환경에서는 실행하지 못했다.** 모델 호출이 `terminal_reason":"api_error"`로 끝나(로그인 없음) 스크립트가 `SKIP - 모델을 호출하지 못했다(로그인 없음?)`을 출력하고 종료 0으로 끝났다. CI에서는 e2e 미실행.

## 6. 한계와 다음 아이디어

- **실제 훅 경로는 미확인.** Claude Code가 `git commit`을 실행하려는 순간 `transcript_path` 파일에 방금의 `Skill` 호출까지 기록돼 있는지, 훅 입력에 `session_id`·`transcript_path`·`cwd`가 들어오는지는 로그인이 없어 e2e로 확인하지 못했다. 파서는 진짜 기록으로 시험했지만 훅 입력은 공식 형식에 대한 가정이다. 기록이 안 보이면 `unknown`으로 열어 두므로 막히는 쪽으로는 실패하지 않는다.
- **"검증했다"는 흔적 확인일 뿐 검증의 질이 아니다.** `/verify`를 돌리고 실패한 결과를 무시해도 `verified`다. `bash` 증거는 실패(`is_error`)면 인정하지 않지만 슬래시·Skill 증거는 결과를 보지 않는다.
- 셸 쓰기 감지는 휴리스틱이다. `python -c`로 파일을 쓰거나 `git checkout`으로 되돌린 변경은 수정으로 세지 못한다(stale을 놓침). 반대로 `echo`가 아닌 `rm`이 들어간 정리 명령은 수정으로 세어 stale이 과하게 나올 수 있다.
- `Unverified:` 면제는 에이전트가 스스로 적으면 그만이다. observe 기간에 `report`로 면제 비율을 사람이 보는 것이 전제다.
- 글의 "커밋에 검증 방식을 도장처럼 남기기"(stamp)는 만들지 않았다. 훅이 명령을 고쳐 쓰는 방식은 확인하지 못했다. 다음엔 `prepare-commit-msg` git 훅으로 `Verified-by:` 줄을 붙이는 것을 시도할 만하다.
- 다음 아이디어: 이 저장소 `/daily-lab`에 observe로 붙여 일주일 로그를 보기, 글의 "변경이 자기 검사를 고칠 수 없게" 규칙(CI가 `test.sh`·`REVIEW.md`를 베이스 브랜치 기준으로 읽는지) 점검기.

## 7. 출처

- https://claude.dev/blog/how-the-claude-code-team-thinks-about-verification/ — 계기가 된 글 (확인 시점 200)
- https://github.com/anthropics/claude-code/releases/tag/v2.1.326 — 같은 날 릴리스(설정·허용 규칙 경고 추가, 확인 시점 200)
- https://dev.to/vildandenai/stop-claude-code-from-running-curl-bash-with-a-pretooluse-hook-1jfl — PreToolUse 훅이 stdin JSON을 받고 exit 2로 막는 방식의 예 (확인 시점 200)
- 이 세션의 `~/.claude/projects/…/*.jsonl` — 세션 기록 형식 확인용 실물

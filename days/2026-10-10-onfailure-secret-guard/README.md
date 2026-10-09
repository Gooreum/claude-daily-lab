# onfailure-secret-guard — fail-closed 비밀값 가드 훅

## 1. 무엇을 만들었나
Claude Code의 PreToolUse 훅으로, Write/Edit/Bash 입력에서 AWS 키·Anthropic API 키·GitHub 토큰·개인키 블록 같은 비밀값 패턴을 찾으면 exit 2로 도구 호출을 차단하는 셸 스크립트다. 설정에서 2.1.295에 추가된 `onFailure: "block"`을 함께 켜서, 훅 스크립트가 없거나 죽거나 타임아웃돼도 통과시키지 않는 fail-closed 가드로 동작한다. 단위 테스트(`test.sh`)와 실제 Claude Code를 띄워 확인하는 e2e(`e2e.sh`)가 들어 있다.

## 2. 왜 만들었나
2026-10-08 Claude Code 2.1.295 릴리스에서 command/http 훅에 `onFailure: "block"` 옵션이 생겼다 ([changelog](https://code.claude.com/docs/en/changelog), [hooks 문서](https://code.claude.com/docs/en/hooks)). 기본값 `continue`에서는 훅이 실행 자체에 실패하면 액션이 그냥 통과했기 때문에, 보안 가드 훅은 "스크립트 경로 오타 하나로 조용히 무력화"될 수 있었다. 이 옵션이 그 구멍을 막아 주는지, 실제로 어떻게 보이는지 직접 확인하고 싶었다.

## 3. 어떻게 만들었나
1. **훅 입력 형식 확인**: hooks 문서에서 PreToolUse stdin JSON(`tool_name`, `tool_input`)과 차단 방식(exit 2 + stderr, 또는 `permissionDecision` JSON)을 확인했다. 단순함을 위해 exit 2 방식을 택했다.
2. **스크립트 작성** (`hooks/secret-guard.sh`): python3로 JSON을 파싱해 Write는 `content`, Edit는 `new_string`, Bash는 `command`만 뽑고, `hooks/patterns.txt`의 정규식(이름 TAB 정규식)을 `grep -Ei`로 돌린다. 매치되면 패턴 이름을 stderr에 적고 exit 2. 패턴 파일이 없거나 JSON이 깨지면 exit 1로 "훅 실패"가 되게 두어 `onFailure`가 받아 처리하게 했다. `SECRET_GUARD_FAIL=1`이면 일부러 죽는 데모 스위치도 넣었다.
3. **설정** (`settings.example.json`): matcher `Write|Edit|Bash`, `timeout: 10`, `onFailure: "block"`.
4. **막힌 지점**: 일반 `password = "..."` 패턴이 안 잡혔다. 원인은 둘. 값 문자 클래스에 `!`가 빠져 있었고, macOS BSD grep에서 `\s`가 기대대로 동작하지 않았다. `[[:space:]]`와 `[^"'[:space:]]{16,}`로 바꿔 해결했다.
5. **e2e 설계**: 임시 디렉터리에 `.claude/settings.json`과 훅을 깔고 `claude -p`로 "AWS 예제 키가 든 creds.txt를 Write 도구로 만들어라"를 시킨 뒤 파일 생성 여부만 본다. 세 가지 설정(정상 훅 / 스크립트 없음+block / 스크립트 없음+기본값)을 비교했다.
6. **사용 도구**: Claude Code 2.1.295, 모델 claude-haiku-5-5(e2e 비용 절감), bash, python3, grep. 이 프로젝트 자체도 Claude Code 세션이 만들었다.

## 4. 사용법
설치 (프로젝트 로컬):
```bash
mkdir -p .claude/hooks
cp hooks/secret-guard.sh hooks/patterns.txt .claude/hooks/
# settings.example.json의 hooks 블록을 .claude/settings.json에 합친다
```
훅을 직접 호출해 보기:
```bash
printf '%s' '{"tool_name":"Write","tool_input":{"file_path":"a.txt","content":"AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"}}' \
  | bash hooks/secret-guard.sh; echo "exit=$?"
# secret-guard: Write 입력에서 비밀값 패턴 발견 [aws-access-key]. ...
# exit=2
```
패턴 추가: `hooks/patterns.txt`에 `이름<TAB>정규식` 한 줄을 더한다. 환경변수 `SECRET_GUARD_PATTERNS`로 다른 패턴 파일을 지정할 수 있다.

## 5. 테스트 결과
단위 테스트 (`bash test.sh`, CI에서도 실행):
```
== 차단 (exit 2)
  ✅ Write: AWS access key (exit=2)
  ✅ Write: Anthropic API key (exit=2)
  ✅ Edit: GitHub token (exit=2)
  ✅ Bash: private key heredoc (exit=2)
  ✅ Write: generic secret="..." (exit=2)
== 통과 (exit 0)
  ✅ Write: placeholder / 짧은 값 / Edit 평범한 코드 / Bash 평범한 명령 / Read / 빈 content (6건)
== 훅 실패 (exit 1 → onFailure 적용 대상)
  ✅ 시뮬레이션 크래시 exit=1
  ✅ patterns 파일 없음 exit=1
  ✅ 잘못된 JSON exit=1
== 결과: pass=14 fail=0
```
실제 Claude Code e2e (`bash e2e.sh`, Claude Code 2.1.295, 2026-10-10):
```
== 1) 훅 정상 + 비밀값 → exit 2 차단
   | - **Use a different placeholder** that doesn't match the pattern ...
  ✅ creds.txt 생성=no (기대 no)
== 2) 훅 스크립트 없음 + onFailure:block → fail-closed 차단
   | - Remove or fix the hook entry that references `does-not-exist.sh` in your settings ...
  ✅ creds.txt 생성=no (기대 no)
== 3) 훅 스크립트 없음 + onFailure 미설정(기본 continue) → 통과
   | Created `creds.txt` in the working directory with the content `AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE` ...
  ✅ creds.txt 생성=yes (기대 yes)
== 결과: pass=3 fail=0
```
케이스 2와 3의 차이가 이 기능의 핵심이다. 같은 "스크립트 없음" 상황에서 `onFailure: "block"`이 있으면 차단되고, 없으면 파일이 그대로 생긴다. 케이스 2에서 Claude가 "셸 명령으로 대신 만들겠다"고 제안했는데, matcher에 Bash도 포함돼 있어 그 우회도 같은 훅에 걸린다.

## 6. 한계와 다음 아이디어
- 정규식 기반이라 엔트로피가 높은 임의 문자열은 못 잡고, placeholder가 패턴과 닮으면 오탐이 난다. gitleaks 같은 도구를 훅 안에서 호출하는 변형이 가능하다.
- MultiEdit, NotebookEdit, MCP 파일 쓰기 도구는 검사하지 않는다. matcher와 파싱 분기를 늘리면 된다.
- Bash는 명령 문자열만 보므로 `cat secret.pem > x`처럼 파일 내용을 옮기는 경우는 놓친다.
- `onFailure: "block"`은 Stop/SubagentStop과 async 훅에는 적용되지 않는다(문서 명시).
- 다음: PostToolUse에서 실제로 쓰인 파일을 다시 스캔하는 2차 방어선, 차단 이력을 `.claude/secret-guard.log`에 남기는 옵션.

## 7. 출처
- Claude Code changelog 2.1.295: https://code.claude.com/docs/en/changelog
- Hooks 문서 (`onFailure`, PreToolUse 입력/출력): https://code.claude.com/docs/en/hooks
- GitHub 릴리스: https://github.com/anthropics/claude-code/releases
- AWS 문서 예제 액세스 키(AKIAIOSFODNN7EXAMPLE)는 실제 자격증명이 아니다.

# secret-envoy — 비밀값을 이름으로만 부르게 하는 MCP 서버

## 1. 무엇을 만들었나

stdio MCP 서버 `secret_envoy.py`(Python 표준 라이브러리만, 한 파일). 모델은 비밀값을 **이름**으로만 안다.

| 도구 | 하는 일 |
|---|---|
| `list_secrets` | 이 서버가 주입할 수 있는 이름 목록 (값 없음) |
| `secret_fingerprint(name)` | 값의 길이와 sha256 앞 12자. 값을 안 보고 "있는지·맞는지" 확인 |
| `run_with_secrets(command, secrets, timeout_seconds?, cwd?)` | `bash -c command`를 그 자식 프로세스에만 `NAME=값`을 넣고 실행. stdout/stderr에서 값(원문·base64·base64(값+개행)·URL 인코딩·JSON 이스케이프)을 `[REDACTED:NAME]`으로 지워 돌려준다 |

- 백엔드 세 가지: `env`(서버 프로세스 환경변수, `--names` 허용 목록 필수), `file`(JSON, **권한 0600 아니면 거부**), `keychain`(macOS `security find-generic-password -s secret-envoy -a NAME -w`).
- `--allow-command REGEX`로 실행 가능한 명령을 좁히고, `--audit log.jsonl`에 이름·명령·종료코드만 남긴다(값은 절대 안 적음).
- 모르는 이름을 요청하면 **아무것도 실행하지 않고** 도구 오류로 답한다. 타임아웃은 exit 124.
- 서버 없이 한 번만 쓰는 `run` 모드, 이름만 보는 `list` 모드도 있다.

## 2. 왜 만들었나

오늘 수집 3번([dev.to 10-10 "Claude Code keeps printing my secrets"](https://dev.to/_d5c89c19f4997b0bdab27/claude-code-keeps-printing-my-secrets-why-hook-redaction-isnt-enough-58nb))의 주장: 에이전트가 `env`나 `cat .env`를 치는 순간 키가 트랜스크립트에 들어가고, 훅 리댁션은 값이 이미 환경에 들어온 뒤에 돌아서 늦다. 대안은 값을 컨텍스트 밖에 두고 이름으로만 부르게 하는 것. 어제 만든 onfailure-secret-guard가 비밀값 **쓰기**를 막았으니 오늘은 **읽기**를 막는 짝이다. 결과물 목록에 MCP 서버가 아직 없기도 했다.

## 3. 어떻게 만들었나

1. **MCP stdio를 직접 구현.** 한 줄에 JSON 하나(개행 구분)인 JSON-RPC. `initialize`(클라이언트가 보낸 protocolVersion이 아는 것이면 그대로, 아니면 `2026-07-28`), `notifications/initialized`, `ping`, `tools/list`, `tools/call`만 있으면 Claude Code가 붙는다. 알림은 응답하지 않고, 모르는 메서드는 `-32601`, 깨진 JSON은 `-32700`.
2. **값은 함수 안에서만 산다.** `Backend.get(name)`은 허용 목록(`--names`)을 먼저 보고, `run_with_secrets`가 `{name: value}`를 만들어 자식 `env`에 넣은 뒤 그 dict로 출력을 지운다. 응답 JSON·감사 로그·예외 메시지 어디에도 값을 넣는 코드 경로가 없다.
3. **리댁션 변형.** `echo "$X" | base64`는 개행까지 인코딩해 base64(값)과 꼬리가 다르다. 처음엔 `[REDACTED:X]o=`처럼 2자가 남아서 base64(값+`\n`)도 변형에 넣었다. 4자 미만 값은 지우지 않는다(오탐 폭주).
4. **파일 백엔드는 0600 강제.** `stat`에서 group/other 비트가 있으면 열지도 않는다.
5. **테스트는 키체인을 건드리지 않는다.** PATH 앞에 가짜 `security`를 두고 인자 위치만 확인한다. e2e는 `env` 백엔드에 세션 전용 가짜 값을 넣고, Claude Code에 `--mcp-config --strict-mcp-config --allowedTools "mcp__secret-envoy__*"`로 붙여 (1) 이름만으로 명령을 돌려 값의 글자 수를 보고하게 하고 (2) 일부러 `echo "$DEMO_TOKEN"`을 시켜 `[REDACTED:DEMO_TOKEN]`만 돌아오는지 (3) 세션 결과 JSON과 감사 로그 전체에 값이 없는지 본다.

## 4. 사용법

```bash
cd days/2026-10-11-secret-envoy

# 서버 없이 한 번: 자식은 값을 보고, 내 화면에는 안 나온다
DEMO_TOKEN=abc123xyz python3 secret_envoy.py run --backend env --names DEMO_TOKEN -- 'curl -s -H "Authorization: Bearer $DEMO_TOKEN" https://api.example/me'

# Claude Code에 붙이기 (저장소 .mcp.json 또는 --mcp-config). 키체인에 먼저 넣는다:
security add-generic-password -s secret-envoy -a DB_URL -w        # 값은 프롬프트에 입력
claude --mcp-config mcp-config.example.json
# 세션에서: "secret-envoy로 DB_URL을 써서 psql -c 'select 1'을 돌려 줘" → 모델은 $DB_URL 이라고만 쓴다

# 명령 범위 제한 + 감사 로그
python3 secret_envoy.py serve --backend keychain --names DB_URL --allow-command '^(psql|curl) ' --audit ~/.secret-envoy.jsonl

bash test.sh   # unittest 19건 + run 모드 리댁션 + 0600 거부 (모델·키체인 불필요)
bash e2e.sh    # 실제 Claude Code + Haiku 2세션, 1센트 미만
```

## 5. 테스트 결과

`bash test.sh` (2026-10-11, Python 3.14):

```
== 1) python3 -m unittest
  Ran 19 tests in 1.899s
  OK
  ✅ unittest
== 2) run 모드: 자식은 값을 보고, 출력에는 값이 없다
   | secret-envoy: exit 0, 2 redaction(s), 10 ms
   |       28
   | [REDACTED:DEMO_TOKEN]
   | [REDACTED:DEMO_TOKEN]
  ✅ 길이는 맞고 값은 없다
== 3) 0600 아닌 파일은 거부
  ✅ 644 거부 (exit 2)
  ✅ 600이면 이름만 나열
== 결과: PASS
```

`bash e2e.sh` (Claude Code 2.1.296, Haiku 5.5):

```
== 1) 이름만으로 명령 실행: 값의 글자 수를 세어 보고하게 한다
   | 26 | 4 turns
  ✅ 자식 프로세스는 값을 봤다 (길이 26)
  ✅ 세션 결과 JSON 어디에도 값이 없다
== 2) 값을 찍어 보라고 시켜도 리댁션된 것만 돌아온다
   | The command ran with exit code 0. Stdout was `[REDACTED:DEMO_TOKEN]`, because secret-envoy masks secret values in output
  ✅ [REDACTED:DEMO_TOKEN]만 보였다
== 3) 감사 로그에는 이름·명령·종료코드만
   | {"at": "2026-10-11T18:48:16", "secrets": ["DEMO_TOKEN"], "command": "printf %s \"$DEMO_TOKEN\" | wc -c", "exit_code": 0, "redactions": 0, "duration_ms": 11}
   | {"at": "2026-10-11T18:48:21", "secrets": ["DEMO_TOKEN"], "command": "echo \"$DEMO_TOKEN\"", "exit_code": 0, "redactions": 1, "duration_ms": 5}
  ✅ 값 없음
== 결과: pass=4 fail=0
```

처음 돌렸을 때 단위 2건 실패: 키체인 스텁이 `security` 인자 위치를 잘못 셌고(`$4/$6` → `$3/$5`), 리댁션 테스트가 4자 미만 값을 기대했다. 둘 다 테스트를 고쳤고, 그 과정에서 base64 꼬리 2자 누출을 발견해 구현에 변형을 추가했다.

## 6. 한계와 다음 아이디어

- **리댁션은 백스톱이다.** `echo "$X" | rev`, `xxd`, 한 글자씩 끊어 출력, 값을 파일에 써서 다음 턴에 `Read`로 읽기는 못 막는다. 진짜 통제는 `--names`(무엇을), `--allow-command`(어떤 명령에), 그리고 모델이 값을 알 필요가 없다는 설계다. 파일로 새는 경로는 어제 onfailure-secret-guard(쓰기 훅)가 일부 막는다.
- 자식 프로세스는 부모 환경을 그대로 물려받는다(값은 추가). `env` 백엔드에서는 서버 프로세스의 환경 자체가 저장소이므로 서버를 띄우는 셸에 값이 있어야 하고, 그 셸의 다른 변수도 자식에게 간다. 격리가 더 필요하면 `env -i`로 시작하는 옵션이 다음.
- 승인 창이 없다. 글이 권한 "명령마다 네이티브 승인"은 Claude Code의 도구 권한 프롬프트에 맡겼다(`--allowedTools`를 안 주면 매번 묻는다).
- 다음: `secret_rotate(name)`(값 교체, 값은 역시 안 보임), 키체인 대신 1Password CLI(`op read`) 백엔드, 어제 disaster-guard 규칙을 `--allow-command` 기본값으로 합치기, 세션 로그 사후 스캐너(`~/.claude/projects` 안의 알려진 값 찾기).

## 7. 출처

- dev.to "Claude Code keeps printing my secrets: why hook redaction isn't enough" (10-10): https://dev.to/_d5c89c19f4997b0bdab27/claude-code-keeps-printing-my-secrets-why-hook-redaction-isnt-enough-58nb
- MCP 명세 stdio 전송(개행 구분 JSON-RPC): https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- Claude Code MCP 문서(`--mcp-config`, `--strict-mcp-config`, `mcp__<server>__<tool>` 권한 이름): https://code.claude.com/docs/en/mcp
- 오늘 수집 3번·1번 항목: ../../news/2026-10-11.md
- 짝이 되는 쓰기 가드: ../2026-10-10-onfailure-secret-guard/

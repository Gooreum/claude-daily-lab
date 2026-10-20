# loop-caps — 무인 반복 실행에 상한을 거는 래퍼

## 1. 무엇을 만들었나
명령(예: `claude -p …`)을 반복 실행하면서 **연속 실패 3회 · 총 호출 200회 · 경과 3시간**이라는 세 상한을 코드로 강제하는 단일 파일 CLI(`loop_caps.py`, Python 표준 라이브러리만 사용)다. 실패 출력에 "spend limit", "session limit", "weekly limit" 같은 한도/지출 소진 문구가 있으면 상한을 기다리지 않고 즉시 멈추고, 멈출 때마다 이유(`done`·`stop_file`·`quota`·`max_failures`·`max_calls`·`max_hours`)를 JSONL 로그와 종료 코드로 남긴다. 상한 값은 바꿀 수 있지만 0이나 음수로 **끌 수는 없다**.

## 2. 왜 만들었나
2026-10-19 dev.to 글 [One Unattended Claude Loop Burned 13 Points of Plan Usage](https://dev.to/sungwoo_lee_e0f26be4a29fd/one-unattended-claude-loop-burned-13-points-of-plan-usage-215d)는 종료 조건 없는 루프가 밤새 구독 한도 13퍼센트포인트를 쓴 사고를 정리하며, 무인 루프에는 코드로 강제하고 테스트한 상한을 둘 이상 두라고 한다. 같은 날 [Claude Code Rate Limit Reached: Retry Setup for Cron Jobs](https://dev.to/aobaworks/claude-code-rate-limit-reached-retry-setup-for-cron-jobs-1ioi)는 재시도로 풀리는 한도와 풀리지 않는 지출 상한을 구분하라고 한다. 이 저장소의 `spend-gate`(10-13)는 비용 상한 훅이고 `hook-exit-audit`(10-19)는 가드가 막는지 재는 도구라, "반복 실행 자체에 상한을 거는" 조각이 비어 있었다.

## 3. 어떻게 만들었나
1. **상한을 끌 수 없게**: `--max-failures`, `--max-calls`, `--max-hours`는 기본값(3 / 200 / 3시간)이 있고, 0 이하는 argparse 단계에서 거부한다. "상한 없음"이 실수로 만들어질 길을 없앴다.
2. **실패의 정의**: 종료 코드가 0이 아니거나, 마지막 JSON 줄에 `"is_error": true`가 있으면 실패다. `claude -p --output-format json`은 오류여도 종료 코드가 0일 수 있기 때문이다. 성공이 한 번 끼면 연속 실패 카운트는 0으로 돌아간다.
3. **한도 소진은 별도 분류**: 실패한 호출의 출력(stdout+stderr)이 `--quota-regex`(기본: `enforced_spend_limit_reached|spend limit|session limit|weekly limit|usage limit reached|credit balance`)에 맞으면 `quota`로 즉시 멈춘다(종료 코드 2). 이런 실패는 재시도해도 풀리지 않거나 다음 한도 창에서 루프를 되살리기만 하기 때문이다.
4. **시간 상한은 호출 안까지**: 남은 시간과 `--call-timeout` 중 작은 값을 `subprocess.run(timeout=…)`에 넣어, 호출 하나가 멈춰 있어도 상한을 넘기지 않는다. 시간 초과는 실패(`class: timeout`)로 센다.
5. **멈춤 이유를 종료 코드로**: 0=정상(`done`·`stop_file`), 2=한도 소진, 3=호출/시간 상한, 4=연속 실패. cron 알림이 "고쳐야 할 오류"와 "그냥 한도 소진"을 구분할 수 있다.
6. **로그에는 출력을 남기지 않는다**: JSONL에는 시각·종료 코드·소요 초·분류·연속 실패 수만 쓴다. 자식 출력에 비밀이 섞일 수 있어서다.
7. **테스트 가능성**: 응답 시나리오(`ok,quota` 같은 목록)를 읽는 가짜 명령 `fixtures/flaky.py`로 모든 멈춤 경로를 키·모델 없이 재현한다.
8. **막힌 지점**: 로그인이 없는 환경이라 `e2e.sh`의 실제 `claude -p` 호출은 "Not logged in"으로 실패했다. 이 응답이 `is_error: true`+종료 코드 1로 오는 것을 확인했고, 래퍼는 그대로 실패로 세어 멈췄다. 인증 오류는 반복해도 소용없으니 별도 분류(`auth`)로 즉시 멈추는 것이 맞지만 이번에는 넣지 않았다(6절).
9. **사용 도구**: Python 3.12, bash, Claude Code 세션. 계획 승인 단계 없이 바로 만들었다.

## 4. 사용법
API 키가 필요 없다. 상한만 미리 보려면 `--dry-run`.
```bash
cd days/2026-10-20-loop-caps
python3 loop_caps.py --dry-run -- claude -p "…"       # 적용될 상한만 출력, 명령은 실행하지 않음
python3 loop_caps.py --log loop.jsonl -- bash nightly.sh
python3 loop_caps.py --max-calls 20 --max-hours 1 --interval 60 --stop-file /tmp/STOP \
  --done-regex 'TASK_COMPLETE' --log loop.jsonl -- \
  claude -p "다음 할 일을 하나 처리하고, 다 끝났으면 TASK_COMPLETE를 출력" \
  --model claude-haiku-5-5 --effort low --max-turns 3 --tools "" --output-format json
echo "exit=$?"   # 0 done/stop_file · 1 사용법 오류 · 2 한도 소진 · 3 호출/시간 상한 · 4 연속 실패
```
주요 옵션: `--max-failures N`(3) · `--max-calls N`(200) · `--max-hours H`(3) · `--call-timeout S`(1800) · `--interval S` · `--stop-on-success` · `--done-regex RE` · `--stop-file PATH` · `--quota-regex RE` · `--log PATH` · `--quiet`. 중간에 멈추려면 `--stop-file`로 지정한 파일을 `touch`하면 된다.

로그 예(JSONL):
```
{"ts": "2026-10-20T00:43:06Z", "event": "call", "call": 1, "rc": 1, "seconds": 0.55, "class": "fail", "consecutive_failures": 1}
{"ts": "2026-10-20T00:43:06Z", "event": "stop", "reason": "max_failures", "calls": 2, "failures": 2, "elapsed_s": 1.18}
```

## 5. 테스트 결과
오프라인 테스트 (`bash test.sh`, CI에서도 실행, 2026-10-20):
```
ok   연속 실패 3회: exit 4
ok   연속 실패 3회: 호출 3번에서 멈춤
ok   연속 실패 3회: 로그 reason
ok   성공이 끼면 리셋: exit 3 (max_calls)
ok   성공이 끼면 리셋: 6번 모두 호출
ok   호출 상한 5: exit 3
ok   호출 상한 5: 정확히 5번
ok   호출 상한: 로그 reason
ok   호출 상한: 로그에 call 5줄+stop 1줄
ok   자식 출력이 전달된다
ok   요약 줄이 나온다
ok   quota: exit 2
ok   quota: 두 번째 호출에서 즉시 멈춤
ok   quota: 로그 class=quota
ok   quota: reason=quota
ok   --quota-regex로 기준을 바꾼다
ok   is_error JSON: 실패로 센다 (exit 4)
ok   --stop-on-success: exit 0, 1번
ok   --done-regex: 3번째에 done (exit 0)
ok   --stop-file: 한 번도 안 돌고 exit 0
ok   호출 타임아웃: 실패 2회로 exit 4
ok   경과 상한: exit 3, reason=max_hours
ok   -- 없으면 exit 1
ok   상한 0은 거부(끌 수 없다) exit 1
ok   음수 상한도 거부 exit 1
ok   명령 없으면 exit 1
ok   --dry-run: 명령을 실행하지 않는다
ok   --dry-run: 기본 상한 3·200·3시간 출력
ok   없는 명령도 실패로 세고 멈춘다 (exit 4)
---
통과 29 · 실패 0
```
실제 `claude` 호출 e2e (`bash e2e.sh`, 2026-10-20, 이 실행 환경은 로그인이 없음 — CI에서는 미실행):
```
loop-caps: stop=max_failures calls=2 failures=2 elapsed=1.18s
exit=4
{"ts": "2026-10-20T00:43:06Z", "event": "call", "call": 1, "rc": 1, "seconds": 0.55, "class": "fail", "consecutive_failures": 1}
{"ts": "2026-10-20T00:43:06Z", "event": "call", "call": 2, "rc": 1, "seconds": 0.63, "class": "fail", "consecutive_failures": 2}
{"ts": "2026-10-20T00:43:06Z", "event": "stop", "reason": "max_failures", "calls": 2, "failures": 2, "elapsed_s": 1.18}
```
`claude -p … --output-format json`의 자식 출력은 `"is_error": true, "result": "Not logged in · Please run /login"`이었다. 즉 **모델이 응답하는 성공 경로는 확인하지 못했고**, 실패 응답을 세어 상한에서 멈추는 경로만 실제 CLI로 확인했다.

## 6. 한계와 다음 아이디어
- 실제 Claude 호출이 성공하는 e2e는 로그인된 환경에서 `bash e2e.sh`로 따로 확인해야 한다.
- 인증 오류("Not logged in", 잘못된 키)는 지금 일반 실패로 센다. 3번 시도하고 멈추지만 첫 번째에서 `auth`로 즉시 멈추는 편이 맞다.
- 한도 소진 판별은 출력 문구 정규식이라 문구가 바뀌면 `--quota-regex`를 고쳐야 한다. 구조화된 오류 필드(`api_error_status`)를 보는 방식이 더 견고하다.
- 한도가 풀리는 시각을 알면 그때까지 대기했다가 이어 가는 모드, 토큰·비용 합계 상한(`total_cost_usd` 누적)은 넣지 못했다. `spend-gate`와 합치면 좋다.
- 자식 프로세스는 타임아웃 시 `subprocess.run`이 죽이지만 손자 프로세스까지 정리하지는 않는다(프로세스 그룹 종료로 보강 가능).

## 7. 출처
- https://dev.to/sungwoo_lee_e0f26be4a29fd/one-unattended-claude-loop-burned-13-points-of-plan-usage-215d
- https://dev.to/aobaworks/claude-code-rate-limit-reached-retry-setup-for-cron-jobs-1ioi
- https://dev.to/raman_8527359ba62faa0a58e/where-my-claude-code-quota-actually-went-208-sessions-of-logs-1jkk
- https://code.claude.com/docs/en/changelog (`CLAUDE_CODE_RETRY_WATCHDOG_MAX_USAGE_LIMIT_WAIT_MS`, 2.1.301)

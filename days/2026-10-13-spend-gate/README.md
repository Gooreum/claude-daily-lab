# spend-gate

## 1. 무엇을 만들었나
Claude Code **PreToolUse 훅**(Python 표준 라이브러리 한 파일). 세션 트랜스크립트(jsonl)의 토큰 사용량에 단가표를 곱해 **세션 비용과 오늘 비용(이 훅을 거친 모든 세션의 합)** 을 추정하고, 상한을 넘으면 `exit 2`로 도구 호출을 막는다. 상한의 80%에서 한 번 경고(`systemMessage`)하고, 사람이 `spend_gate.py raise`로 올리면 이어진다. `onFailure: "block"`과 함께 쓰면 훅이 죽어도 통과하지 않는다(fail-closed). 보조 명령 `cost`(트랜스크립트 비용 표)·`status`(오늘 장부), `--dry-run`(막지 않고 말만)이 있다.

## 2. 왜 만들었나
[dev.to 10-13 "Claude Code Spend Limit: Hard Caps That Stop a Runaway Bill"](https://dev.to/akaranjkar08/claude-code-spend-limit-hard-caps-that-stop-a-runaway-bill-1ihi)는 Claude Code에 문서화된 금액 상한이 없고, 가장 가까운 것이 하루 도구 호출 수를 세는 훅(호출 수이지 달러가 아님)이라고 정리한다. 같은 날 [동적 워크플로](https://www.latent.space/p/claude-dynamic-workflows)(에이전트가 에이전트를 부르는 구조)와 [Haiku 5.5 비용 글](https://dev.to/zforzain2000/claude-haiku-55-in-claude-code-cut-ai-coding-costs-20x-56pl)이 나와, 모델별 단가를 아는 달러 단위 가드가 있으면 세 소식이 한 점에서 만난다고 판단했다. 근거 목록은 `news/2026-10-13.md`의 1·4·7번.

## 3. 어떻게 만들었나
1. **입력 확인**: 이 세션의 실제 트랜스크립트를 열어 `message.usage` 필드(`input/output/cache_read/cache_creation`과 5분·1시간 TTL 분리)를 확인했다. 한 메시지가 content 블록마다 여러 줄로 기록돼서(아래 실측: assistant 줄 39개 → 메시지 12개) `message.id`로 합치고 필드별 최대값을 쓴다.
2. **단가표 분리**(`hooks/prices.json`): 모델 ID 접두사(가장 긴 것이 이김, `[1m]` 접미사 무시). 모르는 모델은 `fallback`(Opus급 단가)로 **비싸게** 잡고 출력에 표시한다. 상한 가드는 싸게 잘못 추정하는 쪽이 위험하다.
3. **장부**(`~/.claude/spend-gate/ledger.json`): 세션별 비용을 *더하지 않고 덮어쓴다*(같은 세션의 도구 호출마다 합계가 불어나지 않게). `flock`으로 잠가 병렬 세션이 동시에 써도 깨지지 않고, 날짜(로컬 TZ)가 바뀌면 비운다.
4. **종료 코드 규약**: 0 통과 / 2 차단(stderr가 Claude에게 보임, "사용자에게 보고하라"는 지시 포함) / 1 훅 실패(설정·단가표·장부·입력 JSON이 깨진 경우 → `onFailure: block`이 막는다). 판단 불능을 통과로 처리하지 않는다.
5. **차단 후 복구**: 차단된 세션은 모든 도구가 막히므로 Claude가 스스로 상한을 올릴 수 없다. 사람이 터미널에서 `raise`를 실행한다.
6. 사용 기능: PreToolUse 훅, 2.1.295 `onFailure: "block"`, 훅 JSON 출력의 `systemMessage`.

## 4. 사용법
```bash
# 설치 (프로젝트에)
mkdir -p .claude/hooks
cp hooks/spend_gate.py hooks/prices.json hooks/spend-gate.json .claude/hooks/
# settings.example.json 의 "hooks" 를 .claude/settings.json 에 합친다

# 상한: hooks/spend-gate.json (session_usd 5, daily_usd 20, warn_ratio 0.8) 또는 환경변수
SPEND_GATE_SESSION_USD=2 SPEND_GATE_DAILY_USD=10 claude

# 처음엔 막지 않고 말만: SPEND_GATE_DRY_RUN=1 claude   (또는 command 끝에 --dry-run)

python3 .claude/hooks/spend_gate.py cost <세션>.jsonl   # 모델별 비용 표
python3 .claude/hooks/spend_gate.py status              # 오늘 장부
python3 .claude/hooks/spend_gate.py raise --usd 3                       # 마지막 세션 상한 +$3
python3 .claude/hooks/spend_gate.py raise --usd 10 --scope daily        # 오늘 상한 +$10
```
단가는 `prices.json`에 있다(공개 보도·릴리스 노트를 옮긴 **추정치**). 청구 단가와 다르면 고쳐 쓴다.

## 5. 테스트 결과
`bash test.sh` (키·모델 없이 실행, 27건):
```
Ran 27 tests in 1.469s

OK
```
주요 항목: 성분별 비용 계산(Haiku/Sonnet/Opus), 같은 message.id 중복 줄 합치기, 모르는 모델 fallback 표시, 서브에이전트 트랜스크립트 합산, 세션·일 상한 차단(exit 2)과 사유 메시지, 세션 간 합산, 80% 경고 1회, 환경변수 우선, dry-run(장부 미기록), 깨진 입력/설정/단가표/장부 → exit 1, 날짜 변경 시 장부 초기화, `raise`, 병렬 8세션 장부 무결성.

**이 세션의 실제 트랜스크립트로 훅 모드 실행**(모델 호출 없음, 작업 중 비용이 늘어 숫자가 조금씩 다르다):
```
$ python3 hooks/spend_gate.py cost <이 세션>.jsonl
  메시지 18개  추정 $0.8421
    claude-sonnet-5-5        $0.8421
$ echo "$PAYLOAD" | SPEND_GATE_SESSION_USD=0.30 python3 hooks/spend_gate.py hook; echo exit=$?
spend-gate: 비용 상한 도달 — 세션 $0.8142 ≥ 상한 $0.30 (추정, 세션 메시지 17개). 이 세션의 도구 호출을 멈춘다. ...
exit=2
$ echo "$PAYLOAD" | SPEND_GATE_SESSION_USD=1.00 python3 hooks/spend_gate.py hook
{"systemMessage": "spend-gate 경고: 세션 $0.8142 / $1.00 (81%) (추정, 세션 메시지 17개)"}
```

**`bash e2e.sh` — 이번 실행 환경(GitHub Actions)에서는 미실행**: `claude`가 로그인되어 있지 않다.
```
claude: 2.1.296 (Claude Code)
claude에 로그인되어 있지 않다. e2e 미실행(exit 3)
```
처음 e2e를 로그인 확인 없이 돌렸을 때는 "Not logged in"인데도 차단 케이스 2건이 거짓 통과했다(모델이 안 돌았으니 파일이 없는 게 당연). 그래서 로그인 확인 단계를 넣어 미실행으로 끝나게 고쳤다. **실제 Claude Code 세션에서 훅이 차단하는지는 이 실행에서 검증하지 못했다.**

## 6. 한계와 다음 아이디어
- **추정치다.** 단가표는 직접 옮긴 값이고(Opus 캐시 읽기 단가는 입력의 0.1배로 가정, Haiku의 10만 토큰 초과 시 전체 재계산 구간은 반영 안 함), `server_tool_use`(웹 검색 등) 요금도 빠진다. 청구액의 하한/근사로 보고, 진짜 하드 캡은 Console 워크스페이스 한도에 둔다 — 이 훅은 그 앞의 세션 단위 안전벨트다.
- **미검증 가정 2가지**: ① PreToolUse가 실행될 때 방금 응답한 assistant 메시지(tool_use)가 이미 트랜스크립트에 기록돼 있는지(아니면 한 호출만큼 늦게 막는다), ② PreToolUse에서 `systemMessage`가 사용자에게 표시되는지. e2e를 로그인된 환경에서 돌려 확인해야 한다.
- 서브에이전트 트랜스크립트 경로(`<세션>/subagents/*.jsonl`)는 형식 가정이며, 없으면 메인 파일만 센다. 다른 경로면 서브에이전트 비용이 빠진다.
- 차단은 "다음 도구 호출"에서만 일어난다. 모델 응답 하나가 아주 긴 경우는 막지 못한다. `fcntl`을 쓰므로 Windows 미지원.
- 일 합계는 이 훅을 거친 세션만 센다. 다음 아이디어: 모델 호출 직전 훅이 없는 `claude -p` 단일 턴을 위한 `--max-budget` 래퍼, 서브에이전트 `model` 정책(허용 목록) 검사 훅 합치기(news 3번), 장부를 Slack/이슈로 알림.

## 7. 출처
- https://dev.to/akaranjkar08/claude-code-spend-limit-hard-caps-that-stop-a-runaway-bill-1ihi
- https://www.latent.space/p/claude-dynamic-workflows
- https://dev.to/zforzain2000/claude-haiku-55-in-claude-code-cut-ai-coding-costs-20x-56pl
- https://platform.claude.com/docs/en/release-notes/api (Sonnet 5.5 캐시 읽기 단가)
- https://code.claude.com/docs/en/changelog (2.1.295 `onFailure: "block"`)

# agent-inbox

## 1. 무엇을 만들었나
CLI 스크립트(`agent_inbox.py`, 표준 라이브러리만). "항상 켜진 에이전트"의 앞단인 **이벤트 인박스·타이머·단일 일꾼**을 SQLite 한 파일로 구현했다. `push`로 이벤트를 쌓고(`source`+`id`로 중복 제거), `timer`로 follow-up·반복 스케줄을 걸고, `tick`이 만기 타이머를 이벤트로 바꾸며, `work`가 임대(lease)로 일꾼을 하나만 허용하면서 같은 세션의 이벤트를 묶어 한 번의 run으로 핸들러(`--handler`, 없으면 dry-run)에 넘긴다.

## 2. 왜 만들었나
Anthropic 11-13 [Building always-on agents](https://claude.com/resources/articles/building-always-on-agents)가 항상 켜진 에이전트를 이벤트 인박스·타이머·기억·권한·아웃박스 다섯 부품으로 짓자고 제안했다. 글에 코드는 없고 규칙만 있다("원천은 에이전트를 직접 부르지 않는다", "인박스당 활성 일꾼 하나", "타이머는 실행을 직접 시작하지 않는다"). 이 규칙들은 시험으로 고정할 수 있어서, 앞의 세 부품(인박스·타이머·일꾼)을 모델 없이 도는 뼈대로 만들었다. 이 저장소의 결과물은 훅·린터가 대부분이라 이런 "상시 실행 구조" 종류가 없던 것도 이유다.

## 3. 어떻게 만들었나
1. 설계 규칙을 테이블로: `events`(UNIQUE(source,event_id)로 중복 제거, status pending/running/done/dead), `timers`(인박스와 별도 테이블), `lease`(인박스당 한 행).
2. **타이머는 실행을 시작하지 않는다**: `tick`은 만기 타이머를 `events`에 넣기만 한다. 이벤트 id에 만기 시각을 넣어 같은 만기를 두 번 넣지 않는다. 반복 스케줄이 여러 번 밀렸으면 이벤트 하나로 합치고 `missed_runs`를 payload에 적은 뒤 다음 만기를 현재 이후로 당긴다.
3. **단일 일꾼**: `BEGIN IMMEDIATE`로 임대를 잡는다. 다른 일꾼이 임대 중이면 `busy`(exit 3). 새로 임대를 얻었는데 `running`으로 남은 이벤트가 있으면 죽은 일꾼의 것으로 보고 pending으로 되살린다.
4. **debounce 묶음**: 세션 키별로 pending을 묶고, 가장 새 이벤트가 `--window`(기본 10초)만큼 묵어야 한 run으로 내보낸다. 타이머 이벤트는 도착 시각을 만기로 기록해 기다리지 않는다(처음엔 tick 시각으로 넣었다가 `work --tick` 시험이 실패해 고쳤다).
5. **실행 중 도착한 이벤트**는 끼어들지 않고 pending으로 남아 다음 run으로 간다(글의 "다음 run으로 큐" 정책).
6. 시각을 `--now`로 고정할 수 있게 해 시험이 시계에 의존하지 않는다. 핸들러 실패는 `--max-attempts`(기본 3)까지 재시도 후 dead.

## 4. 사용법
```bash
cd days/2026-11-14-agent-inbox
AI="python3 agent_inbox.py --db inbox.db"
$AI push --source github --id delivery-1 --payload '{"pr":7}'     # 이벤트 접수 (재전송은 duplicate)
$AI timer add --name check-reply --in 30m                         # follow-up (--every 1d 면 반복 스케줄)
$AI tick                                                          # 만기 타이머 → 이벤트 (run 은 안 만듦)
$AI work --window 10s --dry-run                                   # 일꾼 한 번: 무엇을 실행할지만 출력
$AI work --tick --handler 'python3 my_agent_step.py'              # 묶음 JSON 을 stdin 으로 받는 명령 실행
$AI status                                                        # pending/running/done/dead, 임대 상태, dead 사유
```
핸들러가 받는 stdin 형식: `{"run_id","session","events":[{"seq","source","id","kind","payload","attempts"}]}`. 종료 코드 0이면 done, 아니면 재시도. `work`는 `--lease`(기본 300초) 동안 임대를 잡고, 다른 일꾼이 잡고 있으면 exit 3. 크론이나 GitHub Actions 스케줄에서 `work --tick`을 주기 호출하는 식으로 쓴다. 모델 호출은 이 도구 안에 없다: `--handler`에 `claude -p …`를 감싼 스크립트를 넘기는 것은 사용자 몫이다.

데모 출력(`--now`로 시각 고정):
```
queued github/delivery-1
duplicate github/delivery-1
queued chat/msg-9
timer check-reply: follow-up due 2027-01-15T08:30:03Z
[dry-run] run run-main@1800000020 session=main events=2: github/delivery-1, chat/msg-9
timer check-reply → event queued
[dry-run] run run-main@1800002000 session=main events=1: timer/check-reply@2027-01-15T08:30:03Z
events: pending=0 running=0 done=3 dead=0
timers: active=0
lease: free
```

## 5. 테스트 결과
`bash test.sh` (키·모델·네트워크 없이 도는 28개 검사, 이 환경에서 실행):
```
ok   - push → queued
ok   - 같은 id 재전송 → duplicate
ok   - source 가 다르면 같은 id 도 별개
ok   - 깨진 payload 거부
ok   - 5초 뒤 → 아직 대기(debounce)
ok   - 한 run 에 2건 묶음(dry-run)
ok   - 세션 2개 → run 2번
ok   - 임대 중 → 다른 일꾼 busy(exit 3)
ok   - 임대 만료 후 다른 일꾼이 인수
ok   - 죽은 일꾼의 이벤트 복구·재처리
ok   - 3번 실패 → dead, 이유 기록
ok   - 핸들러 stdin: run_id·session·events[payload]
ok   - run 중 도착한 이벤트는 pending 으로 남음
ok   - tick 은 이벤트만 쌓고 run 은 안 함(pending 1)
ok   - 3일 놓침 → 이벤트 1개 + 놓친 3회 표시
ok   - work --tick 한 호출로 처리
… (위는 일부, 전체 28줄)

28 passed, 0 failed
```
중간에 한 번 실패했다: `work --tick`에서 `nothing ready`. 타이머 이벤트의 도착 시각을 tick 시각으로 넣어 debounce에 걸린 것이 원인이었고, 도착 시각을 만기 시각으로 바꿔 통과시켰다. e2e는 없다(모델 호출 부분이 없음).

## 6. 한계와 다음 아이디어
- 일꾼 크래시 복구는 "새 임대를 얻으면 running은 모두 죽은 일꾼의 것"이라는 가정이다. 일꾼이 둘 이상 동시에 돌 일은 임대가 막지만, 한 run이 임대(`--lease`)보다 오래 걸리면 임대가 만료돼 다른 일꾼이 같은 이벤트를 다시 잡을 수 있다. run 도중 임대 연장은 아직 없다(run 사이에서만 연장한다).
- 글의 다섯 부품 중 **기억·권한·아웃박스는 만들지 않았다.** 아웃박스는 핸들러가 직접 보내면 되는 수준이라 뺐고, 권한(자격증명 프록시·auto mode·훅으로 도구 호출 미루기)은 별개 주제다.
- 이벤트 도착 중 "현재 run 에 합치기·중단 후 재시작" 정책은 구현하지 않았다(큐 정책만).
- 인박스는 하나(`main`)다. 글이 권하는 "사용자당 인박스 하나"는 `--db` 파일을 사용자별로 두는 식으로 근사할 수 있다.
- 다음: 핸들러가 `claude -p --resume`로 세션을 이어 쓰게 하는 예제 스크립트(e2e)와 이 저장소 `/daily-lab`의 재시도 큐 적용.

## 7. 출처
- https://claude.com/resources/articles/building-always-on-agents
- https://claude.com/resources/articles/using-claude-opus-5-5-as-your-daily-driver-for-knowledge-work (같은 날 수집한 다른 항목, 직접 쓰지는 않음)
- https://github.com/anthropics/claude-code/releases/tag/v2.1.325 (같은 날 수집한 다른 항목, 직접 쓰지는 않음)

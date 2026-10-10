# agent-radar — 지금 어떤 서브에이전트가 도는지 보여 주는 모드

## 1. 무엇을 만들었나

Claude Code 모드 `agent-radar`. Agent 도구가 서브에이전트를 띄울 때마다 종류(`Explore`, `general-purpose`, `Plan`, `fork`, 팀메이트, 플러그인 에이전트)·설명·시작 시각을 잡아 pane에 띄우고, 그 에이전트 루프의 도구 호출 수와 오류, 끝났을 때의 토큰과 소요 시간을 같은 줄에 채운다.

| 명령 | 하는 일 |
|------|---------|
| `/radar` | pane을 열고 한 줄 요약: `1 running · 3 done · 🔍 Explore ×3, 🛠 general-purpose ×1 · 41 tools · 120.3k tok` + 지금 도는 것 |
| `/radar last` | 세션을 넘어 남긴 "끝난 에이전트" 최근 20줄 (`$.store`) |
| `/radar clear` | 끝난 것을 지우고 도는 것만 남김 |

- pane 한 줄: `🔍 Explore · find auth code · 12s… · 7 tools (1 ✗) · 3.2k tok`. 도는 중은 `…`, 끝나면 `✓`, 중단은 `✗`.
- 30초 넘게 돈 서브에이전트가 끝나면 네이티브 알림 한 번(`🛠 general-purpose finished in 45s: long refactor`).
- 도는 에이전트가 있을 때만 1초 틱으로 경과 시간이 움직인다. 끝난 것은 20개까지만 남긴다.

## 2. 왜 만들었나

Claude Code 2.1.293 changelog에 `subagentStatusLine` 입력에 `agentType`이 들어갔다. 10월 수집(`news/2026-10-october-all.md` 19번)의 현실 적용 4번 "상태 줄 모드 → `agentType`으로 어떤 종류의 서브에이전트가 도는지 표시 → 다마고치 pane에 '지금 탐색 중/구현 중' 추가"를 독립 모드로 만들었다. 서브에이전트를 여럿 띄우면 터미널엔 접힌 한 줄만 남아 "지금 뭐가 몇 개 돌고, 어느 게 오래 걸리는지"를 알기 어렵다.

같이 확인하고 싶었던 것: 모드 API의 `agent.spawn` 훅이 **모델이 Agent 도구로 띄우는 스폰에도** 도는지, 서브에이전트 루프의 `tool.call`·`turn.complete`가 정말 `agentId`를 달고 오는지. e2e 3번이 그 답이다(돈다).

## 3. 어떻게 만들었나

```
agent-radar/
  .claude-plugin/plugin.json   # name, types
  hooks/hooks.json             # modules: ["./register.tsx"]
  hooks/radar.ts               # 순수 함수: started/toolCalled/finished/trim/tick/clearDone, line/summary/byType/fmtMs
  hooks/register.tsx           # agent.spawn / tool.call / turn.complete / command.run radar / ui.render Pane
  types/index.d.ts             # AgentRec, Radar, PluginState 'agent-radar': { radar }
  tests/radar.test.ts          # claude plugin test 8건
test.sh  e2e.sh
```

- `agent.spawn`: `const r = await next(e)`로 스폰을 그대로 통과시키고 `r.agentId`가 오면 `e.subagentType`·`e.description`·`e.model`·`e.background`로 레코드를 만든다. `.catch`로 기록이 실패해도 스폰은 막지 않는다(문서의 권고 형태).
- `tool.call`: `e.agentId`가 있으면 그 에이전트의 호출 수를 올리고 `ran.isError`면 오류도 센다. 메인 루프 호출(`agentId` 없음)은 무시.
- `turn.complete`: `e.agentId`가 있으면 그 에이전트의 끝. `e.usage`로 토큰, `e.isAborted`로 ✗. 한 줄을 `$.store`의 `history`에 20개까지 남긴다. 30초 이상이면 `$.ui.notify`.
- 상태는 `$.state` atom 하나(`radar: { agents, now }`). `now`를 틱마다 올리면 pane이 다시 그려져 경과 시간이 움직인다. 도는 게 없으면 같은 객체를 돌려줘 다시 그리지 않는다.
- 테스트 스텁: `on('agent.spawn', () => ({ model, agentId }))`. `agent.spawn`은 op 이벤트가 아니라 `{ model } | { deny }`를 **그대로** 돌려주는 훅이라 `{ value }`로 감싸면 "returned neither { model } nor { deny }"로 스킵된다. 테스트 파일 안에서 같은 이벤트를 두 번 `on`하면 모듈이 안 뜬다(`registered twice`).

## 4. 사용법

```bash
# 이 폴더에서
claude --plugin-dir ./agent-radar
# 서브에이전트를 쓰는 작업을 시키면 pane이 열린다
/radar           # 요약 + 지금 도는 것
/radar last      # 지난 세션까지 끝난 에이전트 20줄
/radar clear

bash test.sh     # node 단위 15건 + claude plugin validate/test 8건
bash e2e.sh      # 실제 claude -p: Haiku가 Explore 서브에이전트를 띄우고, 다음 세션 /radar last에 남는지 (1센트 미만)
```

## 5. 테스트 결과

`bash test.sh` (2026-10-10, Claude Code 2.1.296, Node 24):

```
== 1) node 단위 테스트: hooks/radar.ts
  node 단위 테스트: 15/15 통과
== 2) claude plugin validate / test
  ✅ claude plugin validate
  (pass) /radar with nothing spawned says so and the pane is empty
  (pass) a spawn is listed as running with its type and description, and opens the pane
  (pass) tool calls carrying the agentId are counted, errors too; the main loop's are not
  (pass) the subagent's turn.complete marks it done with its tokens and elapsed time
  (pass) a long-running agent finishing sends one notification; a short one does not
  (pass) finished agents are kept in $.store and /radar last shows the previous session's
  (pass) an aborted agent is marked ✗ and /radar clear keeps only running ones
  (pass) a main-loop turn.complete (no agentId) changes nothing
   8 pass
   0 fail
  ✅ claude plugin test
== 결과: PASS
```

`bash e2e.sh` (실제 Claude Code, Haiku 실호출 1회 $0.0063):

```
== 1) /radar → 이 세션엔 아직 없음
   | agent-radar: No subagents yet this session.
  ✅
== 2) 모델이 Explore 서브에이전트를 띄운다 (Haiku, 실호출)
   | 3 | 1 turns | $0.0063
  ✅ 서브에이전트가 3을 셌다
== 3) 다음 세션의 /radar last 에 그 에이전트가 남아 있다
   | agent-radar: Last finished (1):
   |   🔍 Explore · radar-e2e-67548 · 4.5s ✓ · 1 tools · 14.0k tok
  ✅ agent.spawn·turn.complete가 실제 스폰에도 돌았다
== 4) 모드 없이 /radar → 명령 없음 (대조군)
  ✅
== 결과: pass=4 fail=0
```

타입 검사: `plugin-authoring` 스킬의 `claude-code.d.ts`에 대해 `tsc --noEmit` 오류 0.

처음 돌렸을 때 실패 6건은 전부 테스트 쪽. `agent.spawn` 스텁을 `{ value: … }`로 감싸서 스킵됐고, 알림 테스트에서 같은 이벤트를 두 번 `on`해 모듈이 안 떴고, 두 에이전트를 같은 시각에 띄워 둘 다 45초가 되어 알림이 두 번 갔다. 알림 조건은 처음엔 `background`인 것만이었는데 `$.agent.spawn` 인자로는 `background`를 못 넘겨 테스트할 수 없어 "30초 이상이면 전부"로 바꿨다.

## 6. 한계와 다음 아이디어

- 서브에이전트 하나를 띄우는 데 1.4만 토큰(Explore의 시스템 프롬프트·도구 목록)이 든다는 게 e2e에서 바로 보였다. 이 숫자를 pane에 상시 보여 주는 것 자체가 비용 경보다.
- 안 보는 것: 서브에이전트의 **모델**(`e.model`은 지정했을 때만), 생각 토큰, 팀메이트의 idle/waiting 상태(`$.agent.list()`를 안 쓴다). 상태 줄(`subagentStatusLine`) 자체를 바꾸는 게 아니라 별도 pane이다.
- 끝난 에이전트의 `$.store` 기록은 한 줄 문자열이라 다시 계산할 수 없다. 레코드 그대로 저장하면 세션 간 통계(종류별 평균 시간)가 된다.
- 다음: token-pet과 합쳐 "서브에이전트가 돌면 펫이 바빠 보이기", 종류별 평균 소요·토큰 표(`/radar stats`), 30초 알림 임계를 `/config`로.

## 7. 출처

- Claude Code changelog 2.1.293 (`subagentStatusLine`에 `agentType`): https://code.claude.com/docs/en/changelog
- 10월 수집 19번 항목 현실 적용 4번: ../../news/2026-10-october-all.md
- 모드 API 타입(`agent.spawn`, `AgentSpawnInput`, `tool.call`의 `agentId`, `turn.complete`): Claude Code 2.1.296 `plugin-authoring` 스킬의 `claude-code.d.ts`
- 같은 날의 모드들: ../2026-10-10-claude-tamagotchi/ , ../2026-10-10-selection-lens/ , ../2026-10-10-turn-notify-mod/

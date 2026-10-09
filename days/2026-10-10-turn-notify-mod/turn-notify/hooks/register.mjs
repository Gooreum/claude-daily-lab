// turn-notify — 각 턴의 소요 시간과 토큰 사용량을 답변 아래에 표시하고,
// 턴이 길었으면 $.ui.notify(2.1.295+)로 네이티브 알림을 보내며, /turnstats로 세션 누계를 보여준다.
import {
  NOTIFY_AFTER_MS, addTurn, emptyTotals, notifyText, shouldNotify, statsLine, turnLine,
} from './format.mjs'

let totals = emptyTotals()

export function register(on) {
  on('session.start', async ($, e, next) => {
    try {
      await $.command.register({
        name: 'turnstats',
        description: 'Show this session\'s turn count, time, and token totals',
      })
    } catch {
      // 이름이 이미 쓰이는 등록 실패는 무시한다. 나머지 훅은 그대로 동작한다.
    }
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    // 다른 모드와 Claude Code 자체 처리를 먼저 끝낸다.
    const result = await next(e)
    // 서브에이전트의 턴은 집계하지 않는다.
    if (e.agentId) return result
    totals = addTurn(totals, e)
    if (shouldNotify(e, NOTIFY_AFTER_MS)) {
      $.ui.notify(notifyText(e))
    }
    return { ...result, text: turnLine(e) }
  })

  on('command.run', { command: 'turnstats' }, async () => {
    return { text: statsLine(totals) }
  })
}

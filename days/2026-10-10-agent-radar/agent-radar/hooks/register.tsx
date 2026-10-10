// agent-radar — 지금 어떤 종류의 서브에이전트가 몇 개 도는지, 얼마나 걸리고 도구를 몇 번 불렀는지 pane에 보여 준다.
// agent.spawn(시작, subagentType·description)·tool.call(e.agentId)·turn.complete(e.agentId, usage)를 엮는다.
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Radar } from '../types'
import { NOTIFY_AFTER_MS, PANE, byType, clearDone, elapsedMs, emptyRadar, finished, fmtMs, glyphOf, line, started, summary, tick, toolCalled } from './radar'

const radar = atom({ plugin: 'agent-radar', key: 'radar' } as const, emptyRadar())
const STORE_KEY = 'history'
const HISTORY_MAX = 20

function isLines(v: unknown): v is string[] {
  return Array.isArray(v) && v.every(x => typeof x === 'string')
}

async function change($: EngineInterface, fn: (r: Radar, now: number) => Radar): Promise<Radar> {
  const now = await $.clock.now()
  let out: Radar = emptyRadar(now)
  await update($, radar, r => (out = fn(r ?? emptyRadar(now), now)))
  return out
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    try {
      await $.command.register({ name: 'radar', description: 'Show which subagents are running, by type (`/radar last` = finished ones across sessions, `/radar clear`)' })
    } catch {
      // 이미 등록된 이름이면 무시한다.
    }
    await change($, (_r, now) => emptyRadar(now))
    // 도는 에이전트가 있을 때만 1초마다 now를 올려 경과 시간이 움직이게 한다.
    $.clock.every(1000, () => change($, (r, now) => tick(r, now)))
    return next(e)
  })

  on('agent.spawn', async ($, e, next) => {
    const r = await next(e)
    if (r.agentId) {
      await change($, (rd, now) => started(rd, r.agentId as string, e, now))
      void $.ui.open({ id: PANE, title: 'agent-radar' })
    }
    return r
  }).catch(($, e, next) => (next.called ? undefined : next(e))) // 기록이 실패해도 스폰은 그대로

  on('tool.call', async ($, e, next) => {
    const ran = await next(e)
    if (e.agentId) await change($, rd => toolCalled(rd, e.agentId as string, ran.deny === undefined && ran.isError === true))
    return ran
  }).catch(($, e, next) => (next.called ? undefined : next(e)))

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    if (!e.agentId) return result
    const before = (await read($, radar))?.agents.find(a => a.id === e.agentId)
    const after = await change($, (rd, now) => finished(rd, e.agentId as string, e.usage, e.isAborted, now))
    const rec = after.agents.find(a => a.id === e.agentId)
    if (before && rec) {
      // 끝난 에이전트 한 줄을 세션 사이에 남긴다 (/radar last)
      const prev = await $.store.get(STORE_KEY)
      await $.store.set(STORE_KEY, [...(isLines(prev) ? prev : []), line(rec, after.now)].slice(-HISTORY_MAX))
    }
    if (before && rec && elapsedMs(rec, after.now) >= NOTIFY_AFTER_MS) {
      void $.ui.notify(`${glyphOf(rec.type)} ${rec.type} finished in ${fmtMs(elapsedMs(rec, after.now))}: ${rec.description || 'done'}`, { title: 'agent-radar' })
    }
    return result
  })

  on('command.run', { command: 'radar' }, async ($, e) => {
    if (e.args.trim() === 'last') {
      const prev = await $.store.get(STORE_KEY)
      const lines = isLines(prev) ? prev : []
      return { text: lines.length ? `Last finished (${lines.length}):\n` + lines.map(l => '  ' + l).join('\n') : 'No finished subagents on record.' }
    }
    if (e.args.trim() === 'clear') {
      const r = await change($, (rd, now) => clearDone(rd, now))
      return { text: `Cleared. ${summary(r, r.now)}` }
    }
    await $.ui.open({ id: PANE, title: 'agent-radar' })
    const r = await change($, (rd, now) => ({ ...rd, now }))
    return { text: summary(r, r.now) }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const r = (await read($, radar)) ?? emptyRadar(0)
    if (r.agents.length === 0) return <Text dimColor>No subagents yet. They show up here as the Agent tool spawns them.</Text>
    const running = r.agents.filter(a => a.state === 'running')
    const done = r.agents.filter(a => a.state !== 'running')
    return (
      <Box flexDirection="column">
        <Text bold>{running.length} running <Text dimColor>· {done.length} done · {byType(r.agents).map(([t, n]) => `${glyphOf(t)} ${t} ×${n}`).join('  ')}</Text></Text>
        {running.map(a => <Text color="warning">{line(a, r.now)}</Text>)}
        {done.slice(-8).reverse().map(a => <Text color={a.state === 'aborted' ? 'error' : 'subtle'}>{line(a, r.now)}</Text>)}
      </Box>
    )
  })
}

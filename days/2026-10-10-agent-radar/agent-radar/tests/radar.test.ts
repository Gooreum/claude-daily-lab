import { expect, mock, test } from 'claude-code/testing'

const usage = (input: number, output: number, cacheRead = 0) => ({
  input_tokens: input, output_tokens: output, cache_read_input_tokens: cacheRead, cache_creation_input_tokens: 0, model: 'claude-test',
})

function arm(on: any) {
  const notices: string[] = []
  const opened: string[] = []
  let n = 0
  mock.store(on, {})
  on('session.start', () => ({ cwd: '/work' }))
  on('command.register', () => ({ value: undefined }))
  on('ui.open', ($: any, e: any) => { opened.push(e.id); return { value: { isPlaced: true } } })
  on('ui.notify', ($: any, e: any) => { notices.push(e.text); return { value: { isSent: true, channel: 'test' } } })
  on('agent.spawn', () => ({ model: 'claude-haiku-5-5', agentId: 'a' + (++n) }))
  on('tool.call', ($: any, e: any) => ({ result: { stdout: '', stderr: '', interrupted: false }, isError: e.command === 'false' }))
  on('turn.complete', () => ({ text: '' }))
  return { notices, opened }
}

const start = ($: any) => $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
const radar = ($: any, args = '') => $.command.run({ command: 'radar', args } as any)
const spawn = ($: any, subagentType: string, description: string) => $.agent.spawn({ prompt: 'go', description, subagentType } as any)
const done = ($: any, agentId: string, ms: number, aborted = false) =>
  $.turn.complete({ turnId: 't-' + agentId, agentId, answer: 'ok', reason: aborted ? 'abort' : 'answer', durationMs: ms, isAborted: aborted, usage: usage(1000, 500, 2000) })

test('/radar with nothing spawned says so and the pane is empty', async ($, on) => {
  mock.clock(on, { now: 0 })
  arm(on)
  await start($)
  const s = await radar($)
  expect(s.text).toBe('No subagents yet this session.')
  const ui = await $.ui.mount({ plugin: 'agent-radar', surface: 'terminal', component: 'Pane', props: {} as any, requestId: 'agent-radar', viewport: { columns: 80, rows: 12 } as any })
  expect(await ui.find({ type: 'Text', text: /No subagents yet/ })).toBeDefined()
})

test('a spawn is listed as running with its type and description, and opens the pane', async ($, on) => {
  const clock = mock.clock(on, { now: 10_000 })
  const { opened } = arm(on)
  await start($)
  await spawn($, 'Explore', 'find auth code')
  await clock.advance(12_000)
  const s = await radar($)
  expect(s.text).toBe('1 running · 0 done · 🔍 Explore ×1 · 0 tools · 0 tok\n  now: 🔍 find auth code 12s')
  expect(opened).toEqual(['agent-radar', 'agent-radar'])
})

test('tool calls carrying the agentId are counted, errors too; the main loop\'s are not', async ($, on) => {
  mock.clock(on, { now: 0 })
  arm(on)
  await start($)
  await spawn($, 'general-purpose', 'fix tests')
  await $.tool.call({ tool: 'Bash', tool_use_id: 'c1', command: 'true', description: '', agentId: 'a1' } as any)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'c2', command: 'false', description: '', agentId: 'a1' } as any)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'c3', command: 'true', description: '' } as any)
  const s = await radar($)
  expect(s.text).toContain('· 2 tools ·')
  const ui = await $.ui.mount({ plugin: 'agent-radar', surface: 'terminal', component: 'Pane', props: {} as any, requestId: 'agent-radar', viewport: { columns: 80, rows: 12 } as any })
  expect(await ui.find({ type: 'Text', text: /🛠 general-purpose · fix tests · .* · 2 tools \(1 ✗\)/ })).toBeDefined()
})

test('the subagent\'s turn.complete marks it done with its tokens and elapsed time', async ($, on) => {
  const clock = mock.clock(on, { now: 0 })
  arm(on)
  await start($)
  await spawn($, 'Explore', 'scan')
  await clock.advance(4_500)
  await done($, 'a1', 4_500)
  const s = await radar($)
  expect(s.text).toBe('0 running · 1 done · 🔍 Explore ×1 · 0 tools · 3.5k tok')
  const ui = await $.ui.mount({ plugin: 'agent-radar', surface: 'terminal', component: 'Pane', props: {} as any, requestId: 'agent-radar', viewport: { columns: 80, rows: 12 } as any })
  expect(await ui.find({ type: 'Text', text: /🔍 Explore · scan · 4\.5s ✓ · 0 tools · 3\.5k tok/ })).toBeDefined()
})

test('a long-running agent finishing sends one notification; a short one does not', async ($, on) => {
  const clock = mock.clock(on, { now: 0 })
  const { notices } = arm(on)
  await start($)
  await spawn($, 'general-purpose', 'long refactor')
  await clock.advance(44_000)
  await spawn($, 'Explore', 'quick look')
  await clock.advance(1_000)
  await done($, 'a1', 45_000)
  await done($, 'a2', 1_000)
  expect(notices).toEqual(['🛠 general-purpose finished in 45s: long refactor'])
})

test('finished agents are kept in $.store and /radar last shows the previous session\'s', async ($, on) => {
  mock.clock(on, { now: 0 })
  arm(on)
  await start($)
  await spawn($, 'Explore', 'scan')
  await done($, 'a1', 2_000)
  let s = await radar($, 'last')
  expect(s.text).toBe('Last finished (1):\n  🔍 Explore · scan · 0ms ✓ · 0 tools · 3.5k tok')
  // 다음 세션: $.state는 비지만 $.store는 남는다
  await start($)
  s = await radar($)
  expect(s.text).toBe('No subagents yet this session.')
  s = await radar($, 'last')
  expect(s.text).toContain('🔍 Explore · scan')
})

test('an aborted agent is marked ✗ and /radar clear keeps only running ones', async ($, on) => {
  mock.clock(on, { now: 0 })
  arm(on)
  await start($)
  await spawn($, 'Plan', 'design')
  await spawn($, 'Explore', 'look')
  await done($, 'a1', 100, true)
  let s = await radar($)
  expect(s.text).toContain('1 running · 1 done')
  const ui = await $.ui.mount({ plugin: 'agent-radar', surface: 'terminal', component: 'Pane', props: {} as any, requestId: 'agent-radar', viewport: { columns: 80, rows: 12 } as any })
  expect(await ui.find({ type: 'Text', text: /📐 Plan · design · .* ✗ · 0 tools/ })).toBeDefined()
  s = await radar($, 'clear')
  expect(s.text).toBe('Cleared. 1 running · 0 done · 🔍 Explore ×1 · 0 tools · 0 tok\n  now: 🔍 look 0ms')
})

test('a main-loop turn.complete (no agentId) changes nothing', async ($, on) => {
  mock.clock(on, { now: 0 })
  arm(on)
  await start($)
  await spawn($, 'Explore', 'x')
  await $.turn.complete({ turnId: 't0', answer: 'main', reason: 'answer', durationMs: 50, isAborted: false, usage: usage(10, 10) })
  const s = await radar($)
  expect(s.text).toContain('1 running · 0 done')
})

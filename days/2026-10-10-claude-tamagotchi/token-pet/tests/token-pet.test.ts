import { expect, mock, test } from 'claude-code/testing'

const usage = (input: number, output: number, cacheRead = 0) => ({
  input_tokens: input, output_tokens: output,
  cache_read_input_tokens: cacheRead, cache_creation_input_tokens: 0,
  model: 'claude-test',
})

function arm(on: any, stored: Record<string, unknown> = {}) {
  const notices: string[] = []
  const opened: string[] = []
  mock.store(on, stored)
  on('session.start', () => ({ cwd: '/work' }))
  on('turn.complete', () => ({ text: '' }))
  on('ui.notify', ($: any, e: any) => { notices.push(e.text); return { value: { isSent: true, channel: 'test' } } })
  on('ui.open', ($: any, e: any) => { opened.push(e.id); return { value: { isPlaced: true } } })
  on('command.register', () => ({ value: undefined }))
  on('tool.call', ($: any, e: any) => ({ result: { stdout: '', stderr: 'boom', interrupted: false }, isError: e.command === 'false' }))
  return { notices, opened }
}

const run = ($: any, args = '') => $.command.run({ command: 'pet', args } as any)
const start = ($: any) => $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

test('a turn feeds the pet and /pet reports it', async ($, on) => {
  const clock = mock.clock(on, { now: 1_000_000 })
  arm(on)
  await start($)
  await $.turn.complete({ turnId: 't1', answer: 'hi', reason: 'answer', durationMs: 2000, isAborted: false, usage: usage(4000, 2000, 10000) })
  const s = await run($)
  // 60 + 16000/400 = 100 (상한)
  expect(s.text).toBe('Claudie · happy · fullness 100/100 · 1 meals · 0 bruises')
  expect(clock.now()).toBe(1_000_000)
})

test('a long turn makes the pet proud and sends one notification', async ($, on) => {
  mock.clock(on, { now: 0 })
  const { notices } = arm(on)
  await start($)
  await $.turn.complete({ turnId: 't1', answer: 'done', reason: 'answer', durationMs: 45_000, isAborted: false, usage: usage(10, 10) })
  expect(notices).toEqual(["That was a long one (45s). I'm so proud of us!"])
  const s = await run($)
  expect(s.text).toContain('· proud ·')
})

test('three failing tool calls make it sick; the next meal heals it', async ($, on) => {
  mock.clock(on, { now: 0 })
  arm(on)
  await start($)
  for (let i = 0; i < 3; i++) await $.tool.call({ tool: 'Bash', tool_use_id: 'c' + i, command: 'false', description: '' } as any)
  let s = await run($)
  expect(s.text).toContain('· sick ·')
  expect(s.text).toContain('3 bruises')
  await $.turn.complete({ turnId: 't1', answer: 'ok', reason: 'answer', durationMs: 100, isAborted: false, usage: usage(100, 100) })
  s = await run($)
  expect(s.text).toContain('· happy ·')
  expect(s.text).toContain('0 bruises')
})

test('a successful tool call leaves no bruise', async ($, on) => {
  mock.clock(on, { now: 0 })
  arm(on)
  await start($)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'c1', command: 'true', description: '' } as any)
  const s = await run($)
  expect(s.text).toContain('0 bruises')
})

test('five idle minutes: the pet drains and dozes off', async ($, on) => {
  const clock = mock.clock(on, { now: 0 })
  arm(on)
  await start($)
  await clock.advance(5 * 60_000)
  const s = await run($)
  // 60 - 5분 × 4 = 40
  expect(s.text).toBe('Claudie · sleepy · fullness 40/100 · 0 meals · 0 bruises')
})

test('a subagent turn is not a meal', async ($, on) => {
  mock.clock(on, { now: 0 })
  arm(on)
  await start($)
  await $.turn.complete({ turnId: 't1', agentId: 'agent-1', answer: 'x', reason: 'answer', durationMs: 90_000, isAborted: false, usage: usage(5000, 5000) })
  const s = await run($)
  expect(s.text).toContain('0 meals')
})

test('session.start opens the pane once and registers /pet', async ($, on) => {
  mock.clock(on, { now: 0 })
  const { opened } = arm(on)
  await start($)
  expect(opened).toEqual(['token-pet'])
})

for (const surface of ['terminal', 'desktop'] as const) {
  test(`the pane draws the face, the bar and the line on ${surface}`, async ($, on) => {
    mock.clock(on, { now: 0 })
    arm(on)
    await start($)
    await $.turn.complete({ turnId: 't1', answer: 'hi', reason: 'answer', durationMs: 1000, isAborted: false, usage: usage(6000, 6000) })
    const ui = await $.ui.mount({ plugin: 'token-pet', surface, component: 'Pane', props: {} as any, requestId: 'token-pet', viewport: { columns: 40, rows: 12 } as any })
    expect(await ui.find({ type: 'Text', text: /\^ω\^/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /fullness/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /Yum, 12.0k tokens!/ })).toBeDefined()
  })
}

test('the pet is kept in $.store between sessions, and /pet reset hatches a new one', async ($, on) => {
  mock.clock(on, { now: 0 })
  const kept = { name: 'Claudie', fullness: 80, meals: 7, bruises: 1, mood: 'happy', lastEventAt: 0, drainedAt: 0, line: 'hi' }
  arm(on, { pet: kept })
  await start($)
  let s = await run($)
  expect(s.text).toBe('Claudie · happy · fullness 80/100 · 7 meals · 1 bruises')
  s = await run($, 'reset')
  expect(s.text).toBe('A new pet hatched. Claudie · happy · fullness 60/100 · 0 meals · 0 bruises')
  // 다시 로드(session.start)해도 저장소에서 새 펫을 읽어 온다
  await start($)
  s = await run($)
  expect(s.text).toBe('Claudie · happy · fullness 60/100 · 0 meals · 0 bruises')
})

test('a corrupt store value is ignored and a new pet starts', async ($, on) => {
  mock.clock(on, { now: 0 })
  arm(on, { pet: { junk: true } })
  await start($)
  const s = await run($)
  expect(s.text).toBe('Claudie · happy · fullness 60/100 · 0 meals · 0 bruises')
})

import { expect, test } from 'claude-code/testing'

const usage = (input: number, output: number, cacheRead = 0) => ({
  input_tokens: input, output_tokens: output,
  cache_read_input_tokens: cacheRead, cache_creation_input_tokens: 0,
  model: 'claude-test',
})

function arm(on: any) {
  const notices: string[] = []
  on('turn.complete', () => ({ text: '' }))
  on('ui.notify', ($: any, e: any) => { notices.push(e.text); return { value: undefined } })
  return notices
}

test('a short turn shows its line and sends no notification', async ($, on) => {
  const notices = arm(on)
  const r = await $.turn.complete({ turnId: 't1', answer: 'hi', durationMs: 5300, isAborted: false, usage: usage(1200, 300, 10000) })
  expect(r.text).toBe('⏱ 5.3s · in 1.2k · out 300 · cache read 10.0k · claude-test')
  expect(notices).toEqual([])
})

test('a long turn sends one native notification', async ($, on) => {
  const notices = arm(on)
  await $.turn.complete({ turnId: 't1', answer: 'done', durationMs: 90000, isAborted: false, usage: usage(10, 10) })
  expect(notices).toEqual(['Turn finished in 90.0s'])
})

test('an interrupted turn is marked and still notifies past the threshold', async ($, on) => {
  const notices = arm(on)
  const r = await $.turn.complete({ turnId: 't1', answer: '', durationMs: 45000, isAborted: true, usage: null })
  expect(r.text).toBe('⏱ 45.0s · interrupted')
  expect(notices).toEqual(['Turn finished in 45.0s (interrupted)'])
})

test('a subagent turn is ignored', async ($, on) => {
  const notices = arm(on)
  const r = await $.turn.complete({ turnId: 't1', agentId: 'agent-1', answer: 'x', durationMs: 120000, isAborted: false, usage: usage(5, 5) })
  expect(r.text).toBe('')
  expect(notices).toEqual([])
  const s = await $.command.run({ command: 'turnstats', args: '' })
  expect(s.text).toBe('No turns yet in this session')
})

test('/turnstats sums the main conversation turns', async ($, on) => {
  arm(on)
  await $.turn.complete({ turnId: 't1', answer: 'a', durationMs: 1000, isAborted: false, usage: usage(1000, 200, 5000) })
  await $.turn.complete({ turnId: 't2', answer: 'b', durationMs: 2500, isAborted: true, usage: usage(500, 100) })
  const s = await $.command.run({ command: 'turnstats', args: '' })
  expect(s.text).toBe('2 turns (1 interrupted) · total 3.5s · in 1.5k · out 300 · cache read 5.0k · cache write 0')
})

test('session.start registers /turnstats', async ($, on) => {
  const registered: string[] = []
  on('session.start', () => ({ cwd: '/work' }))
  on('command.register', ($: any, e: any) => { registered.push(e.name); return { value: undefined } })
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  expect(registered).toEqual(['turnstats'])
})

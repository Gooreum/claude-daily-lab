import { expect, mock, test } from 'claude-code/testing'

const usage = (input: number, output: number, cacheRead = 0, cacheWrite = 0) => ({
  input_tokens: input, output_tokens: output,
  cache_read_input_tokens: cacheRead, cache_creation_input_tokens: cacheWrite,
})

type Stub = { selection?: string; answer?: string; fail?: 'api-error' | 'empty-reply' | 'aborted' }

function arm(on: any, stub: Stub = {}) {
  const asked: any[] = []
  const opened: string[] = []
  mock.clock(on, { now: 1_700_000_000_000 })
  on('session.start', () => ({ cwd: '/work' }))
  on('command.register', () => ({ value: undefined }))
  on('ui.open', ($: any, e: any) => { opened.push(e.id); return { value: { isPlaced: true } } })
  on('ui.selection', () => ({ value: stub.selection === undefined ? undefined : { text: stub.selection, requestId: 'row-1' } }))
  on('model.complete', ($: any, e: any) => {
    asked.push(e)
    if (stub.fail === 'api-error') return { value: { isAnswered: false, reason: 'api-error', status: 529, error: 'overloaded', usage: usage(0, 0) } }
    if (stub.fail) return { value: { isAnswered: false, reason: stub.fail, usage: usage(0, 0) } }
    return { value: { isAnswered: true, text: stub.answer ?? '안녕하세요', usage: usage(40, 12, 100, 0) } }
  })
  return { asked, opened }
}

const start = ($: any) => $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
const lens = ($: any, args = '') => $.command.run({ command: 'lens', args } as any)

test('/lens with a selection translates it to Korean with haiku and opens the pane', async ($, on) => {
  const { asked, opened } = arm(on, { selection: 'Hello there', answer: '안녕하세요' })
  await start($)
  const r = await lens($)
  expect(r.exitCode).toBe(0)
  expect(r.text).toBe('[→ 한국어] 안녕하세요  (140→12 tok, <$0.0001)')
  expect(asked.length).toBe(1)
  expect(asked[0].model).toBe('haiku')
  expect(asked[0].effort).toBe('low')
  expect(asked[0].prompt).toBe('Hello there')
  expect(opened).toEqual(['selection-lens'])
})

test('/lens explain sends the explain system prompt', async ($, on) => {
  const { asked } = arm(on, { selection: 'const x = atom(...)', answer: 'atom은 상태 셀을 만든다.' })
  await start($)
  const r = await lens($, 'explain')
  expect(r.text).toContain('[설명] atom은 상태 셀을 만든다.')
  expect(JSON.stringify(asked[0].system)).toContain('Explain in Korean')
})

test('inline text after -- wins over the selection', async ($, on) => {
  const { asked } = arm(on, { selection: 'selected words', answer: 'ok' })
  await start($)
  await lens($, 'en -- 캐시가 깨졌다')
  expect(asked[0].prompt).toBe('캐시가 깨졌다')
  expect(JSON.stringify(asked[0].system)).toContain('into natural English')
})

test('with nothing selected it explains how to use it and asks the model nothing', async ($, on) => {
  const { asked, opened } = arm(on, {})
  await start($)
  const r = await lens($)
  expect(r.exitCode).toBe(1)
  expect(r.text).toContain('Nothing is selected')
  expect(asked.length).toBe(0)
  expect(opened).toEqual([])
})

test('an API error is reported, not thrown, and stays in the pane history', async ($, on) => {
  arm(on, { selection: 'x', fail: 'api-error' })
  await start($)
  const r = await lens($)
  expect(r.exitCode).toBe(1)
  expect(r.text).toBe('[→ 한국어] ✗ api-error 529 (overloaded)')
})

test('a very long selection is cut to 4000 chars before it is sent', async ($, on) => {
  const { asked } = arm(on, { selection: 'a'.repeat(9000), answer: 'aaa' })
  await start($)
  const r = await lens($, 'tldr')
  expect(asked[0].prompt.length).toBe(4000)
  expect(r.text).toContain('selection was cut to 4000 chars')
})

for (const surface of ['terminal', 'desktop'] as const) {
  test(`the pane lists lookups newest first on ${surface}`, async ($, on) => {
    arm(on, { selection: 'first', answer: '첫째' })
    await start($)
    await lens($)
    await lens($, 'tldr -- second thing')
    const ui = await $.ui.mount({ plugin: 'selection-lens', surface, component: 'Pane', props: {} as any, requestId: 'selection-lens', viewport: { columns: 60, rows: 20 } as any })
    expect(await ui.find({ type: 'Text', text: /한 줄 요약/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /“second thing”/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /“first”/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /2 lookups/ })).toBeDefined()
  })
}

test('an empty pane says what to do', async ($, on) => {
  arm(on, {})
  await start($)
  const ui = await $.ui.mount({ plugin: 'selection-lens', surface: 'terminal', component: 'Pane', props: {} as any, requestId: 'selection-lens', viewport: { columns: 60, rows: 20 } as any })
  expect(await ui.find({ type: 'Text', text: /Select text in the transcript/ })).toBeDefined()
})

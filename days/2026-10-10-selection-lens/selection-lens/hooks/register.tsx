// selection-lens — 트랜스크립트에서 마우스로 고른 텍스트를 /lens 한 번으로 번역·설명한다.
// 선택 영역은 $.ui.selection()으로 받고, 답은 세션의 자격 증명으로 $.model.complete(haiku)에 묻고,
// 결과는 pane에 최근 5개까지 쌓인다. -p처럼 선택이 없는 자리에서는 `/lens ko -- <text>`로 직접 넘긴다.
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Lookup, Mode } from '../types'
import { MODES, NO_SELECTION, PANE, buildRequest, clipSource, costOf, fmtCost, inputTokensOf, parseArgs, preview, pushLookup, summarize } from './lens'

const lookups = atom({ plugin: 'selection-lens', key: 'lookups' } as const, [] as readonly Lookup[])

async function lookUp($: EngineInterface, mode: Mode, raw: string, from: Lookup['from']): Promise<Lookup> {
  const { text, clipped } = clipSource(raw)
  const at = await $.clock.now()
  const r = await $.model.complete(buildRequest(mode, text))
  const base = { mode, source: text, from, at }
  if (r.isAnswered) {
    const answer = clipped ? `${r.text.trim()}\n(selection was cut to ${text.length} chars)` : r.text
    return { ...base, ok: true, answer, inputTokens: inputTokensOf(r.usage), outputTokens: r.usage.output_tokens, cost: costOf(r.usage) }
  }
  const why = r.reason === 'api-error' ? `api-error ${r.status ?? 'no response'} (${r.error})` : r.reason
  return { ...base, ok: false, answer: why, inputTokens: 0, outputTokens: 0, cost: 0 }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    try {
      await $.command.register({ name: 'lens', description: 'Translate or explain the text you selected in the transcript: /lens [ko|en|explain|tldr] [-- text]' })
    } catch {
      // 이미 등록된 이름이면 무시한다.
    }
    return next(e)
  })

  on('command.run', { command: 'lens' }, async ($, e) => {
    const { mode, text: inline } = parseArgs(e.args)
    let raw = inline
    let from: Lookup['from'] = 'args'
    if (!raw) {
      const sel = await $.ui.selection()
      raw = sel?.text?.trim() || undefined
      from = 'selection'
    }
    if (!raw) return { text: NO_SELECTION, exitCode: 1 }
    const l = await lookUp($, mode, raw, from)
    await update($, lookups, list => pushLookup(list ?? [], l))
    void $.ui.open({ id: PANE, title: 'lens' })
    return { text: summarize(l), exitCode: l.ok ? 0 : 1 }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const list = (await read($, lookups)) ?? []
    if (list.length === 0) {
      return <Text dimColor>Select text in the transcript and run /lens.</Text>
    }
    const spent = list.reduce((s, l) => s + l.cost, 0)
    return (
      <Box flexDirection="column">
        {list.map(l => (
          <Box flexDirection="column" marginBottom={1}>
            <Text bold color={l.ok ? 'success' : 'error'}>
              {MODES[l.mode].label} <Text dimColor>· {l.from} · {l.inputTokens}→{l.outputTokens} tok · {fmtCost(l.cost)}</Text>
            </Text>
            <Text dimColor>“{preview(l.source)}”</Text>
            <Text color={l.ok ? 'text' : 'error'}>{l.answer.trim()}</Text>
          </Box>
        ))}
        <Text dimColor>{list.length} lookups · {fmtCost(spent)} this session</Text>
      </Box>
    )
  })
}

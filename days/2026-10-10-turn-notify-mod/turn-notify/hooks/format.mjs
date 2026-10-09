// 순수 함수 모음. Claude Code 없이 node로 단위 테스트한다.

export const NOTIFY_AFTER_MS = 30_000

export function fmtTokens(n) {
  if (!Number.isFinite(n) || n < 0) return '0'
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'k'
  return String(n)
}

export function fmtSeconds(ms) {
  const s = Math.max(0, ms) / 1000
  return s >= 100 ? Math.round(s) + 's' : s.toFixed(1) + 's'
}

export function emptyTotals() {
  return { turns: 0, durationMs: 0, input: 0, output: 0, cacheRead: 0, cacheWrite: 0, aborted: 0 }
}

// turn.complete 이벤트 하나를 누계에 더한 새 객체를 돌려준다 (원본은 바꾸지 않음).
export function addTurn(totals, e) {
  const u = e.usage || {}
  return {
    turns: totals.turns + 1,
    durationMs: totals.durationMs + (e.durationMs || 0),
    input: totals.input + (u.input_tokens || 0),
    output: totals.output + (u.output_tokens || 0),
    cacheRead: totals.cacheRead + (u.cache_read_input_tokens || 0),
    cacheWrite: totals.cacheWrite + (u.cache_creation_input_tokens || 0),
    aborted: totals.aborted + (e.isAborted ? 1 : 0),
  }
}

// 답변 아래 한 줄: "⏱ 12.3s · in 1.2k · out 300 · cache read 10.0k · model claude-x"
export function turnLine(e) {
  const u = e.usage
  const parts = ['⏱ ' + fmtSeconds(e.durationMs || 0)]
  if (e.isAborted) parts.push('interrupted')
  if (u) {
    parts.push('in ' + fmtTokens(u.input_tokens || 0))
    parts.push('out ' + fmtTokens(u.output_tokens || 0))
    if (u.cache_read_input_tokens) parts.push('cache read ' + fmtTokens(u.cache_read_input_tokens))
    if (u.model) parts.push(u.model)
  }
  return parts.join(' · ')
}

export function statsLine(t) {
  if (t.turns === 0) return 'No turns yet in this session'
  return (
    t.turns + ' turn' + (t.turns === 1 ? '' : 's') +
    (t.aborted ? ' (' + t.aborted + ' interrupted)' : '') +
    ' · total ' + fmtSeconds(t.durationMs) +
    ' · in ' + fmtTokens(t.input) +
    ' · out ' + fmtTokens(t.output) +
    ' · cache read ' + fmtTokens(t.cacheRead) +
    ' · cache write ' + fmtTokens(t.cacheWrite)
  )
}

export function shouldNotify(e, thresholdMs = NOTIFY_AFTER_MS) {
  return !e.agentId && (e.durationMs || 0) >= thresholdMs
}

export function notifyText(e) {
  return 'Turn finished in ' + fmtSeconds(e.durationMs || 0) + (e.isAborted ? ' (interrupted)' : '')
}

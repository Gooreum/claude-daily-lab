// agent-radar 순수 함수. claude-code를 import하지 않아 node만으로 테스트된다.
import type { AgentRec, Radar } from '../types'

export const PANE = 'agent-radar'
export const MAX_DONE = 20
/** 이보다 오래 걸린 서브에이전트가 끝나면 네이티브 알림을 보낸다. */
export const NOTIFY_AFTER_MS = 30_000

export const GLYPHS: Record<string, string> = {
  Explore: '🔍', 'general-purpose': '🛠', Plan: '📐', fork: '🍴', teammate: '👥', claude: '🤖',
}

export function glyphOf(type: string): string {
  return GLYPHS[type] ?? '•'
}

export function emptyRadar(now = 0): Radar {
  return { agents: [], now }
}

export type SpawnLike = { subagentType: string; description: string; model?: string; background: boolean }

export function started(r: Radar, id: string, e: SpawnLike, now: number): Radar {
  const rec: AgentRec = {
    id, type: e.subagentType || 'teammate', description: e.description || '', model: e.model, background: e.background,
    startedAt: now, toolCalls: 0, toolErrors: 0, tokens: 0, state: 'running',
  }
  // 같은 id가 다시 오면(재시작) 바꿔치기한다
  return { ...r, now, agents: [...r.agents.filter(a => a.id !== id), rec] }
}

export function toolCalled(r: Radar, id: string, isError: boolean): Radar {
  return patch(r, id, a => ({ ...a, toolCalls: a.toolCalls + 1, toolErrors: a.toolErrors + (isError ? 1 : 0) }))
}

export type UsageLike = { input_tokens: number; output_tokens: number; cache_read_input_tokens?: number } | null | undefined

export function tokensOf(u: UsageLike): number {
  return u ? u.input_tokens + u.output_tokens + (u.cache_read_input_tokens ?? 0) : 0
}

export function finished(r: Radar, id: string, usage: UsageLike, aborted: boolean, now: number): Radar {
  const next = patch(r, id, a => ({ ...a, state: aborted ? 'aborted' : 'done', endedAt: now, tokens: a.tokens + tokensOf(usage) }))
  return { ...next, now, agents: trim(next.agents) }
}

/** 끝난 것은 최근 MAX_DONE개만 남긴다. 도는 것은 항상 남긴다. */
export function trim(agents: AgentRec[], max = MAX_DONE): AgentRec[] {
  const running = agents.filter(a => a.state === 'running')
  const done = agents.filter(a => a.state !== 'running').slice(-max)
  return [...running, ...done].sort((a, b) => a.startedAt - b.startedAt)
}

export function clearDone(r: Radar, now: number): Radar {
  return { now, agents: r.agents.filter(a => a.state === 'running') }
}

export function tick(r: Radar, now: number): Radar {
  return r.agents.some(a => a.state === 'running') ? { ...r, now } : r
}

function patch(r: Radar, id: string, fn: (a: AgentRec) => AgentRec): Radar {
  let hit = false
  const agents = r.agents.map(a => (a.id === id ? ((hit = true), fn(a)) : a))
  return hit ? { ...r, agents } : r
}

export function elapsedMs(a: AgentRec, now: number): number {
  return Math.max(0, (a.endedAt ?? now) - a.startedAt)
}

export function fmtMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`
  return `${Math.floor(ms / 60_000)}m${String(Math.round((ms % 60_000) / 1000)).padStart(2, '0')}s`
}

export function fmtTokens(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n)
}

export function byType(agents: AgentRec[]): [string, number][] {
  const m = new Map<string, number>()
  for (const a of agents) m.set(a.type, (m.get(a.type) ?? 0) + 1)
  return [...m.entries()].sort((x, y) => y[1] - x[1] || x[0].localeCompare(y[0]))
}

/** 한 에이전트 한 줄: `🔍 Explore · find auth code · 12s · 7 tools (1 ✗) · 3.2k tok` */
export function line(a: AgentRec, now: number): string {
  const parts = [`${glyphOf(a.type)} ${a.type}`]
  if (a.description) parts.push(a.description)
  parts.push(fmtMs(elapsedMs(a, now)) + (a.state === 'running' ? '…' : a.state === 'aborted' ? ' ✗' : ' ✓'))
  parts.push(`${a.toolCalls} tools` + (a.toolErrors ? ` (${a.toolErrors} ✗)` : ''))
  if (a.tokens) parts.push(`${fmtTokens(a.tokens)} tok`)
  return parts.join(' · ')
}

/** 명령 응답 한 줄. */
export function summary(r: Radar, now: number): string {
  if (r.agents.length === 0) return 'No subagents yet this session.'
  const running = r.agents.filter(a => a.state === 'running')
  const done = r.agents.filter(a => a.state !== 'running')
  const types = byType(r.agents).map(([t, n]) => `${glyphOf(t)} ${t} ×${n}`).join(', ')
  const tools = r.agents.reduce((s, a) => s + a.toolCalls, 0)
  const tokens = r.agents.reduce((s, a) => s + a.tokens, 0)
  const head = `${running.length} running · ${done.length} done · ${types} · ${tools} tools · ${fmtTokens(tokens)} tok`
  const busiest = running.map(a => `${glyphOf(a.type)} ${a.description || a.type} ${fmtMs(elapsedMs(a, now))}`).join(', ')
  return busiest ? `${head}\n  now: ${busiest}` : head
}

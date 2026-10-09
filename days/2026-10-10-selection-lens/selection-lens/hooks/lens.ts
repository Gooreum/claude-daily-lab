// selection-lens 순수 함수. 선택 텍스트를 받아 어떤 모드로 무엇을 물을지 정하고, 결과를 한 줄로 요약한다.
// claude-code 모듈을 import하지 않으므로 node만으로 테스트된다.
import type { Lookup, Mode } from '../types'

export const PANE = 'selection-lens'
export const MODEL = 'haiku'
export const DEFAULT_MODE: Mode = 'ko'
/** 선택 영역이 이보다 길면 앞부분만 보낸다 (한 번의 /lens가 비싸지지 않게). */
export const MAX_CHARS = 4000
export const MAX_HISTORY = 5
export const TIMEOUT_MS = 30_000

type ModeSpec = { label: string; system: string; maxTokens: number }

export const MODES: Record<Mode, ModeSpec> = {
  ko: {
    label: '→ 한국어',
    system: 'You translate the user message into natural Korean. Keep code, identifiers, file paths and numbers untouched. Answer with the translation only — no preface, no notes.',
    maxTokens: 1024,
  },
  en: {
    label: '→ English',
    system: 'You translate the user message into natural English. Keep code, identifiers, file paths and numbers untouched. Answer with the translation only — no preface, no notes.',
    maxTokens: 1024,
  },
  explain: {
    label: '설명',
    system: 'The user message is a passage selected from a coding session transcript. Explain in Korean what it means and why it matters, in at most 5 short sentences. If it is code, say what it does. No preface.',
    maxTokens: 600,
  },
  tldr: {
    label: '한 줄 요약',
    system: 'Summarize the user message in one Korean sentence of at most 40 characters. Answer with the sentence only.',
    maxTokens: 120,
  },
}

export function isMode(s: string): s is Mode {
  return Object.prototype.hasOwnProperty.call(MODES, s)
}

/** `/lens`, `/lens explain`, `/lens ko -- text to look up` → 모드와 (있으면) 인라인 텍스트. */
export function parseArgs(args: string): { mode: Mode; text?: string } {
  const trimmed = args.trim()
  const sep = trimmed.indexOf('--')
  const head = (sep >= 0 ? trimmed.slice(0, sep) : trimmed).trim()
  const inline = sep >= 0 ? trimmed.slice(sep + 2).trim() : ''
  const mode: Mode = head === '' ? DEFAULT_MODE : isMode(head) ? head : DEFAULT_MODE
  if (head !== '' && !isMode(head) && sep < 0) {
    // `/lens some words` — 모드가 아니면 전부 인라인 텍스트로 본다
    return { mode: DEFAULT_MODE, text: trimmed }
  }
  return inline ? { mode, text: inline } : { mode }
}

/** 선택 영역을 보낼 크기로 자른다. */
export function clipSource(text: string, max = MAX_CHARS): { text: string; clipped: boolean } {
  const t = text.replace(/\r\n/g, '\n').trim()
  if (t.length <= max) return { text: t, clipped: false }
  return { text: t.slice(0, max), clipped: true }
}

/** $.model.complete에 넘길 요청. system은 매번 같으니 캐시 표시를 붙인다. */
export function buildRequest(mode: Mode, text: string) {
  const spec = MODES[mode]
  return {
    model: MODEL,
    system: [{ text: spec.system, cache: true as const }],
    prompt: text,
    effort: 'low' as const,
    maxTokens: spec.maxTokens,
    timeoutMs: TIMEOUT_MS,
  }
}

/** Haiku 5.5 공개 단가(USD/MTok, ≤100K 입력): 입력 0.10, 출력 0.50, 캐시 읽기 0.01, 캐시 쓰기 0.125 */
export const HAIKU_PRICE = { input: 0.10, output: 0.50, cacheRead: 0.01, cacheWrite: 0.125 }

export type Usage = { input_tokens: number; output_tokens: number; cache_read_input_tokens?: number; cache_creation_input_tokens?: number }

export function costOf(u: Usage | null | undefined, p = HAIKU_PRICE): number {
  if (!u) return 0
  const M = 1_000_000
  return (u.input_tokens * p.input + u.output_tokens * p.output
    + (u.cache_read_input_tokens ?? 0) * p.cacheRead + (u.cache_creation_input_tokens ?? 0) * p.cacheWrite) / M
}

export function inputTokensOf(u: Usage | null | undefined): number {
  if (!u) return 0
  return u.input_tokens + (u.cache_read_input_tokens ?? 0) + (u.cache_creation_input_tokens ?? 0)
}

/** 한 줄 미리보기: 줄바꿈을 공백으로, 길면 말줄임. */
export function preview(text: string, max = 60): string {
  const one = text.replace(/\s+/g, ' ').trim()
  return one.length <= max ? one : one.slice(0, max - 1) + '…'
}

export function fmtCost(usd: number): string {
  return usd < 0.0001 && usd > 0 ? '<$0.0001' : `$${usd.toFixed(4)}`
}

/** 명령 응답 한 줄. */
export function summarize(l: Lookup): string {
  const tag = `[${MODES[l.mode].label}]`
  if (!l.ok) return `${tag} ✗ ${l.answer}`
  return `${tag} ${l.answer.trim()}  (${l.inputTokens}→${l.outputTokens} tok, ${fmtCost(l.cost)})`
}

/** 최근 N개만 남기고 앞에 붙인다. */
export function pushLookup(list: readonly Lookup[], l: Lookup, max = MAX_HISTORY): readonly Lookup[] {
  return [l, ...list].slice(0, max)
}

export const NO_SELECTION = 'Nothing is selected. Drag over text in the transcript, then run /lens again — or pass text inline: /lens ko -- <text>'

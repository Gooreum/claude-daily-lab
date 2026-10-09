export type Mode = 'ko' | 'en' | 'explain' | 'tldr'

/** One /lens run, kept in the pane's history (newest first). */
export type Lookup = {
  mode: Mode
  /** The text that was looked up, already clipped to MAX_CHARS. */
  source: string
  /** Where the text came from. */
  from: 'selection' | 'args'
  /** The model's answer, or an explanation of why there is none. */
  answer: string
  ok: boolean
  inputTokens: number
  outputTokens: number
  /** USD, from the plugin's own Haiku price table (an estimate). */
  cost: number
  /** ms since epoch */
  at: number
}

declare module 'claude-code' {
  interface PluginState {
    'selection-lens': { lookups: readonly Lookup[] }
  }
}

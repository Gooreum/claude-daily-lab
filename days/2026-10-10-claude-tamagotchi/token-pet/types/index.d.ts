export type Mood = 'happy' | 'hungry' | 'sleepy' | 'sick' | 'proud'

export type Pet = {
  name: string
  /** 0..100. Tokens feed it, time drains it. */
  fullness: number
  /** Turns completed this session. */
  meals: number
  /** Tool calls that returned an error since the last meal. */
  bruises: number
  mood: Mood
  /** Last time something fed or hurt it (ms since epoch). */
  lastEventAt: number
  /** Last time the hunger drain was applied, so ticks never double-count. */
  drainedAt: number
  /** The last line the pet "said". */
  line: string
}

declare module 'claude-code' {
  interface PluginState {
    'token-pet': { pet: Pet | null }
  }
}

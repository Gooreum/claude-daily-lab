// 순수 함수 모음. 모드 런타임 없이 node로도 단위 테스트할 수 있다.
import type { Mood, Pet } from '../types'

export const PANE = 'token-pet'
export const TOKENS_PER_POINT = 400        // 400 토큰 = 포만감 1점
export const FULL_MAX = 100
export const DRAIN_PER_MIN = 4             // 1분에 4점씩 배고파진다
export const SLEEPY_AFTER_MS = 5 * 60_000  // 5분 넘게 아무 일 없으면 존다
export const PROUD_AFTER_MS = 30_000       // 30초 넘는 턴은 자랑거리
export const SICK_AFTER_BRUISES = 3        // 에러 3번이면 앓는다

export function newPet(now: number, name = 'Claudie'): Pet {
  return { name, fullness: 60, meals: 0, bruises: 0, mood: 'happy', lastEventAt: now, drainedAt: now, line: '…' }
}

export function tokensOf(usage: { input_tokens?: number; output_tokens?: number; cache_read_input_tokens?: number } | null | undefined): number {
  if (!usage) return 0
  return (usage.input_tokens || 0) + (usage.output_tokens || 0) + (usage.cache_read_input_tokens || 0)
}

// 시간이 흐르면 배가 꺼진다. 마지막으로 꺼진 시각(drainedAt)부터만 계산해 틱이 겹쳐도 이중 차감되지 않는다.
export function drained(pet: Pet, now: number): Pet {
  const minutes = Math.max(0, now - pet.drainedAt) / 60_000
  const fullness = Math.max(0, pet.fullness - minutes * DRAIN_PER_MIN)
  return { ...pet, fullness, drainedAt: Math.max(pet.drainedAt, now) }
}

export function feed(pet: Pet, tokens: number, durationMs: number, now: number): Pet {
  const base = drained(pet, now)
  const points = Math.min(FULL_MAX, tokens / TOKENS_PER_POINT)
  const fullness = Math.min(FULL_MAX, base.fullness + points)
  const bruises = 0
  const mood: Mood = durationMs >= PROUD_AFTER_MS ? 'proud' : moodOf(fullness, bruises, 0)
  const line = durationMs >= PROUD_AFTER_MS
    ? `That was a long one (${Math.round(durationMs / 1000)}s). I'm so proud of us!`
    : points >= 25 ? `Yum, ${fmtTokens(tokens)} tokens!` : points >= 5 ? 'Nom nom.' : 'A snack. I could eat more.'
  return { ...base, fullness, meals: base.meals + 1, bruises, mood, lastEventAt: now, line }
}

export function hurt(pet: Pet, tool: string, now: number): Pet {
  const base = drained(pet, now)
  const bruises = base.bruises + 1
  const mood = moodOf(base.fullness, bruises, 0)
  const line = bruises >= SICK_AFTER_BRUISES ? `${tool} failed again… I don't feel so good.` : `Ouch, ${tool} bit me.`
  return { ...base, bruises, mood, lastEventAt: now, line }
}

// 시간 경과만 반영한 현재 모습 (틱마다 호출). 포만감과 기분, 조는 상태를 갱신한다.
export function tick(pet: Pet, now: number): Pet {
  const base = drained(pet, now)
  const idleMs = now - pet.lastEventAt
  const computed = moodOf(base.fullness, base.bruises, idleMs)
  // 자랑스러운 기분은 배고프거나 졸리거나 아프기 전까지 이어진다.
  const mood: Mood = computed === 'happy' && pet.mood === 'proud' ? 'proud' : computed
  const line = mood === 'sleepy' && pet.mood !== 'sleepy' ? 'zzz…' : mood === 'hungry' && pet.mood !== 'hungry' ? 'Feed me a prompt?' : pet.line
  return { ...base, mood, line }
}

export function moodOf(fullness: number, bruises: number, idleMs: number): Mood {
  if (bruises >= SICK_AFTER_BRUISES) return 'sick'
  if (idleMs >= SLEEPY_AFTER_MS) return 'sleepy'
  if (fullness < 25) return 'hungry'
  return 'happy'
}

export const FACES: Record<Mood, string[]> = {
  happy:  ['  ∩___∩  ', ' ( ^ω^ ) ', '  (   )  ', '   U U   '],
  hungry: ['  ∩___∩  ', ' ( ;ω; ) ', '  (   )  ', '   U U   '],
  sleepy: ['  ∩___∩  ', ' ( -ω- )z', '  (   )  ', '   U U   '],
  sick:   ['  ∩___∩  ', ' ( xωx ) ', '  (   )  ', '   U U   '],
  proud:  ['  ∩___∩  ', ' ( ★ω★ ) ', '  (   )  ', '   U U   '],
}

export function bar(value: number, width = 10): string {
  const filled = Math.round(Math.max(0, Math.min(FULL_MAX, value)) / FULL_MAX * width)
  return '█'.repeat(filled) + '░'.repeat(width - filled)
}

export function fmtTokens(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'k'
  return String(n)
}

export function statusLine(pet: Pet): string {
  return `${pet.name} · ${pet.mood} · fullness ${Math.round(pet.fullness)}/100 · ${pet.meals} meals · ${pet.bruises} bruises`
}

// token-pet — Claude Code 안에 사는 펫. 턴마다 쓴 토큰이 밥이고, 시간이 가면 배가 꺼지고,
// 도구 호출이 실패하면 다치고, 30초 넘는 턴이 끝나면 자랑스러워하며 네이티브 알림을 보낸다.
// 상태는 $.state(세션, pane을 다시 그림)와 $.store(세션 사이에 남음)에 함께 둔다.
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Pet } from '../types'
import { FACES, PANE, PROUD_AFTER_MS, bar, feed, hurt, newPet, statusLine, tick, tokensOf } from './pet'

const STORE_KEY = 'pet'
const pet = atom({ plugin: 'token-pet', key: 'pet' } as const, null)

function isPet(v: unknown): v is Pet {
  return typeof v === 'object' && v !== null && typeof (v as Pet).fullness === 'number' && typeof (v as Pet).name === 'string'
}

// 세션 상태와 영구 저장소를 함께 갱신한다. 없으면 새 펫부터 시작한다.
async function change($: EngineInterface, fn: (p: Pet, now: number) => Pet): Promise<Pet> {
  const now = await $.clock.now()
  let next: Pet | null = null
  await update($, pet, p => { next = fn(p ?? newPet(now), now); return next })
  const saved = next as Pet | null
  if (saved) await $.store.set(STORE_KEY, saved)
  return saved ?? newPet(now)
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    try {
      await $.command.register({ name: 'pet', description: 'Open the token-pet pane and show how your pet is doing (`/pet reset` starts over)' })
    } catch {
      // 이미 등록된 이름이면 무시한다.
    }
    const now = await $.clock.now()
    const stored = await $.store.get(STORE_KEY)
    await update($, pet, () => (isPet(stored) ? tick(stored, now) : newPet(now)))
    void $.ui.open({ id: PANE, title: 'token-pet' })
    // 1분마다 배가 꺼지고 조는지 본다. 값이 바뀌면 pane이 다시 그려진다.
    $.clock.every(60_000, () => change($, (p, t) => tick(p, t)))
    return next(e)
  })

  on('command.run', { command: 'pet' }, async ($, e) => {
    if (e.args.trim() === 'reset') {
      const p = await change($, (_p, now) => newPet(now))
      return { text: `A new pet hatched. ${statusLine(p)}` }
    }
    await $.ui.open({ id: PANE, title: 'token-pet' })
    const p = await change($, (p, now) => tick(p, now))
    return { text: statusLine(p) }
  })

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    if (e.agentId) return result // 서브에이전트 턴은 밥이 아니다
    const tokens = tokensOf(e.usage)
    const fed = await change($, (p, now) => feed(p, tokens, e.durationMs || 0, now))
    if ((e.durationMs || 0) >= PROUD_AFTER_MS) {
      void $.ui.notify(fed.line, { title: 'token-pet' })
    }
    return result
  })

  on('tool.call', async ($, e, next) => {
    const ran = await next(e)
    if (ran.deny === undefined && ran.isError === true) {
      await change($, (p, now) => hurt(p, e.tool, now))
    }
    return ran
  }).catch(($, e, next) => next(e)) // 펫 갱신이 실패해도 도구는 그대로 돌아간다

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const p = (await read($, pet)) ?? newPet(0)
    const face = FACES[p.mood]
    const color = p.mood === 'sick' ? 'error' : p.mood === 'hungry' ? 'warning' : p.mood === 'proud' ? 'success' : p.mood === 'sleepy' ? 'subtle' : 'text'
    return (
      <Box flexDirection="column">
        {face.map(row => <Text color={color}>{row}</Text>)}
        <Text bold>{p.name} <Text dimColor>· {p.mood}</Text></Text>
        <Text>fullness {bar(p.fullness)} {Math.round(p.fullness)}</Text>
        <Text dimColor>{p.meals} meals · {p.bruises} bruises</Text>
        <Text italic>“{p.line}”</Text>
      </Box>
    )
  })
}

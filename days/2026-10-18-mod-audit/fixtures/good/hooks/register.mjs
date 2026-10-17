// $.process.run 같은 위험 호출은 주석에 적어도 세지 않아야 한다 (주석 제거 테스트).
import { fmt } from './format.mjs'

export function register(on) {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'turnstats', description: 'stats' })
    return next(e)
  })
  on('turn.complete', async ($, e, next) => {
    const r = await next(e)
    $.ui.notify(fmt(e)) // https://example.com 은 문자열이 아니라 주석 속 URL
    return r
  })
}

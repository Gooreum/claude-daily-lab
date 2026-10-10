#!/usr/bin/env bash
# test.sh — 이 폴더에서 `bash test.sh`.
# 1) node로 순수 함수(hooks/radar.ts) 단위 테스트 (CI에서 항상 실행, Node 22+ 타입 스트리핑)
# 2) claude CLI가 있으면 `claude plugin validate` + `claude plugin test` (agent.spawn·tool.call·turn.complete 스텁)
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
fail=0

echo "== 1) node 단위 테스트: hooks/radar.ts"
node --input-type=module - <<'JS' || fail=1
import assert from 'node:assert/strict'
const R = await import('./agent-radar/hooks/radar.ts')
let n = 0
const t = (name, fn) => { try { fn(); n++; console.log('  ✅ ' + name) } catch (e) { console.log('  ❌ ' + name + ': ' + e.message); process.exitCode = 1 } }
const sp = (type, description = '', background = false) => ({ subagentType: type, description, background })
let r = R.emptyRadar(0)
t('started: running 레코드, 타입·설명·시작 시각', () => { r = R.started(r, 'a1', sp('Explore', 'look'), 1000); assert.equal(r.agents.length, 1); assert.equal(r.agents[0].state, 'running'); assert.equal(r.agents[0].startedAt, 1000) })
t('started: 빈 subagentType은 teammate', () => assert.equal(R.started(R.emptyRadar(0), 'x', sp(''), 0).agents[0].type, 'teammate'))
t('started: 같은 id는 바꿔치기', () => assert.equal(R.started(r, 'a1', sp('Plan'), 2000).agents.length, 1))
t('toolCalled: 횟수·오류 누적, 모르는 id는 무시(같은 객체)', () => { const x = R.toolCalled(R.toolCalled(r, 'a1', false), 'a1', true); assert.equal(x.agents[0].toolCalls, 2); assert.equal(x.agents[0].toolErrors, 1); assert.equal(R.toolCalled(r, 'zz', false), r) })
t('tokensOf: 입력+출력+캐시 읽기', () => { assert.equal(R.tokensOf({ input_tokens: 1, output_tokens: 2, cache_read_input_tokens: 3 }), 6); assert.equal(R.tokensOf(null), 0) })
t('finished: done/aborted, endedAt, 토큰', () => { const d = R.finished(r, 'a1', { input_tokens: 100, output_tokens: 50 }, false, 5000); assert.equal(d.agents[0].state, 'done'); assert.equal(d.agents[0].endedAt, 5000); assert.equal(d.agents[0].tokens, 150); assert.equal(R.finished(r, 'a1', null, true, 1).agents[0].state, 'aborted') })
t('trim: 끝난 것은 20개만, 도는 것은 모두', () => { let x = R.emptyRadar(0); for (let i = 0; i < 25; i++) { x = R.started(x, 'd' + i, sp('Explore'), i); x = R.finished(x, 'd' + i, null, false, i + 1) } x = R.started(x, 'run', sp('Plan'), 99); assert.equal(x.agents.length, 21); assert.ok(x.agents.some(a => a.id === 'run')); assert.ok(!x.agents.some(a => a.id === 'd0')) })
t('tick: 도는 게 있을 때만 now 갱신', () => { assert.equal(R.tick(r, 9).now, 9); const d = R.finished(r, 'a1', null, false, 2); assert.equal(R.tick(d, 99), d) })
t('clearDone: 끝난 것만 지움', () => { const x = R.started(R.finished(r, 'a1', null, false, 2), 'a2', sp('Explore'), 3); assert.deepEqual(R.clearDone(x, 4).agents.map(a => a.id), ['a2']) })
t('fmtMs: ms / s / m', () => { assert.equal(R.fmtMs(999), '999ms'); assert.equal(R.fmtMs(4500), '4.5s'); assert.equal(R.fmtMs(12_000), '12s'); assert.equal(R.fmtMs(125_000), '2m05s') })
t('fmtTokens', () => { assert.equal(R.fmtTokens(999), '999'); assert.equal(R.fmtTokens(3456), '3.5k') })
t('byType: 많은 순, 같으면 이름순', () => { let x = R.emptyRadar(0); x = R.started(x, '1', sp('Explore'), 0); x = R.started(x, '2', sp('Plan'), 0); x = R.started(x, '3', sp('Explore'), 0); assert.deepEqual(R.byType(x.agents), [['Explore', 2], ['Plan', 1]]) })
t('glyphOf: 모르는 타입은 •', () => { assert.equal(R.glyphOf('Explore'), '🔍'); assert.equal(R.glyphOf('lab:runner'), '•') })
t('line: 도는 중 …, 끝남 ✓, 중단 ✗', () => { assert.equal(R.line(r.agents[0], 13_000), '🔍 Explore · look · 12s… · 0 tools'); const d = R.finished(R.toolCalled(r, 'a1', true), 'a1', { input_tokens: 2000, output_tokens: 0 }, false, 3000); assert.equal(R.line(d.agents[0], 0), '🔍 Explore · look · 2.0s ✓ · 1 tools (1 ✗) · 2.0k tok') })
t('summary: 없음 / 합계 줄 / now 줄', () => { assert.equal(R.summary(R.emptyRadar(0), 0), 'No subagents yet this session.'); assert.equal(R.summary(r, 2000), '1 running · 0 done · 🔍 Explore ×1 · 0 tools · 0 tok\n  now: 🔍 look 1.0s') })
console.log('  node 단위 테스트: ' + n + '/15 통과')
JS

echo "== 2) claude plugin validate / test"
if command -v claude >/dev/null 2>&1; then
  claude plugin validate ./agent-radar >/dev/null 2>&1 && echo "  ✅ claude plugin validate" || { echo "  ❌ claude plugin validate"; claude plugin validate ./agent-radar; fail=1; }
  out="$(cd agent-radar && claude plugin test 2>&1)"; rc=$?
  printf '%s\n' "$out" | grep -E '^\(pass\)|^\(fail\)|pass$|fail$|✓|✗|passed|failed' | sed 's/^/  /'
  [ "$rc" -eq 0 ] && echo "  ✅ claude plugin test" || { echo "  ❌ claude plugin test"; printf '%s\n' "$out" | tail -40; fail=1; }
else
  echo "  ⏭ claude CLI 없음 — 모드 훅 테스트는 건너뜀 (로컬에서 bash test.sh로 실행)"
fi

echo "== 결과: $([ $fail -eq 0 ] && echo PASS || echo FAIL)"
exit "$fail"

#!/usr/bin/env bash
# test.sh — 이 폴더에서 `bash test.sh`.
# 1) node로 순수 함수(format.mjs) 단위 테스트 (CI에서 항상 실행)
# 2) claude CLI가 있으면 `claude plugin validate` + `claude plugin test` (모드 훅 테스트)
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
fail=0

echo "== 1) node 단위 테스트: hooks/format.mjs"
node --input-type=module - <<'JS' || fail=1
import assert from 'node:assert/strict'
import { fmtTokens, fmtSeconds, addTurn, emptyTotals, turnLine, statsLine, shouldNotify, notifyText, NOTIFY_AFTER_MS } from './turn-notify/hooks/format.mjs'
let n = 0
const t = (name, fn) => { try { fn(); n++; console.log('  ✅ ' + name) } catch (e) { console.log('  ❌ ' + name + ': ' + e.message); process.exitCode = 1 } }
t('fmtTokens 경계값', () => { assert.equal(fmtTokens(0), '0'); assert.equal(fmtTokens(999), '999'); assert.equal(fmtTokens(1000), '1.0k'); assert.equal(fmtTokens(1_250_000), '1.3M'); assert.equal(fmtTokens(-5), '0'); assert.equal(fmtTokens(NaN), '0') })
t('fmtSeconds 100초 이상은 정수', () => { assert.equal(fmtSeconds(5300), '5.3s'); assert.equal(fmtSeconds(123456), '123s'); assert.equal(fmtSeconds(-1), '0.0s') })
t('addTurn은 원본을 바꾸지 않고 누계', () => {
  const a = emptyTotals(); const b = addTurn(a, { durationMs: 1000, isAborted: true, usage: { input_tokens: 10, output_tokens: 5, cache_read_input_tokens: 3, cache_creation_input_tokens: 2 } })
  assert.equal(a.turns, 0); assert.deepEqual(b, { turns: 1, durationMs: 1000, input: 10, output: 5, cacheRead: 3, cacheWrite: 2, aborted: 1 })
})
t('addTurn usage 없음도 안전', () => { const b = addTurn(emptyTotals(), { durationMs: 0 }); assert.equal(b.turns, 1); assert.equal(b.input, 0) })
t('turnLine usage 없음', () => { assert.equal(turnLine({ durationMs: 2000 }), '⏱ 2.0s') })
t('turnLine cache read 0이면 생략', () => { assert.equal(turnLine({ durationMs: 2000, usage: { input_tokens: 1, output_tokens: 2, cache_read_input_tokens: 0 } }), '⏱ 2.0s · in 1 · out 2') })
t('statsLine 0턴', () => { assert.equal(statsLine(emptyTotals()), 'No turns yet in this session') })
t('statsLine 단수형', () => { assert.match(statsLine(addTurn(emptyTotals(), { durationMs: 10 })), /^1 turn · /) })
t('shouldNotify 임계값 경계', () => { assert.equal(shouldNotify({ durationMs: NOTIFY_AFTER_MS }), true); assert.equal(shouldNotify({ durationMs: NOTIFY_AFTER_MS - 1 }), false); assert.equal(shouldNotify({ durationMs: 999999, agentId: 'x' }), false) })
t('notifyText 중단 표시', () => { assert.equal(notifyText({ durationMs: 31000, isAborted: true }), 'Turn finished in 31.0s (interrupted)') })
console.log('  node 단위 테스트: ' + n + '/10 통과')
JS

echo "== 2) claude plugin validate / test"
if command -v claude >/dev/null 2>&1; then
  claude plugin validate ./turn-notify >/dev/null 2>&1 && echo "  ✅ claude plugin validate" || { echo "  ❌ claude plugin validate"; claude plugin validate ./turn-notify; fail=1; }
  out="$(cd turn-notify && claude plugin test 2>&1)"; rc=$?
  printf '%s\n' "$out" | grep -E '^\(pass\)|^\(fail\)|pass$|fail$' | sed 's/^/  /'
  [ "$rc" -eq 0 ] && echo "  ✅ claude plugin test" || { echo "  ❌ claude plugin test"; fail=1; }
else
  echo "  ⏭ claude CLI 없음 — 모드 훅 테스트는 건너뜀 (로컬에서 bash test.sh로 실행)"
fi

echo "== 결과: $([ $fail -eq 0 ] && echo PASS || echo FAIL)"
exit "$fail"

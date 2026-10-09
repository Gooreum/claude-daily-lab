#!/usr/bin/env bash
# test.sh — 이 폴더에서 `bash test.sh`.
# 1) node로 순수 함수(hooks/pet.ts) 단위 테스트 (CI에서 항상 실행, Node 22+ 타입 스트리핑)
# 2) claude CLI가 있으면 `claude plugin validate` + `claude plugin test` (모드 훅·pane 테스트)
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
fail=0

echo "== 1) node 단위 테스트: hooks/pet.ts"
node --input-type=module - <<'JS' || fail=1
import assert from 'node:assert/strict'
const P = await import('./token-pet/hooks/pet.ts')
let n = 0
const t = (name, fn) => { try { fn(); n++; console.log('  ✅ ' + name) } catch (e) { console.log('  ❌ ' + name + ': ' + e.message); process.exitCode = 1 } }
const pet = P.newPet(0)
t('newPet: fullness 60, happy', () => { assert.equal(pet.fullness, 60); assert.equal(pet.mood, 'happy') })
t('tokensOf: usage 없음 0, 세 항목 합산', () => { assert.equal(P.tokensOf(null), 0); assert.equal(P.tokensOf({ input_tokens: 1, output_tokens: 2, cache_read_input_tokens: 3 }), 6) })
t('feed: 400토큰 = 1점, 상한 100', () => { assert.equal(P.feed(pet, 4000, 0, 0).fullness, 70); assert.equal(P.feed(pet, 1_000_000, 0, 0).fullness, 100) })
t('feed: 원본 불변, meals 증가, bruises 리셋', () => { const h = P.hurt(pet, 'Bash', 0); const f = P.feed(h, 400, 0, 0); assert.equal(pet.meals, 0); assert.equal(f.meals, 1); assert.equal(f.bruises, 0); assert.equal(h.bruises, 1) })
t('feed: 30초 이상이면 proud + 대사', () => { const f = P.feed(pet, 0, 30_000, 0); assert.equal(f.mood, 'proud'); assert.match(f.line, /30s/) })
t('feed: 29.9초는 proud 아님', () => { assert.equal(P.feed(pet, 0, 29_999, 0).mood, 'happy') })
t('drained: 1분에 4점, 0 아래로 안 감', () => { assert.equal(P.drained(pet, 60_000).fullness, 56); assert.equal(P.drained(pet, 60 * 60_000).fullness, 0) })
t('drained: 틱이 겹쳐도 이중 차감 없음', () => { const a = P.drained(pet, 60_000); const b = P.drained(a, 120_000); assert.equal(b.fullness, 52); assert.equal(P.drained(b, 120_000).fullness, 52) })
t('hurt: 3번이면 sick', () => { let p = pet; for (let i = 0; i < 3; i++) p = P.hurt(p, 'Edit', 0); assert.equal(p.mood, 'sick'); assert.match(p.line, /don't feel so good/) })
t('tick: 5분 idle이면 sleepy, 대사 zzz', () => { const p = P.tick(pet, 5 * 60_000); assert.equal(p.mood, 'sleepy'); assert.equal(p.line, 'zzz…'); assert.equal(p.fullness, 40) })
t('tick: 4분 59초는 안 졸림', () => { assert.equal(P.tick(pet, 5 * 60_000 - 1).mood, 'happy') })
t('tick: proud는 유지되다가 졸리면 풀림', () => { const pr = P.feed(pet, 0, 60_000, 0); assert.equal(P.tick(pr, 1000).mood, 'proud'); assert.equal(P.tick(pr, 5 * 60_000).mood, 'sleepy') })
t('moodOf 우선순위: sick > sleepy > hungry', () => { assert.equal(P.moodOf(0, 3, 999999), 'sick'); assert.equal(P.moodOf(0, 0, 999999), 'sleepy'); assert.equal(P.moodOf(24, 0, 0), 'hungry'); assert.equal(P.moodOf(25, 0, 0), 'happy') })
t('bar 경계', () => { assert.equal(P.bar(0), '░░░░░░░░░░'); assert.equal(P.bar(100), '██████████'); assert.equal(P.bar(50), '█████░░░░░') })
t('statusLine 반올림', () => { assert.equal(P.statusLine({ ...pet, fullness: 39.6 }), 'Claudie · happy · fullness 40/100 · 0 meals · 0 bruises') })
console.log('  node 단위 테스트: ' + n + '/15 통과')
JS

echo "== 2) claude plugin validate / test"
if command -v claude >/dev/null 2>&1; then
  claude plugin validate ./token-pet >/dev/null 2>&1 && echo "  ✅ claude plugin validate" || { echo "  ❌ claude plugin validate"; claude plugin validate ./token-pet; fail=1; }
  out="$(cd token-pet && claude plugin test 2>&1)"; rc=$?
  printf '%s\n' "$out" | grep -E '^\(pass\)|^\(fail\)|pass$|fail$|✓|✗|passed|failed' | sed 's/^/  /'
  [ "$rc" -eq 0 ] && echo "  ✅ claude plugin test" || { echo "  ❌ claude plugin test"; printf '%s\n' "$out" | tail -30; fail=1; }
else
  echo "  ⏭ claude CLI 없음 — 모드 훅 테스트는 건너뜀 (로컬에서 bash test.sh로 실행)"
fi

echo "== 결과: $([ $fail -eq 0 ] && echo PASS || echo FAIL)"
exit "$fail"

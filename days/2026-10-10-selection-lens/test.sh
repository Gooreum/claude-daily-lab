#!/usr/bin/env bash
# test.sh — 이 폴더에서 `bash test.sh`.
# 1) node로 순수 함수(hooks/lens.ts) 단위 테스트 (CI에서 항상 실행, Node 22+ 타입 스트리핑)
# 2) claude CLI가 있으면 `claude plugin validate` + `claude plugin test` (selection·model 스텁으로 명령·pane 테스트)
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
fail=0

echo "== 1) node 단위 테스트: hooks/lens.ts"
node --input-type=module - <<'JS' || fail=1
import assert from 'node:assert/strict'
const L = await import('./selection-lens/hooks/lens.ts')
let n = 0
const t = (name, fn) => { try { fn(); n++; console.log('  ✅ ' + name) } catch (e) { console.log('  ❌ ' + name + ': ' + e.message); process.exitCode = 1 } }
t('parseArgs: 빈 인자 → ko, 텍스트 없음', () => assert.deepEqual(L.parseArgs(''), { mode: 'ko' }))
t('parseArgs: 모드만', () => assert.deepEqual(L.parseArgs(' explain '), { mode: 'explain' }))
t('parseArgs: 모드 + -- 텍스트', () => assert.deepEqual(L.parseArgs('en -- 안녕 -- 둘'), { mode: 'en', text: '안녕 -- 둘' }))
t('parseArgs: -- 텍스트만 → ko', () => assert.deepEqual(L.parseArgs('-- hi'), { mode: 'ko', text: 'hi' }))
t('parseArgs: 모드 아닌 단어들 → 전부 텍스트', () => assert.deepEqual(L.parseArgs('what is this'), { mode: 'ko', text: 'what is this' }))
t('clipSource: 4000자 초과만 자르고 CRLF 정리', () => { assert.deepEqual(L.clipSource('a\r\nb '), { text: 'a\nb', clipped: false }); const c = L.clipSource('x'.repeat(4001)); assert.equal(c.text.length, 4000); assert.equal(c.clipped, true) })
t('buildRequest: haiku·low·캐시 표시 system·모드별 maxTokens', () => { const r = L.buildRequest('tldr', 'hi'); assert.equal(r.model, 'haiku'); assert.equal(r.effort, 'low'); assert.equal(r.maxTokens, 120); assert.equal(r.system[0].cache, true); assert.equal(r.prompt, 'hi') })
t('costOf: Haiku 단가 (1M 입력 = $0.10, 캐시 읽기 $0.01)', () => { assert.equal(L.costOf({ input_tokens: 1_000_000, output_tokens: 0 }), 0.10); assert.equal(L.costOf({ input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 1_000_000 }), 0.01); assert.equal(L.costOf(null), 0) })
t('inputTokensOf: 캐시 읽기·쓰기 포함', () => assert.equal(L.inputTokensOf({ input_tokens: 1, output_tokens: 9, cache_read_input_tokens: 2, cache_creation_input_tokens: 3 }), 6))
t('preview: 공백 접고 60자 말줄임', () => { assert.equal(L.preview('a\n\n b'), 'a b'); assert.equal(L.preview('x'.repeat(70)).length, 60); assert.ok(L.preview('x'.repeat(70)).endsWith('…')) })
t('fmtCost: 아주 작은 값은 <$0.0001', () => { assert.equal(L.fmtCost(0.00001), '<$0.0001'); assert.equal(L.fmtCost(0), '$0.0000'); assert.equal(L.fmtCost(0.0123), '$0.0123') })
const ok = { mode: 'ko', source: 's', from: 'selection', answer: ' 안녕 ', ok: true, inputTokens: 10, outputTokens: 3, cost: 0.001, at: 0 }
t('summarize: 성공은 라벨·답·토큰·비용', () => assert.equal(L.summarize(ok), '[→ 한국어] 안녕  (10→3 tok, $0.0010)'))
t('summarize: 실패는 ✗ 이유', () => assert.equal(L.summarize({ ...ok, ok: false, answer: 'aborted' }), '[→ 한국어] ✗ aborted'))
t('pushLookup: 앞에 붙이고 5개 유지', () => { let l = []; for (let i = 0; i < 7; i++) l = L.pushLookup(l, { ...ok, at: i }); assert.equal(l.length, 5); assert.equal(l[0].at, 6) })
console.log('  node 단위 테스트: ' + n + '/14 통과')
JS

echo "== 2) claude plugin validate / test"
if command -v claude >/dev/null 2>&1; then
  claude plugin validate ./selection-lens >/dev/null 2>&1 && echo "  ✅ claude plugin validate" || { echo "  ❌ claude plugin validate"; claude plugin validate ./selection-lens; fail=1; }
  out="$(cd selection-lens && claude plugin test 2>&1)"; rc=$?
  printf '%s\n' "$out" | grep -E '^\(pass\)|^\(fail\)|pass$|fail$|✓|✗|passed|failed' | sed 's/^/  /'
  [ "$rc" -eq 0 ] && echo "  ✅ claude plugin test" || { echo "  ❌ claude plugin test"; printf '%s\n' "$out" | tail -40; fail=1; }
else
  echo "  ⏭ claude CLI 없음 — 모드 훅 테스트는 건너뜀 (로컬에서 bash test.sh로 실행)"
fi

echo "== 결과: $([ $fail -eq 0 ] && echo PASS || echo FAIL)"
exit "$fail"

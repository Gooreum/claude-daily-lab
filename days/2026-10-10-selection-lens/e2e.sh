#!/usr/bin/env bash
# e2e.sh — 실제 Claude Code로 모드를 --plugin-dir로 싣고 /lens를 돌린다. `bash e2e.sh`
# -p에는 마우스 선택이 없으므로(문서: "-p … answers none") 인라인 텍스트 경로와 "선택 없음" 경로를 본다.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
command -v claude >/dev/null || { echo "claude CLI 없음"; exit 1; }
echo "claude: $(claude --version)"
pass=0; fail=0
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
run() { (cd "$tmp" && claude -p "$1" --plugin-dir "$OLDPWD/selection-lens" --output-format text 2>&1 < /dev/null); }

echo "== 1) /lens (선택 없음) → 사용법 안내, 모델 호출 없음"
out="$(run "/lens")"; printf '%s\n' "$out" | sed 's/^/   | /'
if [[ "$out" == *"Nothing is selected"* ]]; then pass=$((pass+1)); echo "  ✅ 선택 없음 안내"; else fail=$((fail+1)); echo "  ❌ 안내 없음"; fi

echo "== 2) /lens ko -- <영어> → 실제 haiku 번역 (세션 자격 증명으로 \$.model.complete)"
out="$(run "/lens ko -- The cache was invalidated because the system prompt changed.")"; printf '%s\n' "$out" | sed 's/^/   | /'
if [[ "$out" == *"[→ 한국어]"* ]] && [[ "$out" == *"tok, "* ]] && [[ "$out" != *"✗"* ]] && [[ "$out" =~ (캐시|시스템) ]]; then pass=$((pass+1)); echo "  ✅ 한국어 번역 + 토큰·비용"; else fail=$((fail+1)); echo "  ❌ 번역 실패"; fi

echo "== 3) /lens tldr -- <긴 문단> → 한 줄 요약"
out="$(run "/lens tldr -- Prompt caching lets you reuse a long system prompt across calls. The first call writes the cache at 1.25x the input price, and later calls read it at a tenth of the price, as long as the prefix is byte-identical and the entry has not expired.")"; printf '%s\n' "$out" | sed 's/^/   | /'
if [[ "$out" == *"[한 줄 요약]"* ]] && [[ "$out" != *"✗"* ]]; then pass=$((pass+1)); echo "  ✅ 요약"; else fail=$((fail+1)); echo "  ❌ 요약 실패"; fi

echo "== 4) 모드 없이 /lens → 응답 없음 (대조군)"
out="$(cd "$tmp" && claude -p "/lens" --output-format text 2>&1 < /dev/null)"; printf '%s\n' "$out" | head -3 | sed 's/^/   | /'
if [[ "$out" != *"Nothing is selected"* ]]; then pass=$((pass+1)); echo "  ✅ 모드 없을 땐 /lens가 없다"; else fail=$((fail+1)); echo "  ❌ 모드 없이도 응답?"; fi

echo "== 결과: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]

#!/usr/bin/env bash
# test.sh — 이 폴더에서 `bash test.sh`. 모델·키체인 없이 unittest + run 모드 리댁션 확인 (CI). 실제 Claude Code는 `bash e2e.sh`.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
fail=0
echo "== 1) python3 -m unittest"
python3 -m unittest discover -s tests -v 2>&1 | grep -E 'Ran |^OK|FAILED|ERROR' | sed 's/^/  /'
python3 -m unittest discover -s tests >/dev/null 2>&1 && echo "  ✅ unittest" || { echo "  ❌ unittest"; python3 -m unittest discover -s tests 2>&1 | tail -30; fail=1; }
echo "== 2) run 모드: 자식은 값을 보고, 출력에는 값이 없다"
val="test-value-$(date +%s)-abcdef"
out="$(DEMO_TOKEN="$val" python3 secret_envoy.py run --backend env --names DEMO_TOKEN -- 'printf %s "$DEMO_TOKEN" | wc -c; echo "$DEMO_TOKEN"; echo "$DEMO_TOKEN" | base64' 2>&1)"
printf '%s\n' "$out" | sed 's/^/   | /'
[[ "$out" == *"${#val}"* ]] && [[ "$out" != *"$val"* ]] && [[ "$out" == *"2 redaction(s)"* ]] && echo "  ✅ 길이는 맞고 값은 없다" || { echo "  ❌"; fail=1; }
echo "== 3) 0600 아닌 파일은 거부"
tmp="$(mktemp -d)"; printf '{"A_KEY":"xxxx-yyyy"}' > "$tmp/s.json"; chmod 644 "$tmp/s.json"
python3 secret_envoy.py list --backend file --file "$tmp/s.json" >/dev/null 2>&1; rc=$?
[ "$rc" -eq 2 ] && echo "  ✅ 644 거부 (exit 2)" || { echo "  ❌ exit=$rc"; fail=1; }
chmod 600 "$tmp/s.json"; out="$(python3 secret_envoy.py list --backend file --file "$tmp/s.json")"
[[ "$out" == '{"backend": "file", "secrets": ["A_KEY"]}' ]] && echo "  ✅ 600이면 이름만 나열" || { echo "  ❌ $out"; fail=1; }
rm -rf "$tmp"
echo "== 결과: $([ $fail -eq 0 ] && echo PASS || echo FAIL)"
exit "$fail"

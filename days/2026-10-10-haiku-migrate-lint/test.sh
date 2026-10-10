#!/usr/bin/env bash
# haiku-migrate-lint 단위 테스트. 키·네트워크·모델 호출 없음.
set -u
cd "$(dirname "$0")"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ✗ $1"; [ -n "${2:-}" ] && echo "      $2"; }
has()  { echo "$1" | grep -q -- "$2"; }

echo "[1] 전체 fixtures 린트 (텍스트)"
OUT=$(python3 haiku_lint.py fixtures 2>&1); RC=$?
[ $RC -eq 1 ] && ok "error가 있으면 exit 1" || bad "exit code $RC (기대 1)"
has "$OUT" "합계: error" && ok "합계 줄 출력" || bad "합계 줄 없음"

echo "[2] legacy_api.py — Claude API 규칙"
J=$(python3 haiku_lint.py --json fixtures/legacy_api.py)
rules() { echo "$J" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(" ".join(sorted({f["rule"] for f in d["findings"]})))'; }
R=$(rules)
for r in H01 H02 H03 H04 H07 H09; do has "$R" "$r" && ok "$r 검출" || bad "$r 미검출" "rules=$R"; done
echo "$J" | grep -q '"platform": {' && ok "JSON에 platform 맵" || bad "platform 맵 없음"
echo "$J" | grep -q 'claude-haiku-4-5-20251001 → claude-haiku-5-5' && ok "H01 fix 문자열(API)" || bad "H01 fix 문자열 틀림"
echo "$J" | python3 -c '
import json,sys; d=json.load(sys.stdin)
errs=[f for f in d["findings"] if f["rule"]=="H03"]
assert len(errs)==2, errs
assert all(f["level"]=="error" for f in errs), errs
' && ok "H03: temperature 0.2·top_k 둘 다 error" || bad "H03 개수/레벨 틀림"
echo "$J" | python3 -c '
import json,sys; d=json.load(sys.stdin)
assert any(f["rule"]=="H10" for f in d["findings"]), "H10 info 기대"
' && ok "H10: refusal 미처리 info" || bad "H10 미검출"

echo "[3] legacy_tools.ts — 도구 버전·헤더"
J=$(python3 haiku_lint.py --json fixtures/legacy_tools.ts); R=$(rules)
has "$R" "H05" && ok "H05 computer_20250124 검출" || bad "H05 미검출" "rules=$R"
has "$R" "H08" && ok "H08 text_editor_20250124 검출" || bad "H08 미검출"
echo "$J" | grep -q 'computer_20250124 → computer_toolset_20260801' && ok "API 플랫폼은 toolset으로 치환" || bad "toolset 치환 안 됨"
echo "$J" | grep -q 'fine-grained-tool-streaming-2025-05-14 → (제거)' && ok "FGTS 헤더 제거 안내(toolset 동반)" || bad "FGTS 미검출"
echo "$J" | grep -q 'computer-use-2025-01-24 → (제거)' && ok "구 베타 헤더 제거 안내" || bad "베타 헤더 미검출"
has "$R" "H10" && bad "H10 오탐: refusal 처리가 있는데 info" || ok "H10 없음(refusal 처리 있음)"
has "$R" "H04" && bad "H04 오탐: user 턴으로 끝남" || ok "H04 없음(user로 끝남)"

echo "[4] legacy_bedrock.py — 플랫폼 자동 감지"
J=$(python3 haiku_lint.py --json fixtures/legacy_bedrock.py); R=$(rules)
echo "$J" | grep -q '"fixtures/legacy_bedrock.py": "bedrock"' && ok "bedrock 자동 감지" || bad "bedrock 감지 실패"
has "$R" "H06" && ok "H06 strict tool(Bedrock) 검출" || bad "H06 미검출" "rules=$R"
echo "$J" | grep -q 'anthropic.claude-haiku-4-5-20251001-v1:0 → anthropic.claude-haiku-5-5' && ok "Bedrock ID 치환" || bad "Bedrock ID 치환 틀림"
has "$R" "H07" && bad "H07 오탐: type으로 고름" || ok "H07 없음(type으로 선택)"

echo "[5] --platform 강제"
J=$(python3 haiku_lint.py --json --platform bedrock fixtures/legacy_tools.ts)
echo "$J" | grep -q 'computer_20250124 → computer_20251124' && ok "Bedrock 강제 시 computer_20251124" || bad "bedrock 강제 치환 틀림"
echo "$J" | grep -q 'computer-use-2025-01-24 → computer-use-2025-11-24' && ok "Bedrock 베타 헤더 치환" || bad "bedrock 헤더 치환 틀림"
J=$(python3 haiku_lint.py --json --platform api fixtures/legacy_bedrock.py)
echo "$J" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert not any(f["rule"]=="H06" for f in d["findings"])' \
  && ok "--platform api면 H06 끔" || bad "H06이 api에서도 나옴"

echo "[6] config.yaml — 허용값 경계"
J=$(python3 haiku_lint.py --json fixtures/config.yaml)
echo "$J" | python3 -c '
import json,sys; d=json.load(sys.stdin)
h3=[f for f in d["findings"] if f["rule"]=="H03"]
assert len(h3)==2 and all(f["level"]=="warn" for f in h3), h3
assert any(f["rule"]=="H01" and "claude-3-5-haiku-latest" in f["fix"] for f in d["findings"])
assert not any(f["rule"]=="H09" for f in d["findings"])
' && ok "temperature 1·top_p 0.99는 warn, Haiku 3.5 alias는 H01, max_tokens 8000은 통과" || bad "yaml 경계값 판정 틀림"

echo "[7] migrated.py — 오탐 0"
OUT=$(python3 haiku_lint.py fixtures/migrated.py); RC=$?
[ $RC -eq 0 ] && has "$OUT" "찾지 못했다" && ok "깨끗한 파일은 exit 0, 지적 없음" || bad "오탐 발생" "$OUT"

echo "[8] --fix --dry-run / --fix"
TMP=$(mktemp -d); cp fixtures/legacy_api.py fixtures/legacy_tools.ts "$TMP"/
OUT=$(python3 haiku_lint.py --fix --dry-run "$TMP")
has "$OUT" "^-.*claude-haiku-4-5-20251001" && has "$OUT" "^+.*claude-haiku-5-5" && ok "dry-run은 unified diff 출력" || bad "diff 없음"
grep -q 'claude-haiku-4-5-20251001' "$TMP/legacy_api.py" && ok "dry-run은 파일을 바꾸지 않음" || bad "dry-run이 파일을 바꿈"
python3 haiku_lint.py --fix "$TMP" >/dev/null
grep -q 'model="claude-haiku-5-5"' "$TMP/legacy_api.py" && ok "--fix: 모델 ID 치환" || bad "모델 ID 미치환"
grep -q 'computer_toolset_20260801' "$TMP/legacy_tools.ts" && grep -q 'text_editor_20250728' "$TMP/legacy_tools.ts" && ok "--fix: 도구 버전 치환" || bad "도구 버전 미치환"
grep -q 'computer-use-2025-01-24' "$TMP/legacy_tools.ts" && ok "--fix: 제거 항목은 건드리지 않음(손으로)" || bad "제거 항목을 임의 삭제"
grep -q 'budget_tokens' "$TMP/legacy_api.py" && ok "--fix: thinking/샘플링은 자동 수정 안 함" || bad "비기계적 항목을 수정함"
J=$(python3 haiku_lint.py --json "$TMP"); echo "$J" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert not any(f["rule"]=="H01" for f in d["findings"])' \
  && ok "fix 후 재린트에 H01 없음" || bad "fix 후에도 H01 남음"
rm -rf "$TMP"

echo "[9] --min-level"
OUT=$(python3 haiku_lint.py --min-level error fixtures/legacy_api.py)
has "$OUT" "WARN" && bad "--min-level error에 WARN 포함" || ok "--min-level error는 error만"

echo "[10] --scope: haiku 언급 없는 파일은 파라미터 규칙 생략"
TMP=$(mktemp -d); printf 'client.messages.create(model="claude-sonnet-5-5", temperature=0.5, max_tokens=100)\n' > "$TMP/sonnet.py"
J=$(python3 haiku_lint.py --json "$TMP"); echo "$J" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["findings"]==[], d' \
  && ok "기본 scope=haiku: Sonnet 전용 파일의 temperature는 무시" || bad "scope=haiku인데 Sonnet 파일을 지적"
J=$(python3 haiku_lint.py --json --scope all "$TMP"); echo "$J" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert any(f["rule"]=="H03" for f in d["findings"])' \
  && ok "--scope all이면 지적" || bad "--scope all에서 미검출"
rm -rf "$TMP"

echo
echo "통과 $PASS · 실패 $FAIL"
[ $FAIL -eq 0 ]

#!/usr/bin/env bash
# adr-guard 테스트. 키·모델·네트워크 없이 돈다.
cd "$(dirname "$0")" || exit 2
HOOK="$PWD/adr_guard.py"
EX="$PWD/examples"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "ok   - $1"; }
bad() { FAIL=$((FAIL+1)); echo "FAIL - $1"; [ -n "${2:-}" ] && echo "       $2"; }
check() { if [ "$2" -eq 0 ]; then ok "$1"; else bad "$1" "${3:-}"; fi; }
has()  { echo "$OUT" | grep -qF -- "$1"; }
# run <프로젝트> <stdin> [args...] → $OUT, $RC
run() { local d="$1" in="$2"; shift 2
  OUT="$(printf '%s' "$in" | env -u ADR_GUARD_DIR CLAUDE_PROJECT_DIR="$d" python3 -I "$HOOK" "$@" 2>&1)"; RC=$?; }
hook() { run "$EX" "{\"prompt\":\"$1\"}" "${@:2}"; }

# 1. 영어 기각 결정(front-matter status: not_adopted)
hook "Let us drop the brace syntax and use a YAML style for diagrams"
check "겹침: YAML ADR(not_adopted)를 찾는다" $(has "0012-yaml-syntax.md" && echo 0 || echo 1) "$OUT"
check "겹침: 기록된 사유를 그대로 보여 준다" $(has "half-YAML syntax would only breed confusion" && echo 0 || echo 1)
check "겹침: exit 0" $RC
# 2. 본문 'Status: Rejected' + '## Why' 절
hook "add a GraphQL API endpoint"
check "본문 Status: Rejected + ## Why 사유를 읽는다" $(has "second API doubles the auth surface" && echo 0 || echo 1) "$OUT"
# 3. 한글 + 조사
hook "렌더링 결과 캐시를 Redis로 옮겨줘"
check "한글: 조사를 떼고 기각 ADR을 찾는다" $(has "0015" && has "운영할 서버" && echo 0 || echo 1) "$OUT"
# 4. 채택된 ADR은 나오지 않는다
hook "use sqlite for local storage in a single file"
check "채택(accepted) ADR은 출력하지 않는다" $(has "0003" && echo 1 || echo 0) "$OUT"
check "겹치는 기각 없음 → 출력 비어 있음" $([ -z "$OUT" ] && echo 0 || echo 1) "$OUT"
# 5. 무관한 프롬프트
hook "fix typo in the readme"
check "무관한 프롬프트: 출력 없음" $([ -z "$OUT" ] && echo 0 || echo 1) "$OUT"
# 6. 단어 하나만 겹치면 붙이지 않는다(기본 2개)
hook "rename the diagram title"
check "단어 하나만 겹치면 출력 없음" $([ -z "$OUT" ] && echo 0 || echo 1) "$OUT"
# 7. 복수형은 한 단어로 센다 (diagram + diagrams = 1)
hook "list all diagrams"
check "복수형 중복 집계 없음(diagrams는 한 단어)" $([ -z "$OUT" ] && echo 0 || echo 1) "$OUT"
# 8. 사유가 없는 기각
hook "switch the test runner to jest"
check "사유 없는 기각: 'no reason recorded'라고 적는다" $(has "no reason recorded" && echo 0 || echo 1) "$OUT"
# 9. 문구는 사실만 (명령조 금지)
hook "Let us drop the brace syntax and use a YAML style for diagrams"
# 훅이 덧붙이는 문구(첫 줄·끝 줄)만 본다. 가운데 줄은 ADR에 적힌 사유를 그대로 옮긴 것이다.
FRAME="$(echo "$OUT" | sed -n '1p;$p')"
check "사실만: 훅이 쓴 문구에 must/should/please/never/do not 없음" $(echo "$FRAME" | grep -qiE '\b(must|should|please|never|do not|don.t)\b' && echo 1 || echo 0) "$FRAME"
check "끝줄: 충돌 여부는 확인하지 않았다고 밝힌다" $(has "has not been checked" && echo 0 || echo 1)
# 10. 상한
P="$TMP/many"; mkdir -p "$P/docs/adr"
for i in 1 2 3 4 5 6; do
  printf -- '---\ntitle: Adopt widget framework %s\nstatus: rejected\n---\nReason: %s\n' "$i" "$(head -c 900 /dev/zero | tr '\0' 'x')" > "$P/docs/adr/00$i.md"
done
run "$P" '{"prompt":"adopt a widget framework"}'
check "상한: ADR 3개까지만" $([ "$(echo "$OUT" | grep -c '^- ')" -eq 3 ] && echo 0 || echo 1) "$OUT"
check "상한: 전체 3000자 이하" $([ ${#OUT} -le 3000 ] && echo 0 || echo 1) "${#OUT}자"
check "상한: 사유는 240자에서 자른다('…')" $(has "…" && echo 0 || echo 1)
# 11. --json
run "$EX" '{"prompt":"use a YAML style for diagram syntax"}' --json
check "--json: hookSpecificOutput.additionalContext" $(echo "$OUT" | python3 -c 'import sys,json; d=json.load(sys.stdin)["hookSpecificOutput"]; assert d["hookEventName"]=="UserPromptSubmit" and "YAML" in d["additionalContext"]' 2>/dev/null && echo 0 || echo 1) "$OUT"
# 12. 깨진 입력도 exit 0, 출력 없음
for in in 'not json' '' '[]' '{"prompt":123}' '{"prompt":null}' '{}'; do
  run "$EX" "$in"
  check "깨진 입력 [$in]: exit 0·출력 없음" $([ $RC -eq 0 ] && [ -z "$OUT" ] && echo 0 || echo 1) "rc=$RC $OUT"
done
# 13. ADR 폴더가 없으면 조용히 통과
mkdir -p "$TMP/empty"; run "$TMP/empty" '{"prompt":"use a YAML style for diagram syntax"}'
check "ADR 폴더 없음: exit 0·출력 없음" $([ $RC -eq 0 ] && [ -z "$OUT" ] && echo 0 || echo 1) "$OUT"
# 14. 깨진 ADR(바이너리·빈 파일)도 죽지 않는다
P="$TMP/bad"; mkdir -p "$P/docs/adr"; : > "$P/docs/adr/empty.md"; head -c 300 /dev/urandom > "$P/docs/adr/bin.md"
printf -- '---\nstatus: rejected\ntitle: Use YAML style diagrams\n---\n' > "$P/docs/adr/ok.md"
run "$P" '{"prompt":"use a YAML style for diagrams"}'
check "깨진 ADR이 섞여도 정상 ADR은 찾는다" $([ $RC -eq 0 ] && has "ok.md" && echo 0 || echo 1) "rc=$RC $OUT"
# 15. 설정 파일: dirs·min_shared
P="$TMP/cfg"; mkdir -p "$P/decisions" "$P/.claude"
printf -- '---\ntitle: Replace cron with queue workers\nstatus: declined\n---\nReason: ops cost.\n' > "$P/decisions/a.md"
run "$P" '{"prompt":"replace cron jobs with queue workers"}'
check "설정 없음 + 비표준 폴더: 못 찾는다" $([ -z "$OUT" ] && echo 0 || echo 1) "$OUT"
echo '{"dirs":["decisions"],"min_shared":3}' > "$P/.claude/adr-guard.json"
run "$P" '{"prompt":"replace cron jobs with queue workers"}'
check "설정 dirs: 비표준 폴더를 읽는다(declined)" $(has "a.md" && echo 0 || echo 1) "$OUT"
run "$P" '{"prompt":"use queue"}'
check "설정 min_shared=3: 적게 겹치면 출력 없음" $([ -z "$OUT" ] && echo 0 || echo 1) "$OUT"
# 16. keywords: 짧은 키워드 하나만 겹쳐도 잡는다
P="$TMP/kw"; mkdir -p "$P/docs/adr"
printf -- '---\ntitle: Monorepo tooling choice\nstatus: not_adopted\nkeywords: bazel\n---\nReason: too heavy.\n' > "$P/docs/adr/k.md"
run "$P" '{"prompt":"try bazel for the build"}'
check "keywords: 한 단어(bazel)만 겹쳐도 잡는다" $(has "k.md" && echo 0 || echo 1) "$OUT"
# 17. ADR_GUARD_DIR 환경 변수
OUT="$(printf '{"prompt":"replace cron jobs with queue workers"}' | ADR_GUARD_DIR=decisions CLAUDE_PROJECT_DIR="$TMP/cfg" python3 -I "$HOOK" 2>&1)"
check "ADR_GUARD_DIR가 폴더를 지정한다" $(has "a.md" && echo 0 || echo 1) "$OUT"
# 18. stdin의 cwd (CLAUDE_PROJECT_DIR 없을 때)
OUT="$(printf '{"prompt":"use a YAML style for diagram syntax","cwd":"%s"}' "$EX" | env -u CLAUDE_PROJECT_DIR python3 -I "$HOOK" 2>&1)"
check "CLAUDE_PROJECT_DIR가 없으면 stdin의 cwd를 쓴다" $(has "0012" && echo 0 || echo 1) "$OUT"
# 19. --dry-run
OUT="$(CLAUDE_PROJECT_DIR="$EX" python3 -I "$HOOK" --dry-run "use a YAML style for diagram syntax" 2>&1)"
check "--dry-run: 같은 결과를 stdin 없이 보여 준다" $(has "0012" && echo 0 || echo 1) "$OUT"
OUT="$(CLAUDE_PROJECT_DIR="$EX" python3 -I "$HOOK" --dry-run "fix typo" 2>&1)"
check "--dry-run: 겹침 없으면 안내 문구" $(has "겹치는 기각 결정 없음" && echo 0 || echo 1) "$OUT"
# 20. --lint
OUT="$(CLAUDE_PROJECT_DIR="$EX" python3 -I "$HOOK" --lint 2>&1)"; RC=$?
check "--lint: 개수 요약(ADR 5개·채택 안 됨 4개)" $(has "ADR 5개 · 채택 안 됨 4개" && echo 0 || echo 1) "$OUT"
check "--lint: 사유 없는 기각을 짚고 exit 1" $(has "사유 없음: docs/adr/0020-no-reason.md" && [ $RC -eq 1 ] && echo 0 || echo 1) "rc=$RC $OUT"
OUT="$(CLAUDE_PROJECT_DIR="$TMP/empty" python3 -I "$HOOK" --lint 2>&1)"; RC=$?
check "--lint: ADR 폴더 없으면 안내 + exit 1" $(has "ADR 폴더를 찾지 못했다" && [ $RC -eq 1 ] && echo 0 || echo 1) "$OUT"
# 21. --print-rule / --print-settings
OUT="$(python3 -I "$HOOK" --print-rule)"
check "--print-rule: 상시 규칙 한 문장" $([ "$(echo "$OUT" | wc -l)" -eq 1 ] && has "rejected decisions" && echo 0 || echo 1) "$OUT"
OUT="$(python3 -I "$HOOK" --print-settings)"
check "--print-settings: 유효한 JSON, UserPromptSubmit, timeout 있음" $(echo "$OUT" | python3 -c 'import sys,json; h=json.load(sys.stdin)["hooks"]["UserPromptSubmit"][0]["hooks"][0]; assert h["type"]=="command" and h["timeout"]>0' 2>/dev/null && echo 0 || echo 1) "$OUT"
# 22. 소스에 비밀·외부 호출이 없다
check "소스에 네트워크 모듈 import 없음" $(grep -qE '^\s*(import|from)\s+(urllib|requests|socket|http|subprocess)' "$HOOK" && echo 1 || echo 0)

echo
echo "통과 $PASS · 실패 $FAIL"
[ "$FAIL" -eq 0 ]

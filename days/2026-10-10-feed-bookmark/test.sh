#!/usr/bin/env bash
# test.sh — 이 폴더에서 `bash test.sh`. 네트워크 없이 file:// fixture로만 돈다 (CI에서 실행).
# 실제 GitHub 피드로 확인하려면 `bash e2e.sh`.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
fail=0

echo "== 1) python3 -m unittest (fixture 기반)"
python3 -m unittest discover -s tests -v 2>&1 | sed 's/^/  /' | grep -E 'ok$|FAIL|ERROR|Ran |^  OK|^  FAILED' || true
python3 -m unittest discover -s tests >/dev/null 2>&1 && echo "  ✅ unittest" || { echo "  ❌ unittest"; fail=1; }

echo "== 2) CLI 스모크: 첫 실행 → 두 번째 실행 → 불가 소스 섞기"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fx="$(cd tests/fixtures && pwd)"
python3 - "$tmp" "$fx" <<'PY'
import json, sys, pathlib
tmp, fx = sys.argv[1], pathlib.Path(sys.argv[2])
u = lambda f: (fx / f).as_uri()
json.dump({"sources": [{"name": "example", "url": u("atom_v1.xml")}]}, open(f"{tmp}/s1.json", "w"))
json.dump({"sources": [{"name": "example", "url": u("atom_v2.xml")}, {"name": "gone", "url": u("missing.xml")}]}, open(f"{tmp}/s2.json", "w"))
PY
NOW="2026-10-10T12:00:00+00:00"
out="$(python3 feed_bookmark.py --sources "$tmp/s1.json" --state "$tmp/state.json" --now "$NOW")"; rc=$?
printf '%s\n' "$out" | sed 's/^/   | /'
[ "$rc" -eq 0 ] && [[ "$out" == *"새 항목 2개"* ]] && echo "  ✅ 첫 실행: 48h 내 2개만 new, exit=0" || { echo "  ❌ 첫 실행 exit=$rc"; fail=1; }
out="$(python3 feed_bookmark.py --sources "$tmp/s1.json" --state "$tmp/state.json" --now "$NOW")"; rc=$?
[ "$rc" -eq 0 ] && [[ "$out" == *"example — 조용함"* ]] && echo "  ✅ 재실행: 조용함, exit=0" || { echo "  ❌ 재실행 exit=$rc"; fail=1; }
out="$(python3 feed_bookmark.py --sources "$tmp/s2.json" --state "$tmp/state.json" --now "$NOW")"; rc=$?
printf '%s\n' "$out" | sed 's/^/   | /'
[ "$rc" -eq 2 ] && [[ "$out" == *"example — 새 항목 1개"* ]] && [[ "$out" == *"gone — ⚠️ 읽기 불가"* ]] && echo "  ✅ v2+불가 소스: 추가된 1개만 new, gone은 불가, exit=2" || { echo "  ❌ 혼합 실행 exit=$rc"; fail=1; }
python3 -c "import json,sys; s=json.load(open(sys.argv[1])); assert list(s['bookmarks'])==['example'] and len(s['bookmarks']['example']['seen_ids'])==4" "$tmp/state.json" \
  && echo "  ✅ 상태 파일: example만 북마크 4개, gone 없음" || { echo "  ❌ 상태 파일 내용"; fail=1; }

echo "== 결과: $([ $fail -eq 0 ] && echo PASS || echo FAIL)"
exit "$fail"

#!/usr/bin/env bash
# e2e.sh — 실제 GitHub 릴리스 Atom 피드(sources.json)로 세 번 실행한다. 네트워크 필요.
#  1) 첫 실행: 모든 소스 읽힘(exit 0), 북마크 9개 생성
#  2) 재실행: 전부 조용함(exit 0)
#  3) 존재하지 않는 소스 추가: 그 소스만 불가(exit 2), 나머지 북마크 불변
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
pass=0; fail=0
ok() { pass=$((pass+1)); echo "  ✅ $1"; }
ng() { fail=$((fail+1)); echo "  ❌ $1"; }

echo "== 1) 첫 실행 (sources.json, 48h 창)"
out="$(python3 feed_bookmark.py --state "$tmp/state.json")"; rc=$?
printf '%s\n' "$out" | sed 's/^/   | /'
[ "$rc" -eq 0 ] && ok "exit=0 (모든 소스 읽힘)" || ng "exit=$rc"
n="$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['bookmarks']))" "$tmp/state.json")"
[ "$n" = "9" ] && ok "북마크 9개 생성" || ng "북마크 $n개"

echo "== 2) 재실행"
out="$(python3 feed_bookmark.py --state "$tmp/state.json")"; rc=$?
printf '%s\n' "$out" | head -3 | sed 's/^/   | /'
[ "$rc" -eq 0 ] && [[ "$out" == *"새 항목 0개"* ]] && ok "전부 조용함, exit=0" || ng "exit=$rc"

echo "== 3) 존재하지 않는 소스 추가"
python3 - "$tmp" <<'PY'
import json, sys
s = json.load(open("sources.json"))
s["sources"].append({"name": "nope", "url": "https://github.com/anthropics/this-repo-does-not-exist-xyz/releases.atom"})
json.dump(s, open(f"{sys.argv[1]}/s3.json", "w"))
PY
cp "$tmp/state.json" "$tmp/before.json"
out="$(python3 feed_bookmark.py --sources "$tmp/s3.json" --state "$tmp/state.json")"; rc=$?
printf '%s\n' "$out" | grep -E 'nope|읽기 불가' | sed 's/^/   | /'
[ "$rc" -eq 2 ] && [[ "$out" == *"nope — ⚠️ 읽기 불가: HTTP 404"* ]] && ok "nope만 불가(HTTP 404), exit=2" || ng "exit=$rc"
python3 -c "
import json,sys
a=json.load(open(sys.argv[1]))['bookmarks']; b=json.load(open(sys.argv[2]))['bookmarks']
assert 'nope' not in b and all(a[k]['seen_ids']==b[k]['seen_ids'] for k in a), 'bookmarks changed'
" "$tmp/before.json" "$tmp/state.json" && ok "기존 9개 북마크의 seen_ids 불변, nope 북마크 없음" || ng "북마크 변경됨"

echo "== 결과: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]

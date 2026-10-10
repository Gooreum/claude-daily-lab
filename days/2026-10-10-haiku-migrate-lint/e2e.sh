#!/usr/bin/env bash
# 실제 공개 저장소를 얕게 받아 린트해 본다. 네트워크만 필요하고 API 키·모델 호출은 없다.
# 사용: bash e2e.sh [repo ...]   (기본: anthropics/claude-quickstarts anthropics/claude-cookbooks)
set -u
cd "$(dirname "$0")"
REPOS=("${@:-anthropics/claude-quickstarts anthropics/claude-cookbooks}")
[ $# -eq 0 ] && REPOS=(anthropics/claude-quickstarts anthropics/claude-cookbooks)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
for repo in "${REPOS[@]}"; do
  name=${repo##*/}
  echo "== $repo"
  if ! git clone -q --depth 1 --filter=blob:none "https://github.com/$repo.git" "$WORK/$name" 2>/dev/null; then
    echo "   clone 실패 (네트워크?)"; continue
  fi
  python3 haiku_lint.py --json "$WORK/$name" > "$WORK/$name.json"
  python3 - "$WORK/$name.json" "$WORK/$name" <<'PY'
import json, sys, collections
d = json.load(open(sys.argv[1])); root = sys.argv[2]
by_rule = collections.Counter(f["rule"] for f in d["findings"])
files = {f["file"] for f in d["findings"]}
print(f"   파일 {len(files)}개에서 지적 {len(d['findings'])}건 · 규칙별:", dict(sorted(by_rule.items())))
h1 = collections.Counter(f["fix"].split(" → ")[0] for f in d["findings"] if f["rule"]=="H01")
if h1: print("   남아 있는 구 Haiku ID:", dict(h1))
for f in [f for f in d["findings"] if f["level"]=="error"][:6]:
    print(f"   - {f['rule']} {f['file'].replace(root+'/','')}:{f['line']}  {f['snippet'][:90]}")
PY
done
exit 0

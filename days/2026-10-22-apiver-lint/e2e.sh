#!/usr/bin/env bash
# apiver-lint 실측: 공개 저장소를 얕게 받아 돌린다. 네트워크 필요, 모델 호출 없음. CI에서는 돌리지 않는다.
set -u
cd "$(dirname "$0")"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
for repo in anthropics/claude-cookbooks anthropics/claude-quickstarts; do
  name=${repo#*/}
  if git clone --depth 1 -q "https://github.com/$repo" "$T/$name" 2>/dev/null; then
    echo "== $repo"
    python3 apiver_lint.py "$T/$name" --json | python3 -c '
import json,sys
d=json.load(sys.stdin); s=d["summary"]
print("파일 %d · error %d · warn %d · info %d" % (s["files_scanned"], s["error"], s["warn"], s["info"]))
print("규칙별:", ", ".join("%s×%d" % kv for kv in sorted(s["by_rule"].items())))
'
  else
    echo "== $repo: 받을 수 없음(네트워크). 건너뜀"
  fi
done

#!/usr/bin/env bash
# install.sh <대상 저장소> — 훅 두 개를 <저장소>/.claude/hooks/에 복사하고, settings.json이 없으면 예시를 그대로 둔다.
# 이미 있으면 덮어쓰지 않고 합칠 JSON을 보여 준다. `bash install.sh ~/Code/my-repo`
set -eu
cd "$(dirname "${BASH_SOURCE[0]}")"
target="${1:?usage: install.sh <repo-dir>}"
[ -d "$target" ] || { echo "no such dir: $target" >&2; exit 1; }
mkdir -p "$target/.claude/hooks"
cp hooks/danger-guard.sh hooks/auto-format.sh hooks/rules.txt "$target/.claude/hooks/"
chmod +x "$target/.claude/hooks/"*.sh
echo "copied hooks → $target/.claude/hooks/"
if [ -f "$target/.claude/settings.json" ]; then
  echo "settings.json already exists — merge this into it:"
  cat settings.example.json
else
  cp settings.example.json "$target/.claude/settings.json"
  echo "wrote $target/.claude/settings.json"
fi

#!/usr/bin/env bash
# auto-format.sh — PostToolUse(Write|Edit|MultiEdit) 훅. 방금 쓴 파일을 확장자별 포맷터로 정리한다.
# 포맷터가 없으면 아무것도 하지 않는다. 어떤 경우에도 exit 0 (포맷은 편집을 막을 이유가 아니다).
set -u
file="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("tool_input",{}).get("file_path",""))' 2>/dev/null)" || exit 0
[ -n "$file" ] && [ -f "$file" ] || exit 0
have() { command -v "$1" >/dev/null 2>&1; }
ran=""
case "$file" in
  *.py)   if have ruff; then ruff format -q "$file" >/dev/null 2>&1 && ran=ruff; elif have black; then black -q "$file" >/dev/null 2>&1 && ran=black; fi ;;
  *.js|*.jsx|*.ts|*.tsx|*.json|*.css|*.md|*.yaml|*.yml)
          if have prettier; then prettier --log-level silent --write "$file" >/dev/null 2>&1 && ran=prettier; fi ;;
  *.sh)   if have shfmt; then shfmt -w "$file" >/dev/null 2>&1 && ran=shfmt; fi ;;
  *.go)   if have gofmt; then gofmt -w "$file" >/dev/null 2>&1 && ran=gofmt; fi ;;
esac
[ -n "$ran" ] && echo "auto-format: $ran → $file"
exit 0

#!/usr/bin/env bash
cmd=$(jq -r '.tool_input.command')
case "$cmd" in
  *"rm -rf"*) echo "차단: rm -rf" >&2; exit 2;;
esac
exit 0

#!/usr/bin/env bash
# 안전한 관용구: 지적하면 안 된다
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
T=$(mktemp -d)
rm -rf "$T"/sub
rm -rf /tmp/work-area.$$
echo "예시 문구: rm -rf \$HOME 는 쓰지 말 것"

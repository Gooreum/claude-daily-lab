#!/usr/bin/env bash
# 홈·루트·빈 값이면 멈춘다
dir="$1"
if [ -z "$dir" ] || [ "$(realpath "$dir")" = "/" ] || [ "$(realpath "$dir")" = "$HOME" ]; then
  echo "refusing to wipe: $dir" >&2; exit 2
fi
rm -rf "$dir"/*

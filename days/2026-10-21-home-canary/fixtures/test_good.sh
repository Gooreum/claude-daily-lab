#!/usr/bin/env bash
# 안전한 테스트: 임시 폴더에서만 돈다
T=$(mktemp -d)
touch "$T/a"
bash "$(dirname "$0")/bad_wipe.sh" "$T"

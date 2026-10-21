#!/usr/bin/env bash
# 위험한 테스트: 진짜 홈을 그대로 넘긴다
bash "$(dirname "$0")/bad_wipe.sh" "$HOME"

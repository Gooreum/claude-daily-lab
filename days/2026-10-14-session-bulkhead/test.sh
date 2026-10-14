#!/usr/bin/env bash
# test.sh — session_bulkhead.py 테스트. 키·모델 없이 돈다. 이 폴더에서 `bash test.sh`
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
python3 -m unittest discover -s tests -v 2>&1 | tail -70
exit "${PIPESTATUS[0]}"

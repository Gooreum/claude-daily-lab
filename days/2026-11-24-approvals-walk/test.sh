#!/usr/bin/env bash
# 키·모델·네트워크 없이 도는 테스트. 이 폴더에서 `bash test.sh`.
set -euo pipefail
cd "$(dirname "$0")"
python3 -I -c "import ast; ast.parse(open('approvals_walk.py', encoding='utf-8').read())"
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v test_walk 2>&1
echo "--- 데모: 문서 예시 정책 + 파일 두 개"
python3 approvals_walk.py samples/basic.yml --files src/a.py,.claude/approvals.yml --review pass -v
echo "ALL TESTS PASSED"

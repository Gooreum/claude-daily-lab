#!/usr/bin/env bash
# 네트워크 e2e: 공식 Model deprecations 페이지를 실제로 받아 표를 만들고, 이 저장소 전체를 스캔한다.
# 키·모델 호출 없음. CI의 test.sh에는 넣지 않는다(네트워크 필요).
set -u
cd "$(dirname "$0")"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
echo "[1] live import"
python3 model_stale.py --import live --table "$T/live.json" || { echo "✗ import 실패"; exit 1; }
python3 - "$T/live.json" <<'PY' || exit 1
import json, sys
d = json.load(open(sys.argv[1]))
ids = {m["id"] for m in d["models"]}
assert len(ids) >= 30, len(ids)
assert "claude-fable-5-1" in ids and "claude-sonnet-4-5-20250929" in ids
print("✓ 모델 %d개, 필수 ID 포함" % len(ids))
PY
echo "[2] 이 저장소 스캔 (live 표, 모든 fixtures 폴더와 이 도구 폴더 제외)"
python3 model_stale.py ../.. --table "$T/live.json" --summary --min-level error \
  --exclude 'fixtures' --exclude '2026-10-25-model-stale' | tail -25

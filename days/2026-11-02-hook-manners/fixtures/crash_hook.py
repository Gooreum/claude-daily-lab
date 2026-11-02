#!/usr/bin/env python3
# 나쁜 관찰 훅: 깨진 입력에서 트레이스백(exit 1), 정상 입력은 로그를 stdout에 찍는다.
import json, sys
d = json.load(sys.stdin)
print("got event", d["hook_event_name"])

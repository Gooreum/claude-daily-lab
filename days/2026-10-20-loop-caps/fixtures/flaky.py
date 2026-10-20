#!/usr/bin/env python3
"""호출 횟수를 상태 파일에 세고, argv[2]에 적힌 시나리오대로 응답한다.
사용: flaky.py STATE SCENARIO   (SCENARIO: 쉼표로 이은 ok|fail|quota|errjson|slow|done 목록, 끝나면 마지막 값 반복)"""
import sys, time
state, scenario = sys.argv[1], sys.argv[2].split(",")
try:
    n = int(open(state).read())
except (OSError, ValueError):
    n = 0
open(state, "w").write(str(n + 1))
what = scenario[min(n, len(scenario) - 1)]
if what == "ok":
    print("working")
elif what == "done":
    print("TASK_COMPLETE")
elif what == "fail":
    print("boom: transient error"); sys.exit(1)
elif what == "quota":
    print("API Error: 429 enforced_spend_limit_reached"); sys.exit(1)
elif what == "errjson":
    print('{"type":"result","is_error":true,"result":"x"}')
elif what == "slow":
    time.sleep(5)

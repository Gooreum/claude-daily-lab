#!/usr/bin/env python3
# 모범 관찰 훅: 항상 exit 0, 스스로 데드라인(1.5초), stdout 없음.
import json, signal, sys
signal.signal(signal.SIGALRM, lambda *a: sys.exit(0)); signal.setitimer(signal.ITIMER_REAL, 1.5)
try: json.load(sys.stdin)
except Exception: pass
sys.exit(0)

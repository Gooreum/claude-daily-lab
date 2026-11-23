#!/usr/bin/env bash
# ctx-growth 단위 테스트. 키·네트워크·모델 호출 없음. 정답을 손으로 계산해 둔 합성 트랜스크립트를 쓴다.
set -u
cd "$(dirname "$0")"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ✗ $1"; [ -n "${2:-}" ] && echo "      $2"; }
check() { # 이름, 기대 부분 문자열, 실제 출력
  if printf '%s' "$3" | grep -qF -- "$2"; then ok "$1"; else bad "$1" "기대: $2 / 실제: $(printf '%s' "$3" | head -c 300)"; fi
}
CG="python3 ctx_growth.py"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT

python3 - "$T" <<'PY'
import json, os, sys
T = sys.argv[1]
os.makedirs(f"{T}/a/subagents", exist_ok=True)
os.makedirs(f"{T}/b", exist_ok=True)
def asst(rid, ts, occ, out, blocks, side=False, agent=None, dup=1):
    d = {"type": "assistant", "requestId": rid, "timestamp": f"2026-11-23T{ts}Z", "sessionId": "S", "isSidechain": side,
         "message": {"id": "m_" + rid, "model": "claude-opus-5-5", "content": blocks,
                     "usage": {"input_tokens": 0, "cache_read_input_tokens": occ - 100, "cache_creation_input_tokens": 100,
                               "output_tokens": out}}}
    if agent: d["agentId"] = agent
    return "\n".join([json.dumps(d)] * dup)
def user(nbytes):
    return json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": "x" * nbytes}]}})
TH = {"type": "thinking", "thinking": "", "signature": "S" * 40}       # 본문 없이 서명만 남은 생각 블록
def txt(n): return {"type": "text", "text": "y" * n}

# 스레드 A (환산 계수 4.0 기준 손계산):
#  R1 occ 1000, 출력 600토큰, 보이는 텍스트 400바이트(=100토큰) → 출력 기준 생각 몫 500/600
#  사용자 도구 결과 800바이트(=200토큰)
#  R2 occ 1800 → 증가 800, 보이는 300, 남는 500 → 62.5%
#  R2 출력 400토큰, 보이는 1200바이트(=300토큰), 도구 결과 400바이트(=100토큰)
#  R3 occ 2400 → 증가 600, 보이는 400, 남는 200 → 33.3%
#  R3 출력 100토큰, 보이는 400바이트, 도구 결과 0
#  R4 occ 5000 → 증가 2600, 보이는 100, 남는 2500 → 96.2% (극단 쌍: 합계는 끌려가고 중앙값은 33~62 사이)
A = [
  asst("R1", "10:00:00", 1000, 600, [TH, txt(400)], dup=3),         # 스트리밍 중복 3줄
  user(800),
  asst("R2", "10:01:00", 1800, 400, [TH, txt(1200)]),
  user(400),
  asst("R3", "10:02:00", 2400, 100, [txt(400)]),
  asst("R4", "10:03:00", 5000, 50, [txt(100)]),
  "이건 JSON이 아니다",
  asst("SYN", "10:04:00", 99999, 1, [], dup=1).replace("claude-opus-5-5", "<synthetic>"),
]
open(f"{T}/a/main.jsonl", "w").write("\n".join(A) + "\n")

# 서브에이전트 스레드: 별도 파일, 압축(점유량 감소) 쌍이 하나 있다
S = [
  asst("S1", "10:00:10", 3000, 100, [txt(400)], side=True, agent="x"),
  asst("S2", "10:00:20", 3400, 100, [txt(400)], side=True, agent="x"),
  asst("S3", "10:00:30", 900, 100, [txt(400)], side=True, agent="x"),   # 압축: 증가 ≤ 0 → 건너뜀
  asst("S4", "10:00:40", 1200, 100, [txt(400)], side=True, agent="x"),
]
open(f"{T}/a/subagents/agent-x.jsonl", "w").write("\n".join(S) + "\n")

# 오래된 기록 (--since-days 시험)
O = [asst(f"O{i}", f"09:00:0{i}", 1000 * (i + 1), 10, [txt(40)]).replace("2026-11-23", "2026-01-01") for i in range(4)]
open(f"{T}/b/old.jsonl", "w").write("\n".join(O) + "\n")
PY

echo "[1] 손계산 값과 일치"
OUT=$($CG "$T/a/main.jsonl" --min-pairs 1 --json); RC=$?
[ $RC -eq 0 ] && ok "종료 코드 0" || bad "종료 코드 0" "rc=$RC"
py() { printf '%s' "$OUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
[ "$(py "d['total']['pairs']")" = "3" ] && ok "쌍 3개 (R1→R2, R2→R3, R3→R4; 중복 3줄은 한 요청)" || bad "쌍 3개" "$(py "d['total']")"
[ "$(py "d['total']['growth']")" = "4000" ] && ok "증가 합계 800+600+2600=4000" || bad "증가 합계" "$(py "d['total']['growth']")"
[ "$(py "round(d['total']['median_ratio'],3)")" = "0.625" ] && ok "쌍별 중앙값 62.5% (0.333, 0.625, 0.962의 가운데)" || bad "중앙값" "$(py "d['total']['median_ratio']")"
[ "$(py "round(d['total']['aggregate_ratio'],3)")" = "0.8" ] && ok "합계 기준 80%(남는 3200/증가 4000)는 극단 쌍에 끌려 중앙값보다 크다" || bad "합계 기준" "$(py "d['total']['aggregate_ratio']")"
[ "$(py "d['assistant_lines']")" = "6" ] && ok "중복 줄 포함 assistant 줄 6개 읽음 (R1 3줄+R2+R3+R4, 합성 모델 줄은 제외)" || bad "줄 수" "$(py "d['assistant_lines']")"
[ "$(py "d['bad_lines']")" = "1" ] && ok "깨진 줄 1개를 세고 계속 진행" || bad "깨진 줄" "$(py "d['bad_lines']")"

echo "[2] 출력 기준 교차 점검과 순진한 방법"
# 출력 기준: R1 500/600=0.833, R2 (400-300)/400=0.25, R3 (100-100)/100=0 → 중앙값 0.25
[ "$(py "round(d['total']['out_median'],3)")" = "0.25" ] && ok "출력 기준 중앙값 25% (0.833, 0.25, 0)" || bad "출력 기준" "$(py "d['total']['out_median']")"
# 순진: 생각 블록은 서명 40바이트 ×2(R1,R2)만 남음, 보이는 바이트는 훨씬 큼 → 5% 미만
[ "$(py "d['total']['naive_ratio'] < 0.05")" = "True" ] && ok "순진한 방법은 생각을 5% 미만으로 본다 (서명 길이만 셈)" || bad "순진한 방법" "$(py "d['total']['naive_ratio']")"
[ "$(py "d['total']['median_ratio'] > 10*d['total']['naive_ratio']")" = "True" ] && ok "사용량 증가 방법과 순진한 방법의 차이가 10배 넘게 난다" || bad "차이"

echo "[3] 스레드 분리·압축 쌍"
OUT=$($CG "$T/a" --min-pairs 1 --json)
[ "$(py "len(d['threads'])")" = "2" ] && ok "메인과 서브에이전트가 별도 스레드" || bad "스레드 수" "$(py "len(d['threads'])")"
[ "$(py "d['skipped_pairs']")" = "1" ] && ok "점유량이 줄어든 쌍(압축) 1개를 건너뜀" || bad "건너뜀" "$(py "d['skipped_pairs']")"

echo "[4] 표 출력·옵션"
OUT=$($CG "$T/a" --min-pairs 1 --sensitivity)
check "표 머리글" "생각 몫(중앙값)" "$OUT"
check "판정 통계 표시" "쌍별 중앙값)" "$OUT"
check "민감도 줄" "계수 민감도: 3→" "$OUT"
check "주의 문구" "추정이지 측정값이 아니다" "$OUT"
OUT=$($CG "$T/a" --min-pairs 3)
if printf '%s' "$OUT" | grep -q 'agent-x.jsonl'; then bad "--min-pairs 3이면 서브에이전트 스레드(쌍 2개)를 표에서 뺀다"; else ok "--min-pairs 3이면 서브에이전트 스레드(쌍 2개)를 표에서 뺀다"; fi
OUT=$($CG "$T/a/main.jsonl" --min-pairs 1 --json --bpt 8); M8=$(py "round(d['total']['median_ratio'],3)")
[ "$M8" = "0.812" ] || [ "$M8" = "0.813" ] && ok "계수 8이면 보이는 몫이 작아져 중앙값이 오른다 (0.81)" || bad "계수 8" "$M8"
OUT=$($CG "$T/a/main.jsonl" --min-pairs 1 --json --bpt 3); M3=$(py "round(d['total']['median_ratio'],3)")
[ "$(python3 -c "print($M3 < 0.625)")" = "True" ] && ok "계수 3이면 중앙값이 내려간다 ($M3)" || bad "계수 3" "$M3"

echo "[5] --since-days"
OUT=$($CG "$T/b" --since-days 30 2>&1); RC=$?
[ $RC -eq 1 ] && ok "오래된 기록만 있으면 쌍이 없다고 알리고 exit 1" || bad "since-days 종료 코드" "rc=$RC"
check "쌍 없음 안내" "쌍이 없다" "$OUT"
OUT=$($CG "$T/b" --min-pairs 1 2>&1); RC=$?
[ $RC -eq 0 ] && ok "기간 제한이 없으면 같은 기록을 분석한다" || bad "기간 없음" "rc=$RC"

echo "[6] 오류 처리"
OUT=$($CG "$T/없는폴더" 2>&1); RC=$?
[ $RC -eq 2 ] && ok "기록이 없으면 exit 2" || bad "없는 경로" "rc=$RC"
OUT=$($CG "$T/a" --bpt 0 2>&1); RC=$?
[ $RC -eq 2 ] && ok "--bpt 0이면 exit 2" || bad "bpt 0" "rc=$RC"
: > "$T/empty.jsonl"
OUT=$($CG "$T/empty.jsonl" 2>&1); RC=$?
[ $RC -eq 1 ] && ok "빈 파일은 쌍 없음으로 exit 1 (크래시 없음)" || bad "빈 파일" "rc=$RC out=$OUT"

echo
echo "통과 $PASS, 실패 $FAIL"
[ "$FAIL" -eq 0 ]

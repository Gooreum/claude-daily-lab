#!/usr/bin/env bash
# cache-break 단위 테스트. 키·네트워크·모델 호출 없음. 합성 트랜스크립트(실제 Claude Code 기록과 같은 필드)를 만들어 돌린다.
set -u
cd "$(dirname "$0")"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ✗ $1"; [ -n "${2:-}" ] && echo "      $2"; }
CB="python3 cache_break.py"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT

# --- 합성 기록 만들기 -------------------------------------------------------
python3 - "$T" <<'PY'
import json, os, sys
T = sys.argv[1]
os.makedirs(f"{T}/p/S1/subagents", exist_ok=True)
def line(rid, ts, model, stop, read, w1=0, w5=0, out=100, side=False, agent=None, sess="S1", dup=1):
    d = {"type": "assistant", "requestId": rid, "timestamp": f"2026-10-24T{ts}Z", "sessionId": sess, "isSidechain": side,
         "message": {"id": "msg_" + rid, "model": model, "stop_reason": stop,
                     "usage": {"input_tokens": 3, "cache_read_input_tokens": read,
                               "cache_creation_input_tokens": w1 + w5, "output_tokens": out,
                               "cache_creation": {"ephemeral_1h_input_tokens": w1, "ephemeral_5m_input_tokens": w5}}}}
    if agent: d["agentId"] = agent
    return "\n".join([json.dumps(d)] * dup)
OPUS, SON = "claude-opus-5-5", "claude-sonnet-5-5"
main = [
  line("R1", "12:00:00", OPUS, "end_turn", 0, w1=120000, dup=3),          # 첫 호출 (스트리밍으로 3줄 중복)
  line("R2", "12:00:30", OPUS, "tool_use", 120000, w1=110000),            # 직전 캐시를 다 읽고 덧붙임 → append
  line("R3", "12:02:00", OPUS, "end_turn", 1000, w1=230000),              # TTL 안인데 못 읽음 → prefix-change
  line("R4", "14:00:00", OPUS, "tool_use", 0, w1=235000),                 # 2시간 쉼, 직전 end_turn → idle-expiry
  line("R5", "15:30:00", OPUS, "end_turn", 0, w1=240000),                 # 90분 뒤, 직전 tool_use → tool-wait-expiry
  line("R6", "15:30:10", SON, "end_turn", 0, w5=130000),                  # 모델 전환
  "이건 JSON이 아니다",
  json.dumps({"type": "user", "message": {"content": "hi"}}),
  line("SYN", "15:31:00", "<synthetic>", None, 0),
]
sub = [
  line("A1", "13:00:00", SON, "end_turn", 0, w5=60000, side=True, agent="a1"),   # 임계값 미만
  line("A2", "13:10:00", SON, "end_turn", 0, w5=178000, side=True, agent="a1"),  # 10분 쉰 뒤 후속 → idle-expiry
]
open(f"{T}/p/S1.jsonl", "w").write("\n".join(main + sub) + "\n")
# 별도 파일의 서브에이전트 (경로 /subagents/, agentId 없음)
b = [line("B1", "13:00:00", SON, "tool_use", 0, w5=150000), line("B2", "13:08:00", SON, "end_turn", 0, w5=150000)]
open(f"{T}/p/S1/subagents/agent-b.jsonl", "w").write("\n".join(b) + "\n")
# 가격표에 없는 모델
open(f"{T}/p/S9.jsonl", "w").write(line("U1", "10:00:00", "claude-unknown-9", "end_turn", 0, w1=1000, sess="S9") + "\n")
os.makedirs(f"{T}/home/.claude/projects/x", exist_ok=True)
open(f"{T}/home/.claude/projects/x/s.jsonl", "w").write(line("H1", "09:00:00", SON, "end_turn", 0, w5=500) + "\n")
PY
J() { $CB "$@" --json; }
Q() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

echo "[1] 읽기·중복 제거"
R=$(J $T/p/S1.jsonl $T/p/S1/subagents | Q 'd["requests"]')
[ "$R" = "10" ] && ok "요청 10건 (같은 requestId 3줄→1건, 깨진 줄·user·synthetic 무시)" || bad "요청 수" "got $R"
R=$(J $T/p | Q '(d["requests"], d["meta"]["files"], d["meta"]["bad"], d["meta"]["main_threads"], d["meta"]["sub_threads"])')
[ "$R" = "(11, 3, 1, 2, 2)" ] && ok "폴더 재귀 탐색: 11건·파일 3·읽기 실패 1·메인 2·서브 2" || bad "폴더 탐색" "got $R"
R=$(J $T/p/S1.jsonl | Q 'd["meta"]["lines"] > d["requests"]')
[ "$R" = "True" ] && ok "assistant 줄 수 > 요청 수 (스트리밍 중복)" || bad "줄/요청 수"

echo "[2] 원인 분류"
J $T/p > $T/all.json
cell() { Q "[r for r in d['breakdown'] if r['scope']=='$1' and r['category']=='$2'][0]['$3']" < $T/all.json; }
for sc_cat in main:first-call main:append main:prefix-change main:idle-expiry main:tool-wait-expiry main:model-switch subagent:idle-expiry subagent:first-call subagent:tool-wait-expiry; do
  n=$(cell "${sc_cat%%:*}" "${sc_cat##*:}" count 2>/dev/null)
  [ "$n" = "1" ] && ok "${sc_cat//:/ / } 1건" || bad "${sc_cat//:/ / }" "count=$n"
done
R=$(Q 'sum(r["count"] for r in d["breakdown"])' < $T/all.json)
[ "$R" = "9" ] && ok "큰 쓰기 합계 9건 (A1 6만 토큰은 임계값 미만, U1은 1천)" || bad "큰 쓰기 합계" "got $R"
R=$(cell subagent idle-expiry median_write_tokens)
[ "$R" = "178000" ] && ok "서브에이전트 idle-expiry 중앙값 178000" || bad "중앙값" "got $R"

echo "[3] 비용 계산 (정가)"
R=$(cell main idle-expiry cost_usd)
[ "$R" = "1.88" ] && ok "Opus 5.5 1시간 쓰기 23.5만 × \$8/MTok = \$1.88" || bad "idle 비용" "got $R"
R=$(cell main idle-expiry avoidable_usd)
[ "$R" = "1.833" ] && ok "회피 가능 = 쓰기 비용 − 같은 토큰의 읽기 비용(\$0.20) = \$1.833" || bad "회피 가능" "got $R"
R=$(cell subagent idle-expiry cost_usd)
[ "$R" = "0.445" ] && ok "Sonnet 5.5 5분 쓰기 17.8만 × \$2.5/MTok = \$0.445" || bad "Sonnet 비용" "got $R"
R=$(cell main append avoidable_usd)
[ "$R" = "0.0" ] && ok "append·first-call은 회피 가능 0" || bad "append 회피" "got $R"
R=$(Q '(d["unpriced_requests"], d["tokens"]["w1"])' < $T/all.json)
[ "$R" = "(1, 936000)" ] && ok "가격표에 없는 모델 1건 표시, 토큰은 합산(1시간 쓰기 936000)" || bad "unpriced" "got $R"
python3 - <<'PY' && ok "price_for: 최장 접두 일치·Haiku 5.5 10만 초과 구간" || bad "price_for"
import sys; sys.path.insert(0, ".")
import cache_break as c
assert c.price_for("claude-opus-5-5-20261001", 1)[3] == 0.20
assert c.price_for("claude-opus-5", 1)[3] == 0.50
assert c.price_for("claude-haiku-5-5", 50_000)[0] == 0.10
assert c.price_for("claude-haiku-5-5", 150_000)[0] == 0.50
assert c.price_for("gpt-x", 1) is None
PY

echo "[4] --since / --threshold"
R=$(J $T/p --since 3h --now 2026-10-24T16:00:00Z | Q '[r["category"] for r in d["breakdown"] if r["scope"]=="main"]')
case "$R" in *"idle-expiry"*) case "$R" in *"first-call"*) bad "구간 밖 R1이 first-call로 남음" "$R";; *) ok "--since 3h: 분류는 전체 기록으로 하고 R4는 idle-expiry 유지, 구간 밖 first-call 제외";; esac;; *) bad "--since 3h" "$R";; esac
R=$(J $T/p --threshold 200000 | Q 'd["big"]["count"]')
[ "$R" = "3" ] && ok "--threshold 200000 → 20만 이상 3건(R3·R4·R5)" || bad "threshold" "got $R"

echo "[5] Markdown·조치 제안"
$CB $T/p > $T/out.md
for s in "## 토큰 몫과 비용 몫" "## 큰 캐시 쓰기" "idle-expiry" "새 세션을 연다" "5분 안에 보내거나" "run_in_background" "/model 전환" "가격표에 없는 모델 요청 1건"; do
  grep -qF "$s" $T/out.md && ok "출력에 '$s'" || bad "출력에 '$s' 없음"
done
$CB $T/p --top 0 | grep -q "비싼 재작성 상위" && bad "--top 0인데 목록이 나옴" || ok "--top 0은 목록 생략"
$CB $T/p --threshold 200000 | grep -qF "세션 중간에 바꾸지 않는다" && ok "접두 변경이 큰 쓰기의 30% 이상이면 /compact·CLAUDE.md 조언" || bad "prefix-change 조언 없음"
$CB $T/p --threshold 200000 | grep -qF "직전 캐시를 못 읽고" && ok "prefix-change 조언 문구" || bad "prefix-change 문구"
[ "$($CB $T/p --json | Q 'len(d["top"])')" = "8" ] && ok "--json top: append 제외 8건" || bad "top 건수" "$($CB $T/p --json | Q 'len(d["top"])')"

echo "[6] 종료 코드·기본 경로"
$CB /no/such/path >/dev/null 2>&1; [ $? -eq 2 ] && ok "기록 없음 → exit 2" || bad "exit 2 기대"
$CB $T/p --since 3x >/dev/null 2>&1; [ $? -eq 1 ] && ok "잘못된 --since → exit 1" || bad "exit 1 기대(--since)"
$CB $T/p --threshold 0 >/dev/null 2>&1; [ $? -eq 1 ] && ok "--threshold 0 → exit 1" || bad "exit 1 기대(--threshold)"
$CB $T/p --bogus >/dev/null 2>&1; [ $? -eq 1 ] && ok "모르는 옵션 → exit 1" || bad "exit 1 기대(--bogus)"
$CB $T/p --since 1h --now 2026-10-25T00:00:00Z >/dev/null 2>&1; [ $? -eq 2 ] && ok "구간 안에 기록 없음 → exit 2" || bad "exit 2 기대(빈 구간)"
HOME=$T/home $CB --json | Q 'd["requests"]' | grep -qx 1 && ok "경로 생략 시 \$HOME/.claude/projects" || bad "기본 경로"
$CB $T/p >/dev/null 2>&1; [ $? -eq 0 ] && ok "정상 분석 → exit 0" || bad "exit 0 기대"

echo
echo "통과 $PASS · 실패 $FAIL"
[ "$FAIL" -eq 0 ]

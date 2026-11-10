#!/usr/bin/env bash
# prefix-guard 테스트. 키·모델·네트워크 없이 돈다. 픽스처는 임시 폴더에 만든다.
cd "$(dirname "$0")" || exit 2
G="$PWD/prefix_guard.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0

ok()  { PASS=$((PASS+1)); echo "ok   - $1"; }
bad() { FAIL=$((FAIL+1)); echo "FAIL - $1"; [ -n "${2:-}" ] && echo "       $2"; }
check() { if [ "$2" -eq 0 ]; then ok "$1"; else bad "$1" "${3:-}"; fi; }

# run <옵션...> 파일 → $OUT, $RC
run() { OUT="$(python3 -I "$G" "$@" 2>&1)"; RC=$?; }
has() { echo "$OUT" | grep -qF -- "$1"; }
# cnt <픽스처> <레벨> [코드] [-- 추가옵션...] → 해당 레벨(·코드) 개수
cnt() {
  local f="$1" lv="$2" code="${3:-}"; shift 3 2>/dev/null || shift $#
  python3 -I -c "
import json,sys
d=json.loads(sys.argv[1])
print(sum(1 for f in d if f['level']==sys.argv[2] and (not sys.argv[3] or f['code']==sys.argv[3])))" "$(python3 -I "$G" --json "$@" "$TMP/$f" 2>/dev/null)" "$lv" "$code"
}

# ---------- 픽스처 생성 ----------
python3 -I - "$TMP" <<'PY'
import json, sys, os
out = sys.argv[1]
F, O = "claude-fable-5-2", "claude-opus-5-5"
def T(t): return {"type": "thinking", "thinking": t, "signature": "sig-" + t}
def txt(s): return {"type": "text", "text": s}
def u(s): return {"role": "user", "content": s}
def a(t, s): return {"role": "assistant", "content": [T(t), txt(s)]}
def plain(s): return {"role": "assistant", "content": [txt(s)]}
TOOL = {"name": "get_weather", "description": "d", "input_schema": {"type": "object"}}
TOOL2 = {"name": "get_time", "description": "d", "input_schema": {"type": "object"}}
def R(model, msgs, system="sys", tools=None, **kw):
    d = {"model": model, "max_tokens": 1024, "system": system, "messages": msgs}
    if tools is not None: d["tools"] = tools
    d.update(kw); return d
def w(name, rows, arr=False):
    with open(os.path.join(out, name), "w") as f:
        if arr: json.dump(rows, f)
        else:
            for r in rows: f.write((r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)) + "\n")

A1, A2 = a("t1", "a1"), a("t2", "a2")
base = [u("q0"), A1, u("q1"), A2, u("q2")]
# 1 append-only
w("ok.jsonl", [R(F, base[:1]), R(F, base[:3]), R(F, base)])
# 2 시스템 편집
w("sys.jsonl", [R(F, base[:1]), R(F, base[:3]), R(F, base, system="sys 2")])
# 3 이전 메시지 편집(#2), 4 첫 user 메시지 편집(첫 assistant 턴으로 같은 대화에 묶여야 함)
w("msg.jsonl", [R(F, base[:1]), R(F, base[:3]), R(F, [u("q0"), A1, u("q1 요약됨"), A2, u("q2")])])
w("first.jsonl", [R(F, base[:1]), R(F, base[:3]), R(F, [u("q0 [날짜 11/10]"), A1, u("q1"), A2, u("q2")])])
# 5 도구 추가 / 6 도구 제거
w("tools_add.jsonl", [R(F, base[:1], tools=[TOOL]), R(F, base[:3], tools=[TOOL]), R(F, base, tools=[TOOL, TOOL2])])
w("tools_del.jsonl", [R(F, base[:1], tools=[TOOL, TOOL2]), R(F, base[:3], tools=[TOOL, TOOL2]), R(F, base, tools=[TOOL])])
# 7 thinking 블록 없는 대화의 편집 → WARN만
pl = [u("q0"), plain("a1"), u("q1"), plain("a2"), u("q2")]
w("latent.jsonl", [R(F, pl[:1]), R(F, pl[:3]), R(F, pl, system="sys 2")])
# 8 drop_block
w("drop.jsonl", [R(F, base[:1]), R(F, base[:3]), R(F, base, system="sys 2", thinking={"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}})])
# 9 Opus 대화의 편집 (가정 없이는 문제 없음, --model로 가정하면 ERROR)
w("opus.jsonl", [R(O, base[:1]), R(O, base[:3]), R(O, base, system="sys 2")])
# 10 정적 검사: 각각 다른 대화
w("static.jsonl", [
    R(F, [u("s1")], thinking={"type": "enabled", "budget_tokens": 2000}),
    R(F, [u("s2")], thinking={"type": "disabled"}),
    R(F, [u("s3")], tools=[TOOL], tool_choice={"type": "any"}),
    R(F, [u("s4")], tools=[TOOL], tool_choice={"type": "tool", "name": "get_weather"}),
    R(F, [u("s5")], tools=[{"type": "computer_20251124", "name": "computer", "display_width_px": 1, "display_height_px": 1}]),
    R(F, [u("s6")], tools=[{"type": "advisor_20260301", "name": "advisor", "model": O}]),
    R(F, [u("s7")], output_config={"effort": "max"}),
])
w("static_ok.jsonl", [R(F, [u("c1")], thinking={"type": "adaptive"}, tool_choice={"type": "auto"}, output_config={"effort": "xhigh"},
                       tools=[TOOL, {"type": "advisor_20260301", "name": "advisor", "model": "claude-fable-5-2"}])])
w("static_opus.jsonl", [R(O, [u("o1")], thinking={"type": "enabled", "budget_tokens": 2000}, tool_choice={"type": "any"}, tools=[TOOL])])
# 11 모델 전환(Fable 5.2 → Opus)
w("switch.jsonl", [R(F, base[:1]), R(O, base[:3])])
# 12 응답 대조: 되돌려 보낸 턴에서 thinking 블록이 빠짐 / 그대로 보냄
resp = {"content": [T("t1"), txt("a1")]}
w("altered.jsonl", [{"request": R(F, base[:1]), "response": resp},
                    R(F, [u("q0"), plain("a1"), u("q1")])])
w("altered_ctrl.jsonl", [{"request": R(F, base[:1]), "response": resp}, R(F, base[:3])])
# 13 두 대화가 섞인 로그: 대화 0만 편집
x0, x1 = [u("x0"), a("tx1", "xa1"), u("x1")], [u("y0"), a("ty1", "ya1"), u("y1")]
w("mixed.jsonl", [R(F, x0[:1]), R(F, x1[:1]), R(F, x0, system="바뀜"), R(F, x1)])
# 14 입력 문제
w("badjson.jsonl", [R(F, base[:1]), "{not json", R(F, base[:3])])
w("array.json", [R(F, base[:1]), R(F, base[:3]), R(F, base, system="sys 2")], arr=True)
w("empty_msgs.jsonl", [R(F, [])])
# 15 cache_control만 옮긴 경우 / 문자열·블록 content 동치 / 중간부터 시작한 로그
cc = lambda s: {"role": "user", "content": [{"type": "text", "text": s, "cache_control": {"type": "ephemeral"}}]}
w("cc.jsonl", [R(F, [cc("q0")], system=[{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}]),
               R(F, [u("q0"), A1, cc("q1")], system="sys")])
w("midlog.jsonl", [R(F, base)])
PY

# ---------- 점검 ----------
run "$TMP/ok.jsonl"
check "append-only 대화는 문제 없음(exit 0)" $([ $RC -eq 0 ] && has "문제 없음" && echo 0 || echo 1) "$OUT"

run "$TMP/sys.jsonl"
check "시스템 프롬프트 편집 → ERROR prefix-edit, exit 1, 턴 번호와 해결책" $([ $RC -eq 1 ] && has "ERROR 줄 3 [prefix-edit]" && has "시스템 프롬프트가 바뀜" && has "#1, #3" && has "마지막 user 메시지" && echo 0 || echo 1) "$OUT"
check "  400 메시지를 그대로 안내" $(has 'bound to a different conversation' && echo 0 || echo 1)

run "$TMP/msg.jsonl"
check "이전 메시지 편집 → 메시지 번호와 compaction 안내" $([ $RC -eq 1 ] && has "메시지 #2(user)가 바뀌거나 빠짐" && has "compact-2026-09-04" && echo 0 || echo 1) "$OUT"

run "$TMP/first.jsonl"
check "첫 user 메시지를 고쳐도 같은 대화로 묶여 편집을 찾는다" $([ $RC -eq 1 ] && has "메시지 #0(user)" && has "대화 1개" && echo 0 || echo 1) "$OUT"

run "$TMP/tools_add.jsonl"
check "도구 추가 → '도구 1개 추가(get_time)'와 inline-tools 안내" $([ $RC -eq 1 ] && has "도구 1개 추가(get_time)" && has "inline-tools-2026-09-15" && echo 0 || echo 1) "$OUT"

run "$TMP/tools_del.jsonl"
check "도구 제거 → '도구 목록이 바뀌거나 빠짐'" $([ $RC -eq 1 ] && has "도구 목록이 바뀌거나 빠짐" && echo 0 || echo 1) "$OUT"

run "$TMP/latent.jsonl"
check "thinking 블록이 없는 대화의 편집은 WARN만(exit 0)" $([ $RC -eq 0 ] && has "WARN  줄 3 [prefix-edit-latent]" && ! has "ERROR 줄" && echo 0 || echo 1) "$OUT"

run "$TMP/drop.jsonl"
check "drop_block이 켜져 있으면 ERROR 대신 WARN(exit 0)" $([ $RC -eq 0 ] && has "WARN  줄 3 [prefix-edit]" && has "drop_block" && echo 0 || echo 1) "$OUT"

run "$TMP/opus.jsonl"
check "Opus 대화의 편집은 문제 없음(Fable 5.2 규칙 아님)" $([ $RC -eq 0 ] && has "문제 없음" && echo 0 || echo 1) "$OUT"
run --model claude-fable-5-2 "$TMP/opus.jsonl"
check "--model claude-fable-5-2로 가정하면 같은 로그가 ERROR" $([ $RC -eq 1 ] && has "[prefix-edit]" && has "모든 요청을 claude-fable-5-2로 가정" && echo 0 || echo 1) "$OUT"

run "$TMP/static.jsonl"
check "정적 검사: ERROR 6개(enabled·disabled·any·tool·computer·advisor)" $([ "$(cnt static.jsonl ERROR "")" = 6 ] && echo 0 || echo 1) "$OUT"
check "  각 코드가 나온다" $(has "[thinking-enabled]" && has "[thinking-disabled]" && has "[forced-tool]" && has "[computer-old]" && has "[advisor-model]" && echo 0 || echo 1)
check "  forced-tool은 any·tool 둘 다 잡는다" $([ "$(cnt static.jsonl ERROR forced-tool)" = 2 ] && echo 0 || echo 1)
check "  effort=max는 WARN 1개" $([ "$(cnt static.jsonl WARN effort-max)" = 1 ] && echo 0 || echo 1)
check "  exit 1" $([ $RC -eq 1 ] && echo 0 || echo 1)
run --bedrock "$TMP/static.jsonl"
check "--bedrock이면 computer_20251124는 통과(ERROR 5개)" $([ "$(cnt static.jsonl ERROR "" --bedrock)" = 5 ] && ! has "[computer-old]" && echo 0 || echo 1) "$OUT"

run "$TMP/static_ok.jsonl"
check "adaptive·auto·xhigh·Fable advisor는 문제 없음" $([ $RC -eq 0 ] && has "문제 없음" && echo 0 || echo 1) "$OUT"
run "$TMP/static_opus.jsonl"
check "Opus 요청의 정적 항목은 보지 않는다" $([ $RC -eq 0 ] && has "문제 없음" && echo 0 || echo 1) "$OUT"
run --model claude-mythos-5-2 "$TMP/static_opus.jsonl"
check "--model claude-mythos-5-2 가정이면 정적 ERROR가 나온다" $([ $RC -eq 1 ] && has "[thinking-enabled]" && has "[forced-tool]" && echo 0 || echo 1) "$OUT"

run "$TMP/switch.jsonl"
check "Fable 5.2 → Opus 전환은 INFO(블록이 조용히 버려짐), exit 0" $([ $RC -eq 0 ] && has "INFO  줄 2 [model-switch]" && echo 0 || echo 1) "$OUT"

run "$TMP/altered.jsonl"
check "응답과 다르게 되돌려 보낸 thinking → ERROR turn-altered" $([ $RC -eq 1 ] && has "[turn-altered]" && echo 0 || echo 1) "$OUT"
run "$TMP/altered_ctrl.jsonl"
check "응답 그대로 되돌려 보내면 문제 없음({request,response} 꼴)" $([ $RC -eq 0 ] && has "문제 없음" && echo 0 || echo 1) "$OUT"

run "$TMP/mixed.jsonl"
check "섞인 두 대화를 나눈다(대화 2개)" $(has "대화 2개" && echo 0 || echo 1) "$OUT"
check "  ERROR는 대화 #0에만" $([ "$(cnt mixed.jsonl ERROR "")" = 1 ] && python3 -I -c "
import json,sys;d=json.loads(sys.argv[1]);sys.exit(0 if all(f['conv']==0 for f in d if f['level']=='ERROR') else 1)" "$(python3 -I "$G" --json "$TMP/mixed.jsonl")" && echo 0 || echo 1) "$OUT"

run "$TMP/badjson.jsonl"
check "깨진 JSON 줄은 ERROR bad-json으로 알리고 나머지는 계속 본다(exit 1)" $([ $RC -eq 1 ] && has "ERROR 줄 2 [bad-json]" && has "요청 2개" && echo 0 || echo 1) "$OUT"
run "$TMP/array.json"
check "JSON 배열 입력도 읽는다" $([ $RC -eq 1 ] && has "[prefix-edit]" && echo 0 || echo 1) "$OUT"
run "$TMP/empty_msgs.jsonl"
check "messages가 비면 WARN no-messages로 건너뜀" $([ $RC -eq 0 ] && has "[no-messages]" && echo 0 || echo 1) "$OUT"

run "$TMP/cc.jsonl"
check "cache_control 위치 변화·문자열/블록 content 차이는 편집으로 보지 않는다" $([ $RC -eq 0 ] && has "문제 없음" && echo 0 || echo 1) "$OUT"
run "$TMP/midlog.jsonl"
check "대화 중간부터 시작한 로그는 INFO producer-unknown(exit 0)" $([ $RC -eq 0 ] && has "[producer-unknown]" && echo 0 || echo 1) "$OUT"

run "$TMP/없는파일.jsonl"
check "없는 파일은 exit 2" $([ $RC -eq 2 ] && echo 0 || echo 1) "$OUT"

OUT="$(python3 -I "$G" --json "$TMP/sys.jsonl" 2>&1)"
check "--json 출력은 올바른 JSON 배열" $(python3 -I -c "import json,sys;d=json.loads(sys.argv[1]);assert d and d[0]['code']=='prefix-edit'" "$OUT" && echo 0 || echo 1) "$OUT"

run examples/session.jsonl
check "예시 로그: 시스템 날짜 갱신(줄 3)과 thinking enabled(줄 4)를 잡는다" $([ $RC -eq 1 ] && has "ERROR 줄 3 [prefix-edit]" && has "ERROR 줄 4 [thinking-enabled]" && has "ERROR 2, WARN 0, INFO 0" && echo 0 || echo 1) "$OUT"

run "$TMP/ok.jsonl" --bogus-flag
check "알 수 없는 옵션은 exit 2(argparse)" $([ $RC -eq 2 ] && echo 0 || echo 1) "$OUT"

echo
echo "통과 $PASS, 실패 $FAIL"
[ "$FAIL" -eq 0 ]

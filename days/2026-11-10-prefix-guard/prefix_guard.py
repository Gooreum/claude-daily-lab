#!/usr/bin/env python3
"""prefix-guard — Messages API 요청 로그(JSONL)를 이어 읽어 Claude Fable 5.2의 400 사유를 미리 찾는다.

Fable 5.2·Mythos 5.2는 이전 턴의 thinking 블록을 돌려보낼 때, 그 블록이 만들어진 뒤
시스템 프롬프트·도구 목록·이전 메시지가 바뀌었으면 400("The block is bound to a different
conversation")을 낸다. 소스 코드만 봐서는 이 편집이 보이지 않으므로, 실제로 오간 요청을
순서대로 비교한다. 요청 한 개로 볼 수 있는 400 사유(thinking 끄기, 강제 tool_choice,
옛 computer 도구, advisor 불일치)도 같이 본다.

입력: 한 줄에 요청 본문 하나인 JSONL (또는 JSON 배열). 항목은 요청 본문이거나
      {"request": {...}, "response": {...}} 꼴이다("response"가 있으면 되돌려 보낸 assistant 턴도 대조한다).
사용: python3 prefix_guard.py LOG.jsonl [--model ID] [--bedrock] [--json]
종료 코드: 0 = ERROR 없음, 1 = ERROR 있음, 2 = 입력을 읽을 수 없음.
외부 패키지·네트워크·키가 필요 없다(표준 라이브러리만).
"""
import argparse
import json
import sys

TARGET_PREFIXES = ("claude-fable-5-2", "claude-mythos-5-2")
LEVEL_ORDER = {"ERROR": 0, "WARN": 1, "INFO": 2}

HINTS = {
    "system": "매 턴 바뀌는 값(날짜·사용자 이름 등)은 시스템 프롬프트 대신 마지막 user 메시지에 넣으세요.",
    "tools-added": "도구를 추가하려면 tools를 고치지 말고 role:system 메시지로 바꾸세요(베타 inline-tools-2026-09-15).",
    "tools": "대화 중간에 도구 목록을 바꾸지 말고 새 대화에서 바꾸세요. 추가·제거는 role:system 메시지(베타)를 쓸 수 있습니다.",
    "message": "기록을 줄여야 하면 앞 메시지를 고치지 말고 compaction on demand(베타 compact-2026-09-04)를 쓰세요.",
}


def is_target(model):
    return isinstance(model, str) and model.startswith(TARGET_PREFIXES)


def strip_cc(x):
    """cache_control은 내용이 아니라 캐시 표시라서 비교에서 뺀다."""
    if isinstance(x, dict):
        return {k: strip_cc(v) for k, v in x.items() if k != "cache_control"}
    if isinstance(x, list):
        return [strip_cc(v) for v in x]
    return x


def norm_content(c):
    if isinstance(c, str):
        return [{"type": "text", "text": c}]
    return strip_cc(c) if isinstance(c, list) else []


def norm_msg(m):
    if not isinstance(m, dict):
        return {"role": "?", "content": []}
    return {"role": m.get("role"), "content": norm_content(m.get("content"))}


def thinking_blocks(msg):
    return [b for b in msg["content"] if isinstance(b, dict) and b.get("type") in ("thinking", "redacted_thinking")]


def canon(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False)


class Entry:
    def __init__(self, line, req, resp):
        self.line = line
        self.req = req
        self.model = req.get("model")
        raw_msgs = req.get("messages")
        self.msgs = [norm_msg(m) for m in raw_msgs] if isinstance(raw_msgs, list) else []
        self.system = norm_content(req.get("system")) if req.get("system") is not None else []
        raw_tools = req.get("tools")
        self.tools = strip_cc(raw_tools) if isinstance(raw_tools, list) else []
        self.resp_content = None
        if isinstance(resp, dict) and isinstance(resp.get("content"), list):
            self.resp_content = strip_cc(resp["content"])
        self.conv = None


def load(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    items = []  # (line, obj or None, error)
    stripped = text.lstrip()
    if stripped.startswith("["):
        try:
            arr = json.loads(text)
        except ValueError as e:
            return None, "JSON 배열을 읽을 수 없음: %s" % e
        items = [(i + 1, o, None) for i, o in enumerate(arr)]
    else:
        for n, raw in enumerate(text.splitlines(), 1):
            if not raw.strip():
                continue
            try:
                items.append((n, json.loads(raw), None))
            except ValueError as e:
                items.append((n, None, str(e)))
    return items, None


def unwrap(obj):
    if isinstance(obj, dict):
        for key in ("request", "body"):
            if isinstance(obj.get(key), dict):
                return obj[key], obj.get("response")
    return obj, None


def group(entries):
    """첫 메시지가 같거나, 첫 assistant 턴(=API가 돌려준 그대로)이 같으면 같은 대화로 본다.
    첫 user 메시지를 매 턴 고쳐 쓰는 경우도 같은 대화로 묶기 위해서다."""
    by_first, by_second, convs = {}, {}, []
    for e in entries:
        k1 = canon(e.msgs[0]) if e.msgs else None
        k2 = canon(e.msgs[1]) if len(e.msgs) > 1 else None
        idx = by_first.get(k1) if k1 else None
        if idx is None and k2:
            idx = by_second.get(k2)
        if idx is None:
            idx = len(convs)
            convs.append([])
        convs[idx].append(e)
        e.conv = idx
        if k1:
            by_first.setdefault(k1, idx)
        if k2:
            by_second.setdefault(k2, idx)
    return convs


def diff_prefix(prod, cur, k):
    """producer 요청 시점의 앞부분(시스템·도구·messages[:k])과 지금 요청을 비교한다."""
    res = []
    if prod.system != cur.system:
        res.append(("system", "시스템 프롬프트가 바뀜"))
    if prod.tools != cur.tools:
        n = len(prod.tools)
        if len(cur.tools) > n and cur.tools[:n] == prod.tools:
            names = [t.get("name") or t.get("type") for t in cur.tools[n:] if isinstance(t, dict)]
            res.append(("tools-added", "도구 %d개 추가(%s)" % (len(names), ", ".join(map(str, names)))))
        else:
            res.append(("tools", "도구 목록이 바뀌거나 빠짐"))
    for i in range(min(k, len(prod.msgs))):
        if i >= len(cur.msgs) or cur.msgs[i] != prod.msgs[i]:
            res.append(("message", "메시지 #%d(%s)가 바뀌거나 빠짐" % (i, prod.msgs[i]["role"])))
            break
    return res


def effective(e, assume):
    return assume or e.model


def check_static(e, assume, bedrock, out):
    model = effective(e, assume)
    if not is_target(model):
        return
    req = e.req
    th = req.get("thinking")
    if isinstance(th, dict):
        if th.get("type") == "enabled":
            out(e, "ERROR", "thinking-enabled", "thinking.type=enabled(budget_tokens)는 Fable 5.2에서 400. thinking을 빼거나 adaptive로 두고 effort로 깊이를 조절하세요.")
        elif th.get("type") == "disabled":
            out(e, "ERROR", "thinking-disabled", "thinking.type=disabled는 Fable 5.2에서 400(적응형 생각은 항상 켜짐). thinking을 빼고 낮은 effort를 쓰세요.")
    tc = req.get("tool_choice")
    if isinstance(tc, dict) and tc.get("type") in ("any", "tool"):
        out(e, "ERROR", "forced-tool", "tool_choice=%s는 Fable 5.2에서 400. auto로 두고 strict:true나 JSON 출력을 쓰세요." % tc.get("type"))
    for t in e.tools:
        if not isinstance(t, dict):
            continue
        ttype = str(t.get("type", ""))
        if ttype == "computer_20251124" and not bedrock:
            out(e, "ERROR", "computer-old", "computer_20251124는 Bedrock 밖에서 400. computer_toolset_20260801로 옮기세요(Bedrock이면 --bedrock).")
        if ttype.startswith("advisor"):
            adv = t.get("model")
            if not is_target(adv):
                out(e, "ERROR", "advisor-model", "Fable 5.2 실행기의 advisor는 claude-fable-5-2나 claude-mythos-5-2여야 합니다(지금: %s)." % adv)
    oc = req.get("output_config")
    effort = (oc.get("effort") if isinstance(oc, dict) else None) or req.get("effort")
    if effort == "max":
        out(e, "WARN", "effort-max", "effort=max는 생각에 출력 상한(128k)을 다 쓰고 답을 못 내는 사례가 보고됐습니다. xhigh부터 재 보세요.")


def check_history(conv, assume, out):
    for pos, cur in enumerate(conv):
        cur_model = effective(cur, assume)
        bind = None
        th = cur.req.get("thinking")
        if isinstance(th, dict) and isinstance(th.get("block_binding"), dict):
            bind = th["block_binding"].get("prefix_mismatch_behavior")
        drop = bind == "drop_block"
        errs, affected, unknown, switched = [], [], 0, []
        altered = []
        for k, m in enumerate(cur.msgs):
            if m["role"] != "assistant":
                continue
            tb = thinking_blocks(m)
            prod = None
            for cand in reversed(conv[:pos]):
                if len(cand.msgs) == k:
                    prod = cand
                    break
            if prod is None:
                if tb:
                    unknown += 1
                continue
            prod_model = effective(prod, assume)
            # 응답이 로그에 있으면, 받은 thinking 블록을 하나도 빼지 않고 같은 순서로 보냈는지 본다(블록이 통째로 빠진 경우 포함).
            if prod.resp_content is not None and is_target(prod_model) and is_target(cur_model):
                got = [b for b in prod.resp_content if isinstance(b, dict) and b.get("type") in ("thinking", "redacted_thinking")]
                if got and canon(tb) != canon(got):
                    altered.append(k)
            if not tb:
                continue
            if is_target(prod_model) and not is_target(cur_model):
                switched.append(k)
                continue
            if not (is_target(prod_model) and is_target(cur_model)):
                continue
            d = diff_prefix(prod, cur, k)
            if d:
                affected.append(k)
                for item in d:
                    if item not in errs:
                        errs.append(item)
        if errs:
            level = "WARN" if drop else "ERROR"
            what = "; ".join(x[1] for x in errs)
            msg = "thinking 블록이 든 assistant 턴 %s이(가) 만들어진 뒤 앞부분이 바뀜 → %s." % (
                ", ".join("#%d" % k for k in affected), what)
            if drop:
                msg += " drop_block이 켜져 있어 400 대신 블록이 버려집니다(출력 토큰이 늘 수 있음)."
            else:
                msg += " 이대로 보내면 400 \"The block is bound to a different conversation\"."
            seen = []
            for kind, _ in errs:
                if kind not in seen:
                    seen.append(kind)
            msg += " 고치는 법: " + " / ".join(HINTS[k] for k in seen)
            out(cur, level, "prefix-edit", msg)
        if altered:
            level = "WARN" if drop else "ERROR"
            out(cur, level, "turn-altered", "assistant 턴 %s의 thinking 블록이 API가 돌려준 응답과 다릅니다(빠졌거나 순서·내용이 바뀜). 모든 블록을 받은 그대로 보내야 합니다." % ", ".join("#%d" % k for k in altered))
        if switched:
            out(cur, "INFO", "model-switch", "Fable 5.2가 만든 thinking 블록(assistant 턴 %s)은 %s로 보내면 조용히 버려져 그 추론 맥락을 잃습니다(요청은 성공)." % (
                ", ".join("#%d" % k for k in switched), cur_model))
        if unknown:
            out(cur, "INFO", "producer-unknown", "thinking 블록 %d개를 만든 요청이 로그에 없어 앞부분 비교를 못 했습니다(로그가 대화 중간부터 시작?)." % unknown)
        # thinking 블록이 없는 구간의 편집은 오늘 당장 400은 아니지만 이후 400의 씨앗이다.
        if pos > 0 and is_target(cur_model) and not errs and not altered:
            prev = conv[pos - 1]
            d = diff_prefix(prev, cur, len(prev.msgs))
            if d:
                out(cur, "WARN", "prefix-edit-latent", "앞 요청 대비 앞부분이 바뀜 → %s. 지금은 되돌려 보낸 thinking 블록이 없어 통과하지만, 이 뒤로 Fable 5.2가 만든 블록을 보내는 순간 400이 되고 프롬프트 캐시도 깨집니다." % "; ".join(x[1] for x in d))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fable 5.2 prefix check를 요청 로그로 미리 점검한다.")
    ap.add_argument("log", help="요청 본문이 한 줄에 하나인 JSONL(또는 JSON 배열)")
    ap.add_argument("--model", help="모든 요청이 이 모델로 갔다고 가정하고 본다(예: claude-fable-5-2로 옮기면 어떻게 되나)")
    ap.add_argument("--bedrock", action="store_true", help="Amazon Bedrock이면 computer_20251124를 허용")
    ap.add_argument("--json", action="store_true", help="결과를 JSON 배열로 출력")
    args = ap.parse_args(argv)

    try:
        items, err = load(args.log)
    except OSError as e:
        print("읽을 수 없음: %s" % e, file=sys.stderr)
        return 2
    if err:
        print(err, file=sys.stderr)
        return 2

    findings = []

    def out(entry, level, code, msg):
        findings.append({"line": entry.line if entry else None, "conv": entry.conv if entry else None,
                         "level": level, "code": code, "message": msg})

    entries = []
    for line, obj, perr in items:
        if perr is not None:
            findings.append({"line": line, "conv": None, "level": "ERROR", "code": "bad-json", "message": "JSON이 아님: %s" % perr})
            continue
        req, resp = unwrap(obj)
        if not isinstance(req, dict):
            findings.append({"line": line, "conv": None, "level": "ERROR", "code": "bad-entry", "message": "요청 본문이 객체가 아님"})
            continue
        e = Entry(line, req, resp)
        if not e.msgs:
            findings.append({"line": line, "conv": None, "level": "WARN", "code": "no-messages", "message": "messages가 없거나 비어 있어 건너뜀"})
            continue
        entries.append(e)

    convs = group(entries)
    for e in entries:
        check_static(e, args.model, args.bedrock, out)
    for conv in convs:
        check_history(conv, args.model, out)

    findings.sort(key=lambda f: (f["conv"] if f["conv"] is not None else -1, f["line"] or 0, LEVEL_ORDER[f["level"]]))
    counts = {lv: sum(1 for f in findings if f["level"] == lv) for lv in LEVEL_ORDER}

    if args.json:
        print(json.dumps(findings, ensure_ascii=False, indent=2))
    else:
        print("prefix-guard: 요청 %d개, 대화 %d개%s" % (len(entries), len(convs),
              " (모든 요청을 %s로 가정)" % args.model if args.model else ""))
        last = object()
        for f in findings:
            if f["conv"] != last:
                last = f["conv"]
                if f["conv"] is None:
                    print("\n[입력 문제]")
                else:
                    c = convs[f["conv"]]
                    first = c[0].msgs[0]["content"]
                    snippet = (first[0].get("text", "") if first and isinstance(first[0], dict) else "")[:30].replace("\n", " ")
                    print("\n[대화 #%d] 요청 %d개(줄 %s), 첫 메시지: \"%s\"" % (
                        f["conv"], len(c), ",".join(str(x.line) for x in c), snippet))
            print("  %-5s 줄 %s [%s] %s" % (f["level"], f["line"], f["code"], f["message"]))
        print("\n요약: ERROR %d, WARN %d, INFO %d" % (counts["ERROR"], counts["WARN"], counts["INFO"]))
        if not findings:
            print("문제 없음.")
    return 1 if counts["ERROR"] else 0


if __name__ == "__main__":
    sys.exit(main())

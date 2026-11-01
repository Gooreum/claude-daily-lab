#!/usr/bin/env python3
"""mcp-probe — stdio MCP 서버가 프로토콜 최소 요건을 지키는지 키·모델 없이 검사한다.

사용: python3 mcp_probe.py [--timeout 5] [--json] [--strict] -- <서버 명령...>
예:   python3 mcp_probe.py -- node my-server.js
종료 코드: error가 있으면 1 (--strict면 warn도), 아니면 0, 사용법 오류 2.
표준 라이브러리만 쓴다.
"""
import argparse, json, queue, subprocess, sys, threading, time

PROTO = "2025-06-18"
CHECKS = {
    "P01": "initialize가 protocolVersion·capabilities·serverInfo를 담은 결과로 답한다",
    "P02": "stdout에는 JSON-RPC 메시지만 나온다 (로그는 stderr로)",
    "P03": "알림(id 없음)과 요청하지 않은 id에는 답하지 않는다",
    "P04": "ping이 빈 결과로 답한다",
    "P05": "tools/list가 name·inputSchema(type=object)가 있는 도구 배열을 준다",
    "P06": "모르는 메서드에 -32601 오류를 낸다",
    "P07": "모르는 도구 호출에 -32602 프로토콜 오류를 낸다 (isError 결과가 아니라)",
    "P08": "필수 인자를 빼고 부르면 성공 결과로 답하지 않는다",
    "P09": "요청 두 개를 연달아 보내도 응답이 id로 정확히 짝지어진다",
    "P10": "응답마다 jsonrpc 2.0과 요청의 id(타입 포함)를 그대로 돌려준다",
    "P11": "깨진 JSON 한 줄을 받아도 죽지 않고 다음 요청에 답한다",
    "P12": "stdin이 닫히면 제때 종료한다",
}


class Server:
    def __init__(self, cmd, timeout):
        self.timeout = timeout
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.q = queue.Queue()
        self.bad_lines = []      # JSON이 아닌 stdout 줄
        self.pending = {}        # 보낸 요청 id -> 메서드 (아직 답 못 받은 것)
        self.spurious = []       # 요청하지 않은 id의 응답
        self.sent = set()        # 보낸 모든 요청 id
        self.methods = {}        # 답을 받은 id -> 메서드
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.p.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                self.bad_lines.append(line[:80])
                continue
            self.q.put(msg)
        self.q.put(None)  # EOF

    def send(self, obj):
        raw = obj if isinstance(obj, str) else json.dumps(obj)
        try:
            self.p.stdin.write(raw + "\n")
            self.p.stdin.flush()
        except (BrokenPipeError, ValueError):
            pass

    def request(self, rid, method, params=None):
        self.pending[rid] = method
        self.sent.add(rid)
        m = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            m["params"] = params
        self.send(m)

    def notify(self, method, params=None):
        m = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            m["params"] = params
        self.send(m)

    def collect(self, ids):
        """ids에 해당하는 응답을 모두 받을 때까지 기다린다. {id: msg} 반환, 못 받은 건 빠짐."""
        got, deadline = {}, time.time() + self.timeout
        want = set(ids)
        while want - set(got):
            left = deadline - time.time()
            if left <= 0:
                break
            try:
                msg = self.q.get(timeout=left)
            except queue.Empty:
                break
            if msg is None:
                self.q.put(None)
                break
            if not isinstance(msg, dict) or "method" in msg:
                continue  # 서버가 보낸 알림·요청은 무시
            rid = msg.get("id")
            if rid in self.pending and not isinstance(rid, bool):
                self.methods[rid] = self.pending.pop(rid)
                got[rid] = msg
            else:
                self.spurious.append(msg)
        return got

    def alive(self):
        return self.p.poll() is None


def run(cmd, timeout):
    F = []  # (code, level, message)

    def add(code, level, msg):
        F.append((code, level, msg))

    try:
        s = Server(cmd, timeout)
    except OSError as e:
        return [("P00", "error", f"서버를 띄우지 못함: {e}")], 0

    ran = 0
    # --- P01 initialize
    ran += 1
    s.request(1, "initialize", {"protocolVersion": PROTO, "capabilities": {},
                                 "clientInfo": {"name": "mcp-probe", "version": "0.1"}})
    r = s.collect([1]).get(1)
    if r is None:
        if any(isinstance(m.get("id"), str) and m["id"] == "1" for m in s.spurious):
            add("P10", "error", "id를 문자열로 바꿔 돌려줌 (보낸 1, 받은 '1') — 클라이언트가 응답을 못 찾는다")
            s.p.kill()
            return F, ran
        add("P01", "error", "initialize에 %d초 안에 답이 없음%s" % (
            timeout, "" if s.alive() else f" (서버가 종료됨, rc={s.p.poll()})"))
        s.p.kill()
        return F, ran
    res = r.get("result")
    if not isinstance(res, dict):
        add("P01", "error", f"initialize가 result 없이 답함: {json.dumps(r)[:80]}")
    else:
        miss = [k for k in ("protocolVersion", "capabilities", "serverInfo") if k not in res]
        if miss:
            add("P01", "error", "initialize 결과에 빠진 필드: " + ", ".join(miss))
    id_ok = [r]
    s.notify("notifications/initialized")

    # --- P04 ping (알림 뒤에 보내 P03도 함께 본다)
    ran += 1
    s.request(2, "ping")
    r = s.collect([2]).get(2)
    if r is None:
        add("P04", "error", "ping에 답이 없음")
    else:
        id_ok.append(r)
        if r.get("result") != {}:
            add("P04", "warn", f"ping 결과가 빈 객체가 아님: {json.dumps(r.get('result'))[:60]}")

    # --- P05 tools/list
    ran += 1
    s.request(3, "tools/list")
    r = s.collect([3]).get(3)
    tools = []
    if r is None:
        add("P05", "error", "tools/list에 답이 없음")
    elif "result" not in r or not isinstance(r["result"].get("tools"), list):
        add("P05", "error", "tools/list 결과에 tools 배열이 없음")
    else:
        id_ok.append(r)
        tools = r["result"]["tools"]
        for t in tools:
            nm = t.get("name") if isinstance(t, dict) else None
            sch = t.get("inputSchema") if isinstance(t, dict) else None
            if not nm:
                add("P05", "error", "name이 없는 도구가 있음")
            elif not isinstance(sch, dict) or sch.get("type") != "object":
                add("P05", "error", f"도구 {nm}: inputSchema.type이 object가 아님")

    # --- P06 모르는 메서드
    ran += 1
    s.request(4, "mcp-probe/no-such-method")
    r = s.collect([4]).get(4)
    if r is None:
        add("P06", "error", "모르는 메서드에 답이 없음 (클라이언트가 대기하게 됨)")
    else:
        id_ok.append(r)
        code = (r.get("error") or {}).get("code")
        if "error" not in r:
            add("P06", "error", "모르는 메서드에 성공 결과로 답함")
        elif code != -32601:
            add("P06", "warn", f"모르는 메서드의 오류 코드가 {code} (기대 -32601)")

    # --- P07 모르는 도구
    ran += 1
    s.request(5, "tools/call", {"name": "mcp-probe-no-such-tool", "arguments": {}})
    r = s.collect([5]).get(5)
    if r is None:
        add("P07", "error", "모르는 도구 호출에 답이 없음")
    else:
        id_ok.append(r)
        if "error" in r:
            code = r["error"].get("code")
            if code != -32602:
                add("P07", "warn", f"모르는 도구의 오류 코드가 {code} (기대 -32602)")
        elif (r.get("result") or {}).get("isError"):
            add("P07", "warn", "모르는 도구를 isError 결과로 답함 — 프로토콜 오류(-32602)여야 함")
        else:
            add("P07", "error", "모르는 도구 호출이 성공 결과로 끝남")

    # --- P08 필수 인자 누락
    target = next((t for t in tools if isinstance(t, dict)
                   and (t.get("inputSchema") or {}).get("required")), None)
    if target:
        ran += 1
        s.request(6, "tools/call", {"name": target["name"], "arguments": {}})
        r = s.collect([6]).get(6)
        if r is None:
            add("P08", "error", f"도구 {target['name']}: 필수 인자 없는 호출에 답이 없음")
        else:
            id_ok.append(r)
            if "error" not in r and not (r.get("result") or {}).get("isError"):
                add("P08", "error", f"도구 {target['name']}: 필수 인자 {target['inputSchema']['required']} 없이도 성공으로 답함")

    # --- P09 연달아 보낸 요청
    ran += 1
    s.request(7, "ping")
    s.request(8, "tools/list")
    got = s.collect([7, 8])
    if set(got) != {7, 8}:
        add("P09", "error", "연달아 보낸 요청 중 답이 오지 않은 id: %s" % sorted({7, 8} - set(got)))
    else:
        id_ok.extend(got.values())

    # --- P11 깨진 JSON
    ran += 1
    s.send('{"jsonrpc": "2.0", "id": 9, "method": ')
    time.sleep(0.2)
    s.request(10, "ping")
    got = s.collect([10])
    if 10 not in got:
        add("P11", "error", "깨진 JSON 한 줄 뒤에 서버가 죽었거나 답하지 않음" + ("" if s.alive() else f" (rc={s.p.poll()})"))
    else:
        id_ok.append(got[10])

    # --- P10 응답 형식
    ran += 1
    bad = []
    for m in id_ok:
        if m.get("jsonrpc") != "2.0":
            bad.append("jsonrpc 값이 2.0이 아님")
    # id를 문자열로 바꿔 돌려주면 collect가 짝을 못 찾아 spurious로 빠진다 → 여기서 타입 문제로 따로 보고
    retyped = [m for m in s.spurious if m.get("id") is not None and str(m.get("id")) in {str(i) for i in s.sent}
               and m.get("id") not in s.sent]
    if retyped:
        bad.append("id 타입이 요청과 다름 (보낸 %s, 받은 %r)" % (
            "정수", retyped[0].get("id")))
    if bad:
        add("P10", "error", "; ".join(sorted(set(bad))))

    # --- P03 요청하지 않은 응답
    ran += 1
    # 깨진 JSON(id 9)에 대한 -32700 응답은 허용한다 (id가 null이거나 9)
    extra = [m for m in s.spurious if not (
        (m.get("error") or {}).get("code") == -32700 or m.get("id") in (None, 9) or m in retyped)]
    if extra:
        add("P03", "error", "요청하지 않은 id의 응답이 옴: " + json.dumps(extra[0])[:80])
    elif any(m.get("id") is None and "error" not in m for m in s.spurious):
        add("P03", "error", "알림에 응답을 보냄 (id 없는 성공 응답)")

    # --- P02 stdout 청결
    ran += 1
    if s.bad_lines:
        add("P02", "error", f"stdout에 JSON이 아닌 줄 {len(s.bad_lines)}개: {s.bad_lines[0]!r}")

    # --- P12 stdin 종료
    ran += 1
    try:
        s.p.stdin.close()
    except OSError:
        pass
    try:
        s.p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        add("P12", "warn", f"stdin을 닫은 뒤 {timeout}초가 지나도 종료하지 않음")
        s.p.kill()
    return F, ran


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--timeout", type=float, default=5.0, help="응답 대기 초 (기본 5)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="warn도 실패로 친다")
    ap.add_argument("--list", action="store_true", help="검사 목록만 출력")
    ap.add_argument("cmd", nargs=argparse.REMAINDER, help="-- 뒤에 서버 명령")
    a = ap.parse_args(argv)
    if a.list:
        for k, v in CHECKS.items():
            print(f"{k}  {v}")
        return 0
    cmd = a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd
    if not cmd:
        ap.print_usage(sys.stderr)
        return 2
    F, ran = run(cmd, a.timeout)
    errs = sum(1 for f in F if f[1] == "error")
    warns = sum(1 for f in F if f[1] == "warn")
    if a.json:
        print(json.dumps({"command": cmd, "checks_run": ran, "errors": errs, "warnings": warns,
                          "findings": [{"code": c, "level": l, "message": m} for c, l, m in F]},
                         ensure_ascii=False, indent=2))
    else:
        for c, l, m in F:
            print(f"{l:5} {c}: {m}")
        print(f"검사 {ran}개 · error {errs} · warn {warns}")
    return 1 if errs or (a.strict and warns) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""mod-audit — Claude Code 모드(mod)를 설치하기 전에 정적으로 훑는다.

플러그인 폴더의 hooks.json `modules`가 가리키는 JS/TS를 읽어 (1) 처리하는 훅 이벤트,
(2) 쓰는 `$.` API, (3) 번들 MCP 서버의 실행 명령을 뽑고 위험 신호를 짚는다.
`claude` CLI도 모델도 필요 없다(표준 라이브러리만). 종료 코드: 0=error 없음, 1=error 있음, 2=사용 오류.
"""
import argparse
import json
import os
import re
import sys

GATING = {"tool.check", "tool.call", "prompt.submit"}
# 호출 → (등급, 코드, 설명)
RISKY_CALLS = {
    "process.run": ("error", "MA01", "프로세스를 띄운다. 샌드박스 밖에서 내 계정 권한으로 돈다"),
    "process.spawn": ("error", "MA01", "프로세스를 띄운다. 샌드박스 밖에서 내 계정 권한으로 돈다"),
    "http.fetch": ("warn", "MA02", "네트워크 요청을 보낸다"),
    "env.get": ("warn", "MA03", "환경 변수를 읽는다 (API 키가 들어 있을 수 있다)"),
    "settings.read": ("warn", "MA03", "설정 파일을 읽는다 (API 키가 들어 있을 수 있다)"),
    "model.complete": ("warn", "MA04", "모델을 호출한다. 대화 내용이 나가고 토큰이 든다"),
}
LAUNCHERS = {"npx", "bunx", "uvx", "pipx"}


def blank_comments(src):
    """주석을 공백으로 바꾼다(줄 번호 유지). 문자열 안의 `//`(예: https://)는 남긴다."""
    out, i, n, q = [], 0, len(src), None
    while i < n:
        c = src[i]
        if q:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(src[i + 1]); i += 2; continue
            if c == q:
                q = None
            i += 1
        elif c in "'\"`":
            q = c; out.append(c); i += 1
        elif src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i)); i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", src[i:j])); i = j
        else:
            out.append(c); i += 1
    return "".join(out)


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def find_plugins(root):
    found = []
    for d, dirs, _ in os.walk(root):
        dirs[:] = [x for x in dirs if x not in ("node_modules", ".git")]
        if os.path.isfile(os.path.join(d, ".claude-plugin", "plugin.json")):
            found.append(d)
    return sorted(found)


def inside(root, path):
    root = os.path.realpath(root)
    path = os.path.realpath(path)
    return path == root or path.startswith(root + os.sep)


def mcp_servers(plugin_dir, manifest):
    servers = {}
    inline = manifest.get("mcpServers")
    if isinstance(inline, dict):
        servers.update(inline)
    mcp = load_json(os.path.join(plugin_dir, ".mcp.json"))
    if isinstance(mcp, dict):
        body = mcp.get("mcpServers", mcp)
        if isinstance(body, dict):
            servers.update({k: v for k, v in body.items() if isinstance(v, dict)})
    return servers


def pinned(arg):
    """패키지 인자가 정확한 버전으로 고정됐는가. latest/범위/버전 없음은 False."""
    if arg.endswith("@latest"):
        return False
    m = re.search(r"(?:@|==)(\d+\.\d+\.\d+[\w.\-+]*)$", arg)
    return bool(m)


def audit_mcp(plugin, name, spec, add):
    cmd = str(spec.get("command", ""))
    args = [str(a) for a in spec.get("args", [])]
    base = os.path.basename(cmd)
    if base == "pnpm" and args[:1] == ["dlx"]:
        base, args = "pnpm-dlx", args[1:]
    if base not in LAUNCHERS and base != "pnpm-dlx":
        return
    pkgs = [a for a in args if not a.startswith("-")]
    if not pkgs:
        return
    pkg = pkgs[0]
    line = f"{cmd} {' '.join(args)}"
    if pkg.endswith("@latest"):
        add("error", "MA07", ".mcp", 0, f"MCP 서버 '{name}': `{line}` — @latest는 세션 시작마다 새 코드를 받아 실행한다")
    elif not pinned(pkg):
        fixed = pkg + "@<버전>" if base != "uvx" else pkg + "==<버전>"
        add("warn", "MA07", ".mcp", 0, f"MCP 서버 '{name}': `{line}` — 버전 미고정. 태그로 마켓플레이스를 고정해도 이 패키지는 갱신된다 → `{fixed}`")


EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".d.ts")


def resolve(path):
    """확장자 없는 import(`./lens`, `../types`)를 실제 파일로 푼다. 못 풀면 원래 경로."""
    cands = [path] + [path + e for e in EXTS] + [os.path.join(path, "index" + e) for e in EXTS]
    return next((c for c in cands if os.path.isfile(c)), path)


def scan_module(plugin_dir, rel, seen, report, add):
    path = resolve(os.path.normpath(os.path.join(plugin_dir, rel)))
    shown = os.path.relpath(path, plugin_dir)
    if not inside(plugin_dir, path):
        add("error", "MA08", rel, 0, "모듈 경로가 플러그인 폴더 밖을 가리킨다")
        return
    if path in seen:
        return
    seen.add(path)
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        add("warn", "MA09", shown, 0, "모듈 파일을 읽을 수 없다 (hooks.json의 modules 경로 확인)")
        return
    src = blank_comments(raw)
    has_catch = bool(re.search(r"\.catch\s*\(|\bcatch\s*[({]", src))
    for ln, text in enumerate(src.splitlines(), 1):
        for m in re.finditer(r"""\bon\(\s*['"]([\w.]+)['"]""", text):
            ev = m.group(1)
            report["events"].setdefault(ev, []).append(f"{shown}:{ln}")
            if ev == "tool.check":
                add("warn", "MA05", shown, ln, "tool.check — 도구 호출을 사용자에게 묻기 전에 승인할 수 있다 (내 deny 규칙·PreToolUse 훅을 덮을 수 있다)")
            if ev in GATING and not has_catch:
                add("warn", "MA06", shown, ln, f"{ev} 게이트 훅에 catch가 없다 — 훅이 던지거나 시간 초과하면 건너뛰어져 가드가 열린다 (.catch로 거부 처리)")
        for m in re.finditer(r"\$\.([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)", text):
            call = m.group(1)
            report["calls"].setdefault("$." + call, []).append(f"{shown}:{ln}")
            if call in RISKY_CALLS:
                lvl, code, msg = RISKY_CALLS[call]
                add(lvl, code, shown, ln, f"$.{call} — {msg}")
        if re.search(r"\beval\s*\(|\bnew\s+Function\s*\(", text):
            add("warn", "MA08", shown, ln, "eval/new Function — 실행될 코드를 정적으로 읽을 수 없다")
        for m in re.finditer(r"""\bimport\s*\(\s*([^)]*)\)""", text):
            arg = m.group(1).strip()
            if re.match(r"""['"]https?://""", arg):
                add("error", "MA08", shown, ln, "원격 URL을 동적 import — 받아 실행할 코드를 리뷰할 수 없다")
            elif not re.match(r"""['"][^'"]*['"]$""", arg):
                add("warn", "MA08", shown, ln, "동적 import의 경로가 문자열 상수가 아니다")
        for m in re.finditer(r"""(?:from|import)\s+['"]([^'"]+)['"]""", text):
            spec = m.group(1)
            if spec.startswith("."):
                scan_module(plugin_dir, os.path.join(os.path.dirname(rel), spec), seen, report, add)
            elif re.match(r"https?://", spec):
                add("error", "MA08", shown, ln, "원격 URL import")


def match_allow(call, allow):
    return any(call == a or (a.endswith(".*") and call.startswith(a[:-1])) for a in allow)


def audit_plugin(plugin_dir, allow, baseline):
    manifest = load_json(os.path.join(plugin_dir, ".claude-plugin", "plugin.json")) or {}
    report = {"plugin": manifest.get("name", os.path.basename(plugin_dir)), "version": manifest.get("version", "?"),
              "events": {}, "calls": {}, "findings": []}

    def add(level, code, file, line, msg):
        report["findings"].append({"level": level, "code": code, "file": file, "line": line, "message": msg})

    hooks_path = os.path.join(plugin_dir, "hooks", "hooks.json")
    hooks = load_json(hooks_path)
    modules = hooks.get("modules", []) if isinstance(hooks, dict) else []
    report["is_mod"] = bool(modules)
    seen = set()
    for mod in modules:
        scan_module(plugin_dir, os.path.join("hooks", str(mod)), seen, report, add)
    for name, spec in mcp_servers(plugin_dir, manifest).items():
        audit_mcp(plugin_dir, name, spec, add)

    if {"$.http.fetch"} <= set(report["calls"]) and ({"$.env.get"} | {"$.settings.read"}) & set(report["calls"]):
        f = report["calls"]["$.http.fetch"][0]
        add("error", "MA02", f.split(":")[0], int(f.split(":")[1]), "비밀을 읽는 호출($.env.get/$.settings.read)과 네트워크 전송($.http.fetch)이 한 모드에 같이 있다 — 유출 경로가 된다")
    if allow is not None:
        for call, locs in report["calls"].items():
            if not match_allow(call, allow):
                f, ln = locs[0].rsplit(":", 1)
                add("error", "MA10", f, int(ln), f"{call}는 허용 목록(--allow)에 없다")
    if baseline is not None:
        old_calls, old_events = set(baseline.get("calls", [])), set(baseline.get("events", []))
        for call, locs in report["calls"].items():
            if call not in old_calls:
                f, ln = locs[0].rsplit(":", 1)
                add("error", "MA10", f, int(ln), f"이전 보고서에 없던 호출이 새로 생겼다: {call}")
        for ev, locs in report["events"].items():
            if ev not in old_events:
                f, ln = locs[0].rsplit(":", 1)
                add("error", "MA10", f, int(ln), f"이전 보고서에 없던 훅 이벤트가 새로 생겼다: {ev}")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description="Claude Code 모드(플러그인)를 설치 전에 정적으로 점검한다.")
    ap.add_argument("path", help="플러그인 폴더 또는 플러그인 여러 개가 든 폴더")
    ap.add_argument("--json", action="store_true", help="JSON으로 출력 (--baseline 입력으로 쓸 수 있다)")
    ap.add_argument("--strict", action="store_true", help="warn도 실패로 센다")
    ap.add_argument("--allow", help="허용할 $. 호출 목록, 쉼표 구분 (예: '$.ui.*,$.command.register'). 밖의 호출은 error")
    ap.add_argument("--baseline", help="이전 버전의 --json 보고서. 새로 생긴 호출·훅 이벤트는 error")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.path):
        print(f"mod-audit: 폴더가 아니다: {a.path}", file=sys.stderr)
        return 2
    plugins = find_plugins(a.path)
    if not plugins:
        print(f"mod-audit: {a.path} 아래에 .claude-plugin/plugin.json이 없다", file=sys.stderr)
        return 2
    allow = [x.strip() for x in a.allow.split(",") if x.strip()] if a.allow else None
    baseline = None
    if a.baseline:
        b = load_json(a.baseline)
        if not isinstance(b, dict):
            print(f"mod-audit: 기준 보고서를 읽을 수 없다: {a.baseline}", file=sys.stderr)
            return 2
        plist = b.get("plugins", [])
        baseline = {"calls": [c for p in plist for c in p.get("calls", {})],
                    "events": [e for p in plist for e in p.get("events", {})]}
    reports = [audit_plugin(p, allow, baseline) for p in plugins]
    for r in reports:
        r["findings"].sort(key=lambda f: ({"error": 0, "warn": 1}[f["level"]], f["file"], f["line"]))
    errors = sum(f["level"] == "error" for r in reports for f in r["findings"])
    warns = sum(f["level"] == "warn" for r in reports for f in r["findings"])
    if a.json:
        print(json.dumps({"plugins": reports, "errors": errors, "warns": warns}, ensure_ascii=False, indent=2))
    else:
        for r in reports:
            kind = "모드" if r["is_mod"] else "모드 아님(hooks.json modules 없음)"
            print(f"== {r['plugin']} {r['version']} — {kind}")
            print("  훅 이벤트: " + (", ".join(sorted(r["events"])) or "(없음)"))
            print("  $. 호출:   " + (", ".join(sorted(r["calls"])) or "(없음)"))
            for f in r["findings"]:
                where = f"{f['file']}:{f['line']}" if f["line"] else f["file"]
                print(f"  {where}: {f['level']} {f['code']} {f['message']}")
        print(f"요약: error {errors} · warn {warns} · 플러그인 {len(reports)}개")
    return 1 if errors or (a.strict and warns) else 0


if __name__ == "__main__":
    sys.exit(main())

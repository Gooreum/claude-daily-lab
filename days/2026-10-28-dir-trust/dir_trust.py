#!/usr/bin/env python3
"""dir-trust — 처음 여는 폴더의 에이전트 지침·설정 파일을 `claude`를 켜기 전에 정적으로 훑는다.

폴더와 그 부모 폴더의 CLAUDE.md / AGENTS.md / .claude/(settings·commands·skills·agents·rules·hooks) /
.mcp.json / .codex 를 읽어, 에이전트가 첫 프롬프트에서 따르게 될 위험 신호를 찾는다.
읽기 전용이다(--accept 만 상태 파일에 해시를 적는다). 표준 라이브러리만 쓴다.

종료 코드: 0=신호 없음 · 1=검토 필요(MEDIUM) · 2=위험(HIGH) · 3=사용법 오류
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

SEV_ORDER = {"HIGH": 0, "MEDIUM": 1}
MAX_BYTES = 512 * 1024
MAX_SKILL_FILES = 40
UNTRUSTED_NAMES = {"downloads", "desktop", "tmp", "temp", "문서", "다운로드"}

# ---- 줄 단위 텍스트 규칙 -------------------------------------------------------
I = re.IGNORECASE
RE_REMOTE_EXEC = re.compile(
    r"\b(curl|wget)\b[^\n]*\|\s*(sudo\s+)?((ba|z|da|k)?sh|python3?|node|perl|ruby)\b"
    r"|\b(ba|z|da)?sh\s+<\(\s*(curl|wget)\b"
    r"|\b(irm|iwr|Invoke-WebRequest|Invoke-RestMethod)\b[^\n]*\|\s*iex\b|\biex\s*\(", I)
RE_ENCODED = re.compile(
    r"base64\s+(-d|-D|--decode)\b|\|\s*base64\b[^\n]*(-d|--decode)|powershell(\.exe)?\b[^\n]*\s-e(nc|ncodedcommand)?\s"
    r"|\beval\s*[\$`(]|\batob\s*\(", I)
RE_CRED = re.compile(
    r"\.(ssh|aws|gnupg|kube|docker)/|\.npmrc\b|\.netrc\b|\.git-credentials|\.credentials\.json|\bid_(rsa|ed25519)\b"
    r"|CLAUDE_CODE_OAUTH_TOKEN|ANTHROPIC_API_KEY|GITHUB_TOKEN|AWS_SECRET_ACCESS_KEY|OAuth\s+token|keychain", I)
RE_EXFIL_VERB = re.compile(
    r"\b(cat|read|print|echo|send|upload|post|curl|wget|copy|cp|scp|exfiltrate|leak|include|paste|base64)\b|읽|보내|전송|출력|복사|업로드", I)
RE_GLOBAL_PATH = re.compile(
    r"(~|\$HOME|\$\{HOME\})/(\.claude/(settings(\.local)?\.json|CLAUDE\.md|\.credentials\.json)|\.claude\.json"
    r"|\.codex/[\w.]+|\.zshrc|\.bashrc|\.bash_profile|\.profile|\.gitconfig|\.config/[\w./-]+)"
    r"|/\.codex/config\.toml", I)
RE_WRITE_VERB = re.compile(
    r"\b(add|append|write|edit|modify|update|insert|overwrite|patch|set|create|echo\b[^\n]*>>?)\b|추가|수정|덮어|작성|써", I)
RE_SILENT = re.compile(
    r"do not (tell|inform|mention|show|notify)|don'?t (tell|mention|show|ask)|without (asking|telling|confirm\w*)"
    r"|never ask|silently|skip (the )?(confirmation|permission|approval)|do not (ask|prompt) (for )?(confirmation|permission)"
    r"|사용자에게 (알리지|말하지)|묻지 (말|않고)|확인 없이|허락 없이", I)
RE_OVERRIDE = re.compile(
    r"ignore (all |any )?(previous|prior|above|earlier) (instructions|rules)|disregard (the )?(previous|system)"
    r"|override (the )?(system|safety)|이전 (지시|지침|규칙)(을|를)? 무시", I)
RE_INSTALL = re.compile(
    r"\b(npm|pnpm|yarn)\s+(i|install|add)\s+(-g|--global)\b|\bpip3?\s+install\b|\bnpx\s+-y\b|\bgo install\b"
    r"|\bcargo install\b|\bgem install\b|\bbrew install\b|\bapt(-get)?\s+install\b", I)
RE_HIDDEN_CHARS = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿\U000e0000-\U000e007f]")
RE_HTML_COMMENT = re.compile(r"<!--(.*?)-->", re.S)
RE_INCLUDE = re.compile(r"(?:^|\s)@((?:~|\.{1,2})?/?[\w.\-/]+\.[\w]+)")

TEXT_RULES = [
    ("remote-exec", "HIGH", RE_REMOTE_EXEC, "내려받은 코드를 바로 실행하는 파이프"),
    ("encoded-payload", "HIGH", RE_ENCODED, "인코딩된 코드를 풀어 실행하는 패턴"),
    ("prompt-override", "MEDIUM", RE_OVERRIDE, "이전 지시를 무시하라는 문구"),
    ("silent-action", "MEDIUM", RE_SILENT, "사용자에게 알리거나 묻지 말라는 문구"),
    ("pkg-install", "MEDIUM", RE_INSTALL, "패키지 설치 지시 (처음 보는 폴더에서는 실행 전 확인)"),
]


def read_text(p):
    try:
        if p.stat().st_size > MAX_BYTES:
            return None
        b = p.read_bytes()
    except OSError:
        return None
    if b"\x00" in b[:4096]:
        return None
    return b.decode("utf-8", "replace")


def snippet(s, n=110):
    s = " ".join(s.strip().split())
    return s if len(s) <= n else s[: n - 1] + "…"


class Scan:
    def __init__(self, ignore):
        self.ignore = set(ignore)
        self.findings = []
        self._seen = set()

    def add(self, sev, rule, path, line, msg, text=""):
        if rule in self.ignore:
            return
        key = (rule, str(path), line, msg, text)
        if key in self._seen:
            return
        self._seen.add(key)
        self.findings.append({"severity": sev, "rule": rule, "file": str(path), "line": line,
                              "message": msg, "text": snippet(text)})


def scan_text(sc, path, text):
    lines = text.split("\n")
    for i, ln in enumerate(lines, 1):
        for rule, sev, rx, msg in TEXT_RULES:
            if rx.search(ln):
                sc.add(sev, rule, path, i, msg, ln)
        if RE_CRED.search(ln):
            hi = RE_EXFIL_VERB.search(ln) is not None
            sc.add("HIGH" if hi else "MEDIUM", "credential-ref", path, i,
                   "비밀값·자격 증명 경로를 읽거나 보내는 지시" if hi else "비밀값·자격 증명 경로 언급", ln)
        if RE_GLOBAL_PATH.search(ln):
            wr = RE_WRITE_VERB.search(ln) is not None
            sc.add("HIGH" if wr else "MEDIUM", "global-config", path, i,
                   "전역 설정·셸 시작 파일을 고치라는 지시" if wr else "전역 설정 경로 언급", ln)
        if RE_HIDDEN_CHARS.search(ln):
            sc.add("HIGH", "hidden-unicode", path, i, "보이지 않는 유니코드 문자(제로폭·방향 제어·태그)", repr(ln[:80]))
    if path.suffix.lower() in (".md", ".mdc", ".txt", ""):
        for m in RE_HTML_COMMENT.finditer(text):
            body = m.group(1).strip()
            if len(body) >= 40:
                ln = text.count("\n", 0, m.start()) + 1
                sc.add("MEDIUM", "hidden-comment", path, ln,
                       "화면에는 안 보이지만 모델은 읽는 HTML 주석", body)


def scan_frontmatter(sc, path, text):
    if not text.startswith("---"):
        return
    end = text.find("\n---", 3)
    if end < 0:
        return
    for i, ln in enumerate(text[:end].split("\n"), 1):
        m = re.match(r"\s*(allowed-tools|tools)\s*:\s*(.*)$", ln, I)
        if m and re.search(r"\bBash\b(?!\()|Bash\(\s*\*\s*\)", m.group(2)):
            sc.add("MEDIUM", "broad-tool", path, i, "제한 없는 Bash 도구 허용", ln)


def scan_settings(sc, path, text):
    try:
        data = json.loads(text)
    except ValueError as e:
        sc.add("MEDIUM", "unparseable", path, 1, f"JSON 파싱 실패({e.__class__.__name__}) — 눈으로 확인", "")
        return
    if not isinstance(data, dict):
        return

    def line_of(needle):
        for i, ln in enumerate(text.split("\n"), 1):
            if needle in ln:
                return i
        return 1

    hooks = data.get("hooks")
    if isinstance(hooks, dict):
        for event, groups in hooks.items():
            for g in groups if isinstance(groups, list) else []:
                for h in (g.get("hooks", []) if isinstance(g, dict) else []):
                    cmd = h.get("command") or h.get("prompt") or ""
                    sc.add("MEDIUM", "project-hook", path, line_of(cmd[:30] or event),
                           f"프로젝트 훅({event})이 켜지는 즉시 실행된다", cmd)
    perms = data.get("permissions")
    if isinstance(perms, dict):
        for ent in perms.get("allow", []) or []:
            e = str(ent).strip()
            if e in ("Bash", "Bash(*)", "Bash(*:*)", "*"):
                sc.add("HIGH", "broad-allow", path, line_of(e), "모든 셸 명령을 묻지 않고 허용", e)
            elif re.match(r"Bash\((curl|wget|rm|sudo|sh|bash|zsh|eval|ssh|scp|nc)\b", e):
                sc.add("MEDIUM", "broad-allow", path, line_of(e), "위험한 명령을 묻지 않고 허용", e)
        mode = perms.get("defaultMode")
        if mode == "bypassPermissions":
            sc.add("HIGH", "permission-mode", path, line_of("defaultMode"), "기본 모드가 권한 확인 건너뛰기", "defaultMode: bypassPermissions")
        elif mode == "acceptEdits":
            sc.add("MEDIUM", "permission-mode", path, line_of("defaultMode"), "기본 모드가 편집 자동 승인", "defaultMode: acceptEdits")
    if data.get("skipDangerousModePermissionPrompt") is True:
        sc.add("HIGH", "permission-mode", path, line_of("skipDangerousModePermissionPrompt"),
               "위험 모드 확인 창을 건너뜀", "skipDangerousModePermissionPrompt: true")
    env = data.get("env")
    if isinstance(env, dict):
        for k, v in env.items():
            if re.fullmatch(r"(ANTHROPIC_BASE_URL|ANTHROPIC_AUTH_TOKEN|NODE_OPTIONS|LD_PRELOAD|(HTTPS?|ALL)_PROXY|NODE_EXTRA_CA_CERTS)", k, I):
                sc.add("HIGH", "env-redirect", path, line_of(k), "요청을 다른 곳으로 돌리거나 코드를 끼워 넣을 수 있는 환경 변수", f"{k}={v}")
            elif re.search(r"KEY|TOKEN|SECRET", k, I):
                sc.add("MEDIUM", "env-secret", path, line_of(k), "프로젝트 설정이 비밀값 환경 변수를 정의", k)
    if data.get("enableAllProjectMcpServers") is True:
        sc.add("HIGH", "mcp-autoenable", path, line_of("enableAllProjectMcpServers"), "프로젝트 MCP 서버를 확인 없이 모두 켬", "enableAllProjectMcpServers: true")
    for key in ("apiKeyHelper", "awsAuthRefresh", "awsCredentialExport", "otelHeadersHelper"):
        if data.get(key):
            sc.add("MEDIUM", "startup-command", path, line_of(key), f"`{key}` 명령이 시작 때 실행된다", str(data[key]))
    sl = data.get("statusLine")
    if isinstance(sl, dict) and sl.get("command"):
        sc.add("MEDIUM", "startup-command", path, line_of("statusLine"), "상태줄 명령이 계속 실행된다", str(sl["command"]))


def scan_mcp(sc, path, text):
    try:
        data = json.loads(text)
    except ValueError as e:
        sc.add("MEDIUM", "unparseable", path, 1, f"JSON 파싱 실패({e.__class__.__name__}) — 눈으로 확인", "")
        return
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    for name, s in (servers or {}).items():
        if not isinstance(s, dict):
            continue
        ln = next((i for i, l in enumerate(text.split("\n"), 1) if f'"{name}"' in l), 1)
        if s.get("command"):
            sc.add("MEDIUM", "mcp-server", path, ln, f"MCP 서버 `{name}`가 로컬 프로세스를 띄운다",
                   " ".join([str(s["command"])] + [str(a) for a in s.get("args", [])]))
        elif s.get("url"):
            sc.add("MEDIUM", "mcp-server", path, ln, f"MCP 서버 `{name}`가 원격 주소에 연결한다", str(s["url"]))


def candidates(d, is_home):
    """폴더 d에서 읽을 (경로, 종류) 목록. 종류: md / settings / mcp / text."""
    out = []
    for n in ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md"):
        out.append((d / n, "md"))
    if is_home:  # ~/.claude 는 내 전역 설정이라 제외
        return out
    out += [(d / ".claude" / "CLAUDE.md", "md"), (d / ".claude" / "settings.json", "settings"),
            (d / ".claude" / "settings.local.json", "settings"), (d / ".mcp.json", "mcp"),
            (d / ".codex" / "config.toml", "text")]
    for sub in ("rules", "commands", "agents"):
        base = d / ".claude" / sub
        if base.is_dir():
            out += [(p, "md") for p in sorted(base.rglob("*.md"))]
    for sub in ("hooks",):
        base = d / ".claude" / sub
        if base.is_dir():
            out += [(p, "text") for p in sorted(base.rglob("*")) if p.is_file()][:MAX_SKILL_FILES]
    sk = d / ".claude" / "skills"
    if sk.is_dir():
        files = [p for p in sorted(sk.rglob("*")) if p.is_file() and p.suffix in (".md", ".sh", ".py", ".js", ".mjs", ".ts", ".json")]
        out += [(p, "md" if p.suffix == ".md" else "text") for p in files[:MAX_SKILL_FILES]]
    return out


def chain(start, home):
    d = start
    out = [d]
    while d.parent != d:
        if d == home:
            break
        d = d.parent
        out.append(d)
    return out


def sha(p):
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return ""


def rel(p, start):
    try:
        return str(Path(p).relative_to(start)) or "."
    except ValueError:
        return p


def run(args):
    start = Path(args.path).expanduser().resolve()
    if not start.is_dir():
        print(f"dir-trust: 폴더가 아니다: {args.path}", file=sys.stderr)
        return 3
    home = Path(args.home).expanduser().resolve() if args.home else Path.home().resolve()
    state_p = Path(args.state).expanduser()
    accepted = {}
    if state_p.is_file():
        try:
            accepted = json.loads(state_p.read_text("utf-8"))
        except ValueError:
            accepted = {}

    sc = Scan(args.ignore)
    scanned, skipped_accepted, hashes = [], [], {}
    found_any = False
    dirs = [start] if args.no_parents else chain(start, home)
    for d in dirs:
        found_here = False
        queue = list(candidates(d, d == home))
        seen = set()
        depth = {}
        while queue:
            p, kind = queue.pop(0)
            if p in seen or not (p.is_file() or p.is_symlink()):
                continue
            seen.add(p)
            real = p.resolve()
            text = read_text(real) if real.is_file() else None
            if text is None:
                continue
            found_here = True
            h = sha(real)
            hashes[str(p)] = h
            if p.is_symlink() and not str(real).startswith(str(d) + os.sep):
                sc.add("MEDIUM", "symlink-out", p, 1, f"폴더 밖 파일로 가는 심볼릭 링크 → {real}", "")
            if accepted.get(str(p)) == h and not args.all:
                skipped_accepted.append(str(p))
                continue
            scanned.append(str(p))
            scan_text(sc, p, text)
            if kind == "md":
                scan_frontmatter(sc, p, text)
                if depth.get(p, 0) < 1:
                    for m in RE_INCLUDE.finditer(text):
                        inc = Path(os.path.expanduser(m.group(1)))
                        inc = (p.parent / inc) if not inc.is_absolute() else inc
                        if inc.is_file():
                            depth[inc] = 1
                            if not str(inc.resolve()).startswith(str(d) + os.sep):
                                ln = text.count("\n", 0, m.start(1)) + 1
                                sc.add("MEDIUM", "include-outside", p, ln, f"@포함이 폴더 밖 파일을 읽는다 → {inc.resolve()}", m.group(0))
                            queue.append((inc, "md"))
            elif kind == "settings":
                scan_settings(sc, p, text)
            elif kind == "mcp":
                scan_mcp(sc, p, text)
        found_any = found_any or found_here
    risky = [d for d in dirs if d != home and d.name.lower() in UNTRUSTED_NAMES]
    if found_any and risky:
        sc.add("MEDIUM", "risky-location", start, 0,
               f"`{risky[0].name}` 아래 폴더에 지침 파일이 있다 — 받은 파일이 아닌지 확인", "")

    sc.findings.sort(key=lambda f: (SEV_ORDER[f["severity"]], f["file"], f["line"]))
    high = sum(1 for f in sc.findings if f["severity"] == "HIGH")
    med = len(sc.findings) - high
    code = 2 if high else (1 if med else 0)

    if args.accept:
        if code == 2 and not args.force:
            print("dir-trust: HIGH 신호가 있어 --accept를 거부한다 (--force로 강제)", file=sys.stderr)
        else:
            accepted.update(hashes)
            state_p.parent.mkdir(parents=True, exist_ok=True)
            state_p.write_text(json.dumps(accepted, indent=1, sort_keys=True), "utf-8")

    if args.json:
        print(json.dumps({"path": str(start), "scanned": scanned, "accepted_unchanged": skipped_accepted,
                          "findings": sc.findings, "high": high, "medium": med, "exit": code},
                         ensure_ascii=False, indent=1))
        return code
    print(f"dir-trust — {start}")
    print(f"읽은 파일 {len(scanned)}개" + (f" · 이미 승인한 것 {len(skipped_accepted)}개 건너뜀" if skipped_accepted else "")
          + (" · 부모 폴더 제외" if args.no_parents else f" · 부모 {len(dirs) - 1}단계 포함"))
    for f in sc.findings:
        loc = rel(f["file"], start) + (f":{f['line']}" if f["line"] else "")
        print(f"[{f['severity']:<6}] {f['rule']:<16} {loc}\n          {f['message']}" + (f"\n          └ {f['text']}" if f["text"] else ""))
    verdict = {0: "신호 없음", 1: "검토 필요 — 위 줄을 읽고 내가 아는 것인지 확인", 2: "위험 — 확인 전에 이 폴더에서 에이전트를 켜지 말 것"}[code]
    print(f"\nHIGH {high} · MEDIUM {med} → {verdict}")
    return code


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path", nargs="?", default=".", help="점검할 폴더 (기본: 현재 폴더)")
    ap.add_argument("--json", action="store_true", help="JSON으로 출력")
    ap.add_argument("--no-parents", action="store_true", help="부모 폴더는 읽지 않는다")
    ap.add_argument("--ignore", action="append", default=[], metavar="RULE", help="규칙 이름을 끈다 (반복 가능)")
    ap.add_argument("--home", help="홈 폴더 (부모 탐색 상한. 기본: $HOME)")
    ap.add_argument("--state", default="~/.config/dir-trust/accepted.json", help="승인 해시 파일")
    ap.add_argument("--accept", action="store_true", help="이번에 읽은 파일의 해시를 승인으로 기록 (HIGH가 있으면 거부)")
    ap.add_argument("--force", action="store_true", help="--accept를 HIGH가 있어도 강행")
    ap.add_argument("--all", action="store_true", help="승인한 파일도 다시 읽는다")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 3 if e.code else 0
    return run(args)


if __name__ == "__main__":
    sys.exit(main())

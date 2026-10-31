#!/usr/bin/env python3
"""ext_sweep.py — 에디터 확장 공급망 사고 뒤 "내 PC에 흔적이 남았나"를 읽기 전용으로 훑는다.

보는 곳(HOME 아래만, 아무것도 고치거나 지우거나 실행하지 않는다):
  1. 에디터 확장 폴더(VS Code·Cursor·Windsurf·VSCodium·vscode-server)의 Claude Code 확장 버전,
     그리고 그 확장 파일 안의 백도어 문자열(authorized_keys·역방향 터널·LaunchAgents·schtasks·포트)
  2. ~/.ssh/authorized_keys 의 최근 수정과 (목록을 주면) 모르는 키
  3. 자동 실행 위치: macOS LaunchAgents, Linux systemd 사용자 유닛·autostart, Windows 시작 프로그램

종료 코드: 0=신호 없음, 1=MEDIUM만, 2=HIGH 있음, 64=사용법 오류.
기본 지표(버전 2.1.312·2.1.313, 포트 8099)는 GeekNews가 전한 Cursor 공지 내용이며 독립 검증되지 않았다.
버전과 포트는 인자로 바꾼다. 표준 라이브러리만 쓴다.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time

DEFAULT_BAD_VERSIONS = ["2.1.312", "2.1.313"]
DEFAULT_EXT_ID = "anthropic.claude-code"
DEFAULT_PORT = "8099"

# HOME 아래 확장 폴더 후보. 에디터마다 점 폴더 이름이 다르다.
EXT_ROOTS = [
    ".vscode/extensions", ".vscode-insiders/extensions", ".vscode-oss/extensions",
    ".vscode-server/extensions", ".cursor/extensions", ".windsurf/extensions",
    ".vscodium/extensions", ".antigravity/extensions",
]
PERSIST_DIRS = [
    ("launchagent", "Library/LaunchAgents", (".plist",)),
    ("systemd-user", ".config/systemd/user", (".service", ".timer", ".path")),
    ("autostart", ".config/autostart", (".desktop",)),
    ("startup-folder", "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup", None),
]

MAX_FILES_PER_EXT = 4000
MAX_FILE_BYTES = 3 * 1024 * 1024
SCAN_SUFFIXES = (".js", ".cjs", ".mjs", ".json", ".sh", ".ps1", ".bat", ".cmd", ".py", ".vbs", ".plist", ".node.js")

LEVEL_ORDER = {"HIGH": 2, "MEDIUM": 1, "INFO": 0}


class Finding:
    def __init__(self, level, rule, path, detail):
        self.level, self.rule, self.path, self.detail = level, rule, path, detail

    def as_dict(self):
        return {"level": self.level, "rule": self.rule, "path": self.path, "detail": self.detail}


def rel(path, home):
    try:
        r = os.path.relpath(path, home)
        return "~/" + r.replace(os.sep, "/") if not r.startswith("..") else path
    except ValueError:
        return path


def parse_ext_dirname(name, ext_id):
    """`anthropic.claude-code-2.1.312-darwin-arm64` → ('2.1.312', 'darwin-arm64'). 다른 확장이면 None."""
    low = name.lower()
    prefix = ext_id.lower() + "-"
    if not low.startswith(prefix):
        return None
    m = re.match(r"^(\d+\.\d+\.\d+(?:[-+.][0-9A-Za-z.]+?)?)(?:-((?:darwin|linux|win32|alpine|web)[-0-9A-Za-z]*))?$", low[len(prefix):])
    if m:
        return m.group(1), m.group(2) or ""
    return None


def body_patterns(port):
    p = re.escape(port)
    return [
        ("HIGH", "ext-authkeys-string", re.compile(r"authorized_keys"), "authorized_keys를 건드리는 문자열"),
        ("HIGH", "ext-reverse-tunnel", re.compile(r"ssh[^\n]{0,80}\s-R\s*\d+:|\s-R\s*\d{2,5}:[\w.\-]+:\d+"), "ssh 역방향 터널(-R) 문자열"),
        ("MEDIUM", "ext-persistence-string", re.compile(r"LaunchAgents|schtasks|Start Menu[\\/]+Programs[\\/]+Startup|systemctl[^\n]{0,20}--user\s+enable"), "자동 실행 등록 문자열"),
        ("MEDIUM", "ext-port-string", re.compile(r"(?<![\d.])(?:[\w.\-]+):%s(?!\d)|[\"']%s[\"']" % (p, p)), "지표 포트 %s로 보내는 듯한 문자열" % port),
    ]


def scan_extension_files(ext_dir, home, patterns, findings):
    """확장 폴더 안 파일을 읽기만 한다. 심볼릭 링크는 따라가지 않는다."""
    seen = 0
    hit_rules = set()
    for root, dirs, files in os.walk(ext_dir, followlinks=False):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
        for fn in files:
            if seen >= MAX_FILES_PER_EXT:
                findings.append(Finding("INFO", "ext-scan-truncated", rel(ext_dir, home),
                                        "파일이 %d개를 넘어 일부만 읽었다" % MAX_FILES_PER_EXT))
                return
            fp = os.path.join(root, fn)
            if os.path.islink(fp) or not fn.lower().endswith(SCAN_SUFFIXES):
                continue
            try:
                if os.path.getsize(fp) > MAX_FILE_BYTES:
                    continue
                with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            seen += 1
            for level, rule, rx, label in patterns:
                if rule in hit_rules:
                    continue
                m = rx.search(text)
                if m:
                    hit_rules.add(rule)
                    line_no = text.count("\n", 0, m.start()) + 1
                    findings.append(Finding(level, rule, rel(fp, home), "%s (줄 %d)" % (label, line_no)))


def check_extensions(home, ext_id, bad_versions, port, findings):
    found_any = False
    patterns = body_patterns(port)
    for root_rel in EXT_ROOTS:
        root = os.path.join(home, *root_rel.split("/"))
        if not os.path.isdir(root):
            continue
        try:
            names = sorted(os.listdir(root))
        except OSError as e:
            findings.append(Finding("INFO", "ext-unreadable", rel(root, home), str(e)))
            continue
        for name in names:
            path = os.path.join(root, name)
            if os.path.islink(path) or not os.path.isdir(path):
                continue
            parsed = parse_ext_dirname(name, ext_id)
            if not parsed:
                continue
            found_any = True
            version, plat = parsed
            label = "버전 %s%s" % (version, " (%s)" % plat if plat else "")
            if version in bad_versions:
                findings.append(Finding("HIGH", "ext-bad-version", rel(path, home),
                                        "%s — 보도된 영향 버전. 폴더만 지우면 남은 백도어는 그대로다" % label))
            else:
                findings.append(Finding("INFO", "ext-installed", rel(path, home), label))
            # 정상 버전 번호를 재사용한 변조본이 있다고 하므로 버전만 믿지 않고 package.json과 내용도 본다
            pj = os.path.join(path, "extension", "package.json")
            if not os.path.isfile(pj):
                pj = os.path.join(path, "package.json")
            if os.path.isfile(pj):
                try:
                    with open(pj, "r", encoding="utf-8") as fh:
                        meta = json.load(fh)
                    pv = str(meta.get("version", ""))
                    if pv and pv.lower() != version:
                        findings.append(Finding("MEDIUM", "ext-version-mismatch", rel(pj, home),
                                                "폴더 이름은 %s인데 package.json은 %s" % (version, pv)))
                    if pv in bad_versions and version not in bad_versions:
                        findings.append(Finding("HIGH", "ext-bad-version", rel(pj, home),
                                                "package.json 버전 %s — 보도된 영향 버전" % pv))
                except (OSError, ValueError):
                    findings.append(Finding("MEDIUM", "ext-manifest-unreadable", rel(pj, home), "package.json을 읽지 못했다"))
            else:
                findings.append(Finding("MEDIUM", "ext-manifest-missing", rel(path, home), "package.json이 없다"))
            scan_extension_files(path, home, patterns, findings)
    return found_any


def fingerprint(blob_b64):
    try:
        raw = base64.b64decode(blob_b64, validate=True)
    except (ValueError, base64.binascii.Error):
        return None
    return "SHA256:" + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")


KEY_RX = re.compile(r"(?:^|\s)((?:ssh-(?:rsa|ed25519|dss)|ecdsa-sha2-\S+|sk-\S+))\s+([A-Za-z0-9+/=]+)(?:\s+(.*))?$")


def parse_key_line(line):
    m = KEY_RX.search(line.strip())
    if not m:
        return None
    fp = fingerprint(m.group(2))
    return {"type": m.group(1), "fp": fp, "comment": (m.group(3) or "").strip(), "blob": m.group(2),
            "options": line.strip()[:m.start(1)].strip()}


def load_known(path):
    known = set()
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            s = raw.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("SHA256:"):
                known.add(s.split()[0])
                continue
            k = parse_key_line(s)
            if k and k["fp"]:
                known.add(k["fp"])
    return known


def check_authorized_keys(home, since_days, now, known, findings):
    for name in ("authorized_keys", "authorized_keys2"):
        path = os.path.join(home, ".ssh", name)
        if os.path.islink(path) or not os.path.isfile(path):
            continue
        try:
            st = os.stat(path)
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
        except OSError as e:
            findings.append(Finding("INFO", "authkeys-unreadable", rel(path, home), str(e)))
            continue
        keys = [k for k in (parse_key_line(l) for l in lines if l.strip() and not l.lstrip().startswith("#")) if k]
        age_days = (now - st.st_mtime) / 86400
        findings.append(Finding("INFO", "authkeys-summary", rel(path, home),
                                "키 %d개, 마지막 수정 %.1f일 전" % (len(keys), max(age_days, 0))))
        if age_days <= since_days and keys:
            findings.append(Finding("MEDIUM", "authkeys-recent", rel(path, home),
                                    "최근 %d일 안에 수정됨 — 직접 추가한 게 아니면 확인" % since_days))
        for k in keys:
            fp = k["fp"] or "(지문 계산 실패)"
            tag = "%s %s %s" % (k["type"], fp, k["comment"] or "(주석 없음)")
            if known is not None and k["fp"] not in known:
                findings.append(Finding("HIGH", "authkeys-unknown", rel(path, home), "목록에 없는 키: " + tag))
            elif known is None and not k["comment"]:
                findings.append(Finding("MEDIUM", "authkeys-no-comment", rel(path, home),
                                        "주석 없는 키(직접 넣었다면 보통 주석이 있다): %s %s" % (k["type"], fp)))
            if k["options"] and re.search(r"command=|permitopen=|no-pty", k["options"]):
                findings.append(Finding("MEDIUM", "authkeys-options", rel(path, home),
                                        "옵션이 붙은 키: %s … %s" % (k["options"][:60], fp)))


PERSIST_BAD = re.compile(r"\bssh\b[^\n]{0,120}(?:-R\b|-N\b)|authorized_keys|curl[^\n]{0,80}\|\s*(?:ba)?sh|nc\s+-[a-z]*e\b")


def check_persistence(home, since_days, now, port, findings):
    port_rx = re.compile(r"(?<![\d.])%s(?!\d)" % re.escape(port))
    for label, rel_dir, suffixes in PERSIST_DIRS:
        d = os.path.join(home, *rel_dir.split("/"))
        if not os.path.isdir(d):
            continue
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for name in names:
            p = os.path.join(d, name)
            if os.path.islink(p) or not os.path.isfile(p):
                continue
            if suffixes and not name.lower().endswith(suffixes):
                continue
            try:
                age = (now - os.stat(p).st_mtime) / 86400
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read(200000)
            except OSError:
                continue
            bad = PERSIST_BAD.search(text)
            if bad:
                findings.append(Finding("HIGH", label + "-ssh", rel(p, home),
                                        "내용에 ssh 터널·authorized_keys·원격 실행 패턴: %s" % bad.group(0)[:60]))
            elif port_rx.search(text):
                findings.append(Finding("MEDIUM", label + "-port", rel(p, home), "지표 포트 %s가 들어 있다" % port))
            if age <= since_days:
                findings.append(Finding("MEDIUM", label + "-recent", rel(p, home),
                                        "최근 %d일 안에 만들어지거나 수정됨 (%.1f일 전)" % (since_days, max(age, 0))))


NEXT_STEPS = [
    "네트워크를 끊고(와이파이·랜) 에디터를 종료한다.",
    "확장 폴더만 지우지 말고, 위에 나온 authorized_keys 줄·LaunchAgent·시작 프로그램·예약 작업을 직접 확인해 제거한다.",
    "이 PC에서 접근 가능했던 SSH 개인 키, 저장소·클라우드 토큰, API 키를 다른 기기에서 새로 발급하고 옛것을 폐기한다.",
    "공식 공지(Cursor·Anthropic)의 침해 지표와 복구 스크립트를 기준으로 다시 점검한다. 이 도구의 지표는 보도 기반 참고용이다.",
]


def sweep(args):
    home = os.path.abspath(os.path.expanduser(args.home))
    if not os.path.isdir(home):
        print("HOME이 폴더가 아니다: %s" % home, file=sys.stderr)
        return 64, [], False
    now = time.time()
    known = None
    if args.known_keys:
        try:
            known = load_known(args.known_keys)
        except OSError as e:
            print("known-keys를 읽지 못했다: %s" % e, file=sys.stderr)
            return 64, [], False
    findings = []
    found = check_extensions(home, args.ext_id, args.bad_version or DEFAULT_BAD_VERSIONS, args.port, findings)
    check_authorized_keys(home, args.since, now, known, findings)
    check_persistence(home, args.since, now, args.port, findings)
    worst = max([LEVEL_ORDER[f.level] for f in findings] or [0])
    code = 2 if worst == 2 else (1 if worst == 1 else 0)
    return code, findings, found


def render(findings, code, found_ext, args):
    out = []
    out.append("# ext-sweep — %s" % time.strftime("%Y-%m-%d %H:%M", time.localtime()))
    out.append("대상 HOME: %s · 확장 ID: %s · 영향 버전: %s · 포트: %s · 최근 기준: %d일" % (
        os.path.abspath(os.path.expanduser(args.home)), args.ext_id,
        ", ".join(args.bad_version or DEFAULT_BAD_VERSIONS), args.port, args.since))
    out.append("※ 기본 지표는 GeekNews가 전한 Cursor 공지 내용으로 독립 검증되지 않았다. 읽기 전용이며 아무것도 바꾸지 않는다.")
    out.append("")
    shown = [f for f in findings if f.level != "INFO" or args.verbose]
    for lvl in ("HIGH", "MEDIUM", "INFO"):
        for f in shown:
            if f.level == lvl:
                out.append("[%-6s] %-22s %s\n           %s" % (f.level, f.rule, f.path, f.detail))
    if not shown:
        out.append("신호 없음.")
    if not found_ext:
        out.append("(Claude Code 확장 폴더를 찾지 못했다 — 이 HOME에는 해당 에디터 확장이 없거나 다른 위치에 있다.)")
    counts = {l: sum(1 for f in findings if f.level == l) for l in LEVEL_ORDER}
    out.append("")
    out.append("요약: HIGH %d · MEDIUM %d · INFO %d → 종료 코드 %d" % (counts["HIGH"], counts["MEDIUM"], counts["INFO"], code))
    if code == 2:
        out.append("")
        out.append("HIGH가 있다. 다음 순서로 대응한다:")
        for i, s in enumerate(NEXT_STEPS, 1):
            out.append("  %d. %s" % (i, s))
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="에디터 확장 공급망 사고 뒤 로컬 흔적을 읽기 전용으로 점검한다.")
    ap.add_argument("--home", default="~", help="점검할 HOME (기본 ~, 테스트용으로 바꿀 수 있음)")
    ap.add_argument("--ext-id", default=DEFAULT_EXT_ID, help="확장 ID (기본 %s)" % DEFAULT_EXT_ID)
    ap.add_argument("--bad-version", action="append", help="영향 버전(여러 번 가능, 기본 %s)" % ", ".join(DEFAULT_BAD_VERSIONS))
    ap.add_argument("--port", default=DEFAULT_PORT, help="지표 포트 (기본 %s)" % DEFAULT_PORT)
    ap.add_argument("--since", type=int, default=14, help="'최근'으로 볼 일수 (기본 14)")
    ap.add_argument("--known-keys", help="내가 아는 SSH 공개 키(줄) 또는 SHA256 지문 목록 파일. 주면 목록에 없는 키를 HIGH로 본다")
    ap.add_argument("--json", action="store_true", help="JSON으로 출력")
    ap.add_argument("-v", "--verbose", action="store_true", help="INFO(설치된 버전, 키 수)도 출력")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 64 if e.code else 0
    if args.since < 0:
        print("--since는 0 이상이어야 한다", file=sys.stderr)
        return 64
    code, findings, found = sweep(args)
    if code == 64:
        return 64
    if args.json:
        print(json.dumps({"exit": code, "extension_found": found, "findings": [f.as_dict() for f in findings]},
                         ensure_ascii=False, indent=2))
    else:
        print(render(findings, code, found, args))
    return code


if __name__ == "__main__":
    sys.exit(main())

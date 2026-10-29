#!/usr/bin/env python3
"""sandbox-lint — Claude Code 샌드박스 설정(settings.json)의 구멍을 정적으로 찾는다.

읽는 파일: <프로젝트>/.claude/settings.json · settings.local.json, <홈>/.claude/settings.json,
          (있으면) 관리형 managed-settings.json. 모델도 네트워크도 쓰지 않는다. 표준 라이브러리만.

프로필: unattended(기본, 밤새 무인으로 도는 작업 기준) · interactive(사람이 앞에 있을 때).
종료 코드: 0=문제 없음(INFO만) · 1=검토 필요(MEDIUM) · 2=위험(HIGH) · 3=사용법 오류
"""
import argparse
import json
import re
import sys
from pathlib import Path

# 우선순위가 높은 설정부터 (관리형 > 로컬 > 프로젝트 > 사용자)
PRECEDENCE = ["managed", "local", "project", "user"]
USER_ONLY = ("user", "managed")          # 프로젝트 설정에서는 무시되는 키의 유효 범위
SEV_RANK = {"HIGH": 2, "MEDIUM": 1, "INFO": 0}

# sandbox 아래에서 사용자·관리형·--settings에서만 효력이 있는 키 (code.claude.com/docs/en/sandboxing)
USER_ONLY_KEYS = [
    "network.strictAllowlist", "filesystem.disabled", "network.tlsTerminate",
    "credentials.allowPlaintextInject", "allowAppleEvents", "allowNestedUserNamespaces",
    "credentials.awsPairs", "credentials.sigv4",
]
MANAGED_ONLY_KEYS = ["network.allowManagedDomainsOnly", "allowManagedReadPathsOnly"]

CRED_DIRS = ["~/.ssh", "~/.aws", "~/.gnupg", "~/.kube", "~/.config/gh", "~/.netrc", "~/.npmrc"]
STARTUP_PATHS = ["~/.bashrc", "~/.zshrc", "~/.profile", "~/.bash_profile", "~/.gitconfig", "~/.claude", "~/.config"]
BROAD_WRITE = {"/", "~", "/home", "/Users", "/etc", "/usr", "/var", "/root"}
INTERPRETERS = {"bash", "sh", "zsh", "dash", "fish", "python", "python3", "node", "npx", "env", "sudo",
                "ruby", "perl", "pwsh", "powershell", "xargs", "eval", "exec"}
SHARED_HOST_SUFFIXES = ["github.io", "githubusercontent.com", "amazonaws.com", "cloudfront.net", "herokuapp.com",
                        "vercel.app", "netlify.app", "pages.dev", "workers.dev", "ngrok.io", "ngrok-free.app",
                        "trycloudflare.com", "firebaseapp.com", "web.app", "azurewebsites.net", "appspot.com"]

# (id, 프로필별 심각도, 설명) — 심각도가 None이면 그 프로필에서는 보지 않는다
RULES = {
    "sandbox-off":         {"unattended": "HIGH",   "interactive": "MEDIUM"},
    "fail-open":           {"unattended": "HIGH",   "interactive": None},
    "unsandboxed-retry":   {"unattended": "HIGH",   "interactive": "MEDIUM"},
    "no-strict-allowlist": {"unattended": "MEDIUM", "interactive": None},
    "cred-not-denied":     {"unattended": "MEDIUM", "interactive": "MEDIUM"},
    "read-tool-gap":       {"unattended": "MEDIUM", "interactive": "MEDIUM"},
    "ignored-in-project":  {"unattended": "MEDIUM", "interactive": "MEDIUM"},
    "weakening-flag":      {"unattended": "HIGH",   "interactive": "HIGH"},
    "broad-exclude":       {"unattended": "HIGH",   "interactive": "HIGH"},
    "narrow-exclude":      {"unattended": "MEDIUM", "interactive": "MEDIUM"},
    "broad-domain":        {"unattended": "HIGH",   "interactive": "HIGH"},
    "shared-host-domain":  {"unattended": "MEDIUM", "interactive": "MEDIUM"},
    "broad-write":         {"unattended": "HIGH",   "interactive": "HIGH"},
    "sensitive-write":     {"unattended": "MEDIUM", "interactive": "MEDIUM"},
    "own-proxy":           {"unattended": "MEDIUM", "interactive": "MEDIUM"},
    "bypass-unsandboxed":  {"unattended": "HIGH",   "interactive": "HIGH"},
    "parse-error":         {"unattended": "HIGH",   "interactive": "HIGH"},
    "outside-sandbox":     {"unattended": "INFO",   "interactive": "INFO"},
}

BASELINE = {
    "sandbox": {
        "enabled": True,
        "failIfUnavailable": True,
        "allowUnsandboxedCommands": False,
        "network": {"allowedDomains": ["registry.npmjs.org", "pypi.org", "files.pythonhosted.org"],
                    "strictAllowlist": True},
        "credentials": {"files": [{"path": p, "mode": "deny"} for p in ("~/.ssh", "~/.aws", "~/.config/gh")]},
    },
    "permissions": {"deny": ["Read(~/.ssh/**)", "Read(~/.aws/**)", "Read(~/.config/gh/**)"]},
}


# ---- 경로 정규화·비교 ------------------------------------------------------------
def norm_path(p, home):
    """샌드박스 경로를 '~/…' 또는 절대 경로 문자열로 맞춘다."""
    p = str(p).strip().replace("${HOME}", "~").replace("$HOME", "~")
    while len(p) > 1 and (p.endswith("/**") or p.endswith("/*") or p.endswith("/")):
        p = p[:-3] if p.endswith("/**") else p[:-2] if p.endswith("/*") else p[:-1]
    h = str(home).rstrip("/")
    if h and (p == h or p.startswith(h + "/")):
        p = "~" + p[len(h):]
    return p or "/"


def perm_read_path(rule, home):
    """`Read(~/.ssh/**)` → '~/.ssh', `Read(//etc/x)` → '/etc/x'. 비교할 수 없는 규칙은 None."""
    m = re.fullmatch(r"\s*Read\((.*)\)\s*", rule)
    if not m:
        return None
    inner = m.group(1).strip()
    if inner.startswith("//"):
        inner = inner[1:]
    elif not (inner.startswith("~") or inner.startswith("$HOME")):
        return None      # 프로젝트 상대·글롭 규칙은 샌드박스 경로와 직접 비교할 수 없다
    return norm_path(inner, home)


def covers(a, b):
    """경로 a가 b와 같거나 b를 포함하는가."""
    return a == b or a == "/" or b.startswith(a.rstrip("/") + "/")


# ---- 설정 읽기 ------------------------------------------------------------------
def read_json(path):
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return None, f"읽을 수 없음: {e.strerror or e}"
    try:
        data = json.loads(text)
    except ValueError as e:
        return None, f"JSON 파싱 실패: {e}"
    if not isinstance(data, dict):
        return None, "최상위가 객체가 아님"
    return data, None


def load_scopes(project, home, managed_files):
    """{scope: (path, data)} 와 파싱 오류 목록."""
    cands = {
        "user": home / ".claude" / "settings.json",
        "project": project / ".claude" / "settings.json" if project else None,
        "local": project / ".claude" / "settings.local.json" if project else None,
    }
    for m in managed_files:
        cands["managed"] = m
    scopes, errors = {}, []
    for scope, path in cands.items():
        if path is None or not path.is_file():
            continue
        data, err = read_json(path)
        if err:
            errors.append((scope, path, err))
        else:
            scopes[scope] = (path, data)
    return scopes, errors


def get(d, dotted, default=None):
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def sandbox_of(data):
    sb = data.get("sandbox")
    return sb if isinstance(sb, dict) else {}


def eff(scopes, key, default=None, only=None):
    """우선순위가 가장 높은 범위의 sandbox.<key> 값. (값, 범위)."""
    for sc in PRECEDENCE:
        if sc not in scopes or (only and sc not in only):
            continue
        v = get(sandbox_of(scopes[sc][1]), key, None)
        if v is not None:
            return v, sc
    return default, None


def collect_list(scopes, getter):
    """모든 범위의 목록을 합친다. [(값, 범위)]."""
    out = []
    for sc in PRECEDENCE:
        if sc in scopes:
            v = getter(scopes[sc][1])
            if isinstance(v, list):
                out += [(x, sc) for x in v]
    return out


# ---- 점검 ----------------------------------------------------------------------
class Linter:
    def __init__(self, scopes, home, profile, ignore):
        self.scopes, self.home, self.profile, self.ignore = scopes, home, profile, set(ignore)
        self.findings = []

    def add(self, rid, scope, key, msg, fix=""):
        if rid in self.ignore:
            return
        sev = RULES[rid][self.profile]
        if sev is None:
            return
        self.findings.append({"id": rid, "severity": sev, "scope": scope or "-", "key": key, "message": msg, "fix": fix})

    def run(self):
        s = self.scopes
        enabled, en_scope = eff(s, "enabled", False)
        enabled = enabled is True
        if not enabled:
            self.add("sandbox-off", en_scope, "sandbox.enabled",
                     "샌드박스가 꺼져 있다. Bash 명령이 쓰기·네트워크 제한 없이 돈다.",
                     'sandbox.enabled: true 를 사용자 또는 관리형 설정에 둔다')
        else:
            fiu, sc = eff(s, "failIfUnavailable", False)
            if fiu is not True:
                self.add("fail-open", sc, "sandbox.failIfUnavailable",
                         "샌드박스를 못 띄워도 멈추지 않고 제한 없이 실행한다 (bwrap/socat 없음, AppArmor 차단 등).",
                         "sandbox.failIfUnavailable: true")
        # 어느 범위든 false면 샌드박스 밖 재시도가 꺼진다 (사용자·관리형의 false는 프로젝트의 true보다 우선)
        vals = [(get(sandbox_of(s[sc][1]), "allowUnsandboxedCommands"), sc) for sc in PRECEDENCE if sc in s]
        if not any(v is False for v, _ in vals):
            self.add("unsandboxed-retry", next((sc for v, sc in vals if v is True), None),
                     "sandbox.allowUnsandboxedCommands",
                     "명령이 샌드박스에서 실패하면 샌드박스 밖에서 다시 실행하는 길이 열려 있다 (기본값).",
                     "sandbox.allowUnsandboxedCommands: false (엄격 샌드박스 모드)")
        if enabled:
            strict, _ = eff(s, "network.strictAllowlist", False, only=USER_ONLY)
            if strict is not True:
                self.add("no-strict-allowlist", None, "sandbox.network.strictAllowlist",
                         "허용 목록 밖 호스트에 물어보는 방식이라 무인 작업이 확인 대기에서 멈추거나 승인으로 뚫린다. "
                         "(이 키는 사용자·관리형·--settings에서만 효력이 있다)",
                         "사용자 설정에 sandbox.network.strictAllowlist: true")
        self.check_ignored_keys()
        self.check_weakening()
        self.check_credentials_and_read()
        self.check_excluded()
        self.check_domains()
        self.check_write()
        self.check_proxy()
        self.check_bypass(enabled)
        self.check_outside(enabled)
        self.findings.sort(key=lambda f: (-SEV_RANK[f["severity"]], f["id"], f["key"]))
        return self.findings

    def check_ignored_keys(self):
        for sc in ("project", "local"):
            if sc not in self.scopes:
                continue
            sb = sandbox_of(self.scopes[sc][1])
            for key in USER_ONLY_KEYS + MANAGED_ONLY_KEYS:
                v = get(sb, key)
                if v in (None, False, [], {}):
                    continue
                where = "관리형 설정에서만" if key in MANAGED_ONLY_KEYS else "사용자·관리형·--settings에서만"
                self.add("ignored-in-project", sc, f"sandbox.{key}",
                         f"{sc} 설정에 있지만 이 키는 {where} 효력이 있어 무시된다. 켜 둔 줄 알고 있으면 보호가 없다.",
                         "사용자 설정(~/.claude/settings.json)으로 옮긴다")
            for sect in ("files", "envVars"):
                for ent in get(sb, f"credentials.{sect}", []) or []:
                    if isinstance(ent, dict) and ent.get("mode") == "mask":
                        self.add("ignored-in-project", sc, f"sandbox.credentials.{sect}",
                                 f"`mask` 항목은 {sc} 설정에서 무시된다 (사용자·관리형·--settings 전용).",
                                 "사용자 설정으로 옮기거나 mode를 deny로 바꾼다")

    def check_weakening(self):
        flags = ["enableWeakerNestedSandbox", "allowNestedUserNamespaces", "allowAppleEvents",
                 "network.allowAllUnixSockets", "filesystem.disabled"]
        for sc in PRECEDENCE:
            if sc not in self.scopes:
                continue
            sb = sandbox_of(self.scopes[sc][1])
            for key in flags:
                if get(sb, key) is True:
                    self.add("weakening-flag", sc, f"sandbox.{key}",
                             "샌드박스 경계를 약하게 만드는 플래그가 켜져 있다.", "필요한 이유가 없으면 끈다")
            if get(sb, "credentials.allowPlaintextInject") is True:
                self.add("weakening-flag", sc, "sandbox.credentials.allowPlaintextInject",
                         "평문 요청에도 실제 비밀값을 주입한다.", "끈다")

    def denied_paths(self):
        out = []
        for v, sc in collect_list(self.scopes, lambda d: get(sandbox_of(d), "filesystem.denyRead")):
            if isinstance(v, str):
                out.append((norm_path(v, self.home), sc, "sandbox.filesystem.denyRead"))
        for v, sc in collect_list(self.scopes, lambda d: get(sandbox_of(d), "credentials.files")):
            if isinstance(v, dict) and v.get("mode") == "deny" and isinstance(v.get("path"), str):
                out.append((norm_path(v["path"], self.home), sc, "sandbox.credentials.files"))
        return out

    def check_credentials_and_read(self):
        denied = self.denied_paths()
        # 자격 증명 경로가 sandbox deny로 덮여 있나 (permissions.deny의 Read 규칙도 샌드박스에 합쳐진다)
        read_rules = []
        for v, sc in collect_list(self.scopes, lambda d: get(d, "permissions.deny")):
            if isinstance(v, str):
                p = perm_read_path(v, self.home)
                if p:
                    read_rules.append(p)
        protected = [p for p, _, _ in denied] + read_rules
        missing = [c for c in CRED_DIRS if not any(covers(p, c) for p in protected)]
        if missing:
            self.add("cred-not-denied", None, "sandbox.credentials.files",
                     "읽기 거부가 없는 자격 증명 경로: " + ", ".join(missing) +
                     ". 샌드박스는 기본값에서 읽기를 막지 않아 Bash가 읽고 허용된 도메인으로 보낼 수 있다.",
                     'sandbox.credentials.files 에 {"path": "~/.ssh", "mode": "deny"} 처럼 추가')
        # sandbox deny만 있고 내장 Read 도구 규칙이 없는 경로
        for p, sc, key in denied:
            if not any(covers(r, p) for r in read_rules):
                self.add("read-tool-gap", sc, key,
                         f"`{p}`는 Bash에서만 막힌다. 내장 Read 도구는 permissions 규칙을 따르므로 여전히 읽을 수 있다.",
                         f'permissions.deny 에 "Read({p}/**)" 를 함께 둔다')

    def check_excluded(self):
        for v, sc in collect_list(self.scopes, lambda d: get(sandbox_of(d), "excludedCommands")):
            if not isinstance(v, str):
                continue
            toks = v.split()
            if not toks:
                continue
            if v.strip() in ("*", "**") or toks[0] in INTERPRETERS:
                self.add("broad-exclude", sc, "sandbox.excludedCommands",
                         f"`{v}`는 샌드박스 밖에서 제한 없이 돈다. 셸·인터프리터·전체 제외는 샌드박스 전체의 구멍이다.",
                         "서브명령까지 좁힌다 (예: docker compose up *) 또는 컨테이너 안에서 실행")
            elif len(toks) == 1 or (len(toks) == 2 and toks[1] == "*"):
                self.add("narrow-exclude", sc, "sandbox.excludedCommands",
                         f"`{v}`는 서브명령 없이 명령 전체를 샌드박스 밖으로 뺀다.",
                         f"`{toks[0]} <서브명령> *` 처럼 더 좁힌다")

    def check_domains(self):
        for v, sc in collect_list(self.scopes, lambda d: get(sandbox_of(d), "network.allowedDomains")):
            if not isinstance(v, str):
                continue
            d = v.strip().lower()
            bare = d.lstrip("*.")
            if d == "*" or re.fullmatch(r"\*\.[a-z0-9-]+", d):
                self.add("broad-domain", sc, "sandbox.network.allowedDomains",
                         f"`{v}`는 사실상 모든 호스트를 허용한다. 프록시는 호스트 이름만 보므로 어디로든 유출 가능하다.",
                         "필요한 호스트 이름만 적는다")
            elif any(bare == s or bare.endswith("." + s) for s in SHARED_HOST_SUFFIXES):
                self.add("shared-host-domain", sc, "sandbox.network.allowedDomains",
                         f"`{v}`는 아무나 올릴 수 있는 공용 호스팅이라 유출 경로가 된다.",
                         "정확한 서브도메인(예: my-bucket.s3.amazonaws.com)으로 좁힌다")

    def check_write(self):
        for v, sc in collect_list(self.scopes, lambda d: get(sandbox_of(d), "filesystem.allowWrite")):
            if not isinstance(v, str):
                continue
            p = norm_path(v, self.home)
            if p in BROAD_WRITE:
                self.add("broad-write", sc, "sandbox.filesystem.allowWrite",
                         f"`{v}`는 쓰기 범위가 너무 넓다. 작업 폴더 밖 전체를 여는 것과 같다.", "필요한 하위 폴더만 적는다")
                continue
            hit = [c for c in CRED_DIRS[:4] if covers(p, c) or covers(c, p)]
            hit += [c for c in STARTUP_PATHS if covers(p, c)]
            if hit:
                self.add("sensitive-write", sc, "sandbox.filesystem.allowWrite",
                         f"`{v}`가 쓰기를 열어 주는 민감 경로: {', '.join(sorted(set(hit)))}", "그 경로를 빼거나 하위 경로로 좁힌다")

    def check_proxy(self):
        for sc in PRECEDENCE:
            if sc not in self.scopes:
                continue
            sb = sandbox_of(self.scopes[sc][1])
            for key in ("network.httpProxyPort", "network.socksProxyPort"):
                if get(sb, key) is not None:
                    self.add("own-proxy", sc, f"sandbox.{key}",
                             "자체 프록시로 보내면 Claude Code의 도메인 허용·차단이 그 트래픽에 적용되지 않는다.",
                             "프록시 쪽에서 같은 허용 목록을 강제하는지 확인한다")

    def check_bypass(self, enabled):
        mode, sc = None, None
        for s_ in PRECEDENCE:
            if s_ in self.scopes:
                m = get(self.scopes[s_][1], "permissions.defaultMode")
                if m is not None:
                    mode, sc = m, s_
                    break
        if mode != "bypassPermissions":
            return
        vals = [get(sandbox_of(self.scopes[x][1]), "allowUnsandboxedCommands") for x in self.scopes]
        strict = enabled and any(v is False for v in vals)
        if not strict:
            self.add("bypass-unsandboxed", sc, "permissions.defaultMode",
                     "bypassPermissions에서는 샌드박스 밖 재시도까지 자동 승인된다. 샌드박스가 없는 것과 같다.",
                     "엄격 샌드박스(allowUnsandboxedCommands: false)를 같이 쓰거나 컨테이너·VM에서 돌린다")

    def check_outside(self, enabled):
        if not enabled:
            return
        found = []
        for sc in PRECEDENCE:
            if sc not in self.scopes:
                continue
            d = self.scopes[sc][1]
            if isinstance(d.get("hooks"), dict) and d["hooks"]:
                found.append(f"hooks({sc})")
            for k in ("statusLine", "apiKeyHelper"):
                if d.get(k):
                    found.append(f"{k}({sc})")
        if found:
            self.add("outside-sandbox", None, "hooks/statusLine/apiKeyHelper",
                     "샌드박스가 감싸지 않는 것: " + ", ".join(found) + ". 이들은 전체 권한으로 돈다. 내장 도구(Read·Edit·WebFetch)와 로컬 MCP 서버도 마찬가지다.",
                     "훅 스크립트와 로컬 MCP 서버는 따로 검토한다")


def render(findings, scopes, errors, profile):
    lines = [f"sandbox-lint · 프로필 {profile} · 읽은 설정: " +
             (", ".join(f"{sc}={p}" for sc, (p, _) in scopes.items()) or "없음")]
    for f in findings:
        lines.append(f"[{f['severity']:<6}] {f['id']:<19} ({f['scope']}) {f['key']}")
        lines.append(f"          {f['message']}")
        if f["fix"]:
            lines.append(f"          → {f['fix']}")
    n = {k: sum(1 for f in findings if f["severity"] == k) for k in SEV_RANK}
    verdict = "위험 — 이 설정으로 무인 작업을 돌리지 말 것" if n["HIGH"] else "검토 필요" if n["MEDIUM"] else "문제 없음"
    lines.append(f"HIGH {n['HIGH']} · MEDIUM {n['MEDIUM']} · INFO {n['INFO']} → {verdict}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Claude Code 샌드박스 설정 점검")
    ap.add_argument("project", nargs="?", default=".", help="프로젝트 폴더 또는 settings.json 파일 (기본: .)")
    ap.add_argument("--home", default=str(Path.home()), help="사용자 설정을 찾을 홈 폴더 (기본: 실제 홈)")
    ap.add_argument("--managed", action="append", default=[], help="관리형 settings 파일 (반복 가능)")
    ap.add_argument("--no-managed", action="store_true", help="기본 관리형 설정 경로를 읽지 않는다")
    ap.add_argument("--profile", choices=["unattended", "interactive"], default="unattended")
    ap.add_argument("--ignore", action="append", default=[], metavar="ID", help="규칙 끄기 (반복 가능)")
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    ap.add_argument("--print-baseline", action="store_true", help="무인 작업용 권장 설정 조각을 출력하고 끝낸다")
    args = ap.parse_args(argv)

    if args.print_baseline:
        print(json.dumps(BASELINE, indent=2, ensure_ascii=False))
        return 0
    bad = [i for i in args.ignore if i not in RULES]
    if bad:
        print(f"알 수 없는 규칙 id: {', '.join(bad)}\n사용 가능: {', '.join(RULES)}", file=sys.stderr)
        return 3
    target, home = Path(args.project).expanduser(), Path(args.home).expanduser()
    if not target.exists():
        print(f"경로가 없다: {target}", file=sys.stderr)
        return 3
    managed = [Path(m).expanduser() for m in args.managed]
    if not args.managed and not args.no_managed:
        managed = [p for p in (Path("/etc/claude-code/managed-settings.json"),
                               Path("/Library/Application Support/ClaudeCode/managed-settings.json")) if p.is_file()][:1]

    if target.is_file():                       # 파일 하나를 직접 점검: 사용자 설정처럼 취급한다
        data, err = read_json(target)
        scopes, errors = ({}, [("user", target, err)]) if err else ({"user": (target, data)}, [])
        for m in managed:
            d2, e2 = read_json(m)
            if e2:
                errors.append(("managed", m, e2))
            else:
                scopes["managed"] = (m, d2)
    else:
        scopes, errors = load_scopes(target, home, managed)

    lint = Linter(scopes, home, args.profile, args.ignore)
    findings = lint.run()
    for sc, path, err in errors:
        lint.add("parse-error", sc, str(path), f"{err} — 이 설정은 점검하지 못했다. 샌드박스가 꺼진 상태일 수 있다.", "JSON 문법을 고친다")
    findings = sorted(lint.findings, key=lambda f: (-SEV_RANK[f["severity"]], f["id"], f["key"]))
    if not scopes and not errors:
        print("읽을 settings.json이 하나도 없다 — 샌드박스 설정이 없으면 꺼진 것이다.", file=sys.stderr)
    if args.json:
        print(json.dumps({"profile": args.profile, "scopes": {k: str(p) for k, (p, _) in scopes.items()},
                          "findings": findings}, ensure_ascii=False, indent=2))
    else:
        print(render(findings, scopes, errors, args.profile))
    worst = max((SEV_RANK[f["severity"]] for f in findings), default=0)
    return 2 if worst == 2 else 1 if worst == 1 else 0


if __name__ == "__main__":
    sys.exit(main())

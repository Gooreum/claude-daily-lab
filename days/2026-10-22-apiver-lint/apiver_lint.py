#!/usr/bin/env python3
"""apiver-lint — Claude API 버전 2023-06-01 → 2026-10-21 업그레이드 사전 점검 린터.

표준 라이브러리만 쓴다. API 키·네트워크 불필요.

    python3 apiver_lint.py <path>... [--json] [--min-level error|warn|info]
                                      [--ignore V01,V05] [--exclude NAME]...

레벨: error = 업그레이드하면 400·TypeError·ValueError가 확정 / warn = 코드를 보고 판단 / info = 해야 할 일(핀 올리기).
규칙 출처: https://platform.claude.com/docs/en/api/migration-2026-10-21
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict

CODE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".java", ".kt", ".rb",
             ".php", ".cs", ".sh", ".bash", ".zsh", ".ipynb", ".conf"}
CONFIG_EXTS = {".json", ".yaml", ".yml", ".toml", ".env"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", "vendor"}
MAX_BYTES = 2_000_000

LEVELS = {"error": 0, "warn": 1, "info": 2}
LEVEL_LABEL = {"error": "ERROR 업그레이드 시 실패 확정", "warn": "WARN  확인 필요", "info": "INFO  해야 할 일"}

ANTHROPIC_CTX = re.compile(r"anthropic|claude", re.I)
COMMENT_START = ("#", "//", "*", "/*", "<!--")

RULES = {
    "V01": "temperature·top_p·top_k 제거 (모든 모델에서 400)",
    "V02": "assistant 메시지 안의 document 블록 (400)",
    "V03": "user 메시지 text 블록의 비어 있지 않은 citations (400)",
    "V04": "SDK 메이저 핀 / 플랫폼 패키지와 sdk 버전 짝",
    "V05": "anthropic-version 헤더를 직접 보냄",
    "V06": "제거된 Text Completions",
    "V07": "게이트웨이·프록시가 X-Api-Key를 읽음 (SDK는 Authorization: Bearer)",
    "V08": "클라이언트에 자격 증명 둘 (api_key + auth_token)",
    "V09": "MessageParam을 호출·상속 (TypeError)",
    "V10": "TypeScript compactionControl 제거",
    "V11": "비베타 models.list/retrieve에 betas",
    "V12": "Go 모듈·ant CLI 경로에 /v2",
    "V13": "Admin·Analytics API의 옛 필드 이름",
}


@dataclass
class Finding:
    file: str
    line: int
    rule: str
    level: str
    message: str
    snippet: str = ""


def is_comment(line: str) -> bool:
    return line.lstrip().startswith(COMMENT_START)


def last_role(lines: list[str], idx: int, back: int = 14) -> str | None:
    """idx 줄 위쪽(자기 줄 포함) 가장 가까운 role 표시. user/assistant/system 또는 None."""
    pat = re.compile(r"""role["']?\s*[:=]\s*["'](user|assistant|system)["']|\b(User|Assistant|System)MessageParam\b""")
    for j in range(idx, max(-1, idx - back - 1), -1):
        m = pat.search(lines[j])
        if m:
            return (m.group(1) or m.group(2)).lower()
    return None


# ─── 코드 규칙 ──────────────────────────────────────────────────────────────
SAMPLING = re.compile(r"""(?<![\w.\-`])["']?(temperature|top_p|top_k)["']?\s*[:=](?!=)|--(temperature|top-p|top-k)\b""")
DOC_BLOCK = re.compile(r"""["']?type["']?\s*[:=]\s*["']document["']""")
CITATIONS_OPEN = re.compile(r"""["']?citations["']?\s*[:=]\s*\[\s*(\S?)""")
ANTHROPIC_VERSION = re.compile(r"""anthropic-version["']?\s*[:=,]\s*["']?(\d{4}-\d{2}-\d{2})""", re.I)
COMPLETIONS = [
    (re.compile(r"\b(?:client|anthropic)\.completions\b"), "client.completions"),
    (re.compile(r"/v1/complete\b"), "/v1/complete"),
    (re.compile(r"\b(HUMAN_PROMPT|AI_PROMPT)\b"), "HUMAN_PROMPT/AI_PROMPT"),
    (re.compile(r"\bmax_tokens_to_sample\b|--max-tokens-to-sample"), "max_tokens_to_sample"),
    (re.compile(r"\bant\s+completions\b"), "ant completions"),
]
XAPIKEY_READ = re.compile(
    r"""\$http_x_api_key|proxy_set_header\s+x-api-key|"""
    r"""\b(?:req|request|r|ctx)\.\w*headers?\S{0,12}x-api-key|"""
    r"""headers?\.get\(\s*["']x-api-key|Header\.Get\(\s*["']x-api-key""", re.I)
CTOR = re.compile(r"\b(Async)?Anthropic\(|new\s+Anthropic\(")
MESSAGEPARAM_CALL = re.compile(r"(?<![\w.\[,])(?<!class )(Beta)?MessageParam\(")
MESSAGEPARAM_SUBCLASS = re.compile(r"class\s+\w+\(\s*(Beta)?MessageParam\s*\)")
MODELS_BETAS = re.compile(r"(?<!beta\.)(?<!Beta\.)\bmodels\.(?:list|retrieve)\([^)]*\bbetas\b")
GO_IMPORT = re.compile(r'"github\.com/anthropics/anthropic-sdk-go(?!/v2)(?:/[\w/]+)?"')
ANT_INSTALL = re.compile(r"github\.com/anthropics/anthropic-cli/cmd/ant")

# Admin/Analytics 옛 필드: (파일에 있어야 할 힌트, 필드 정규식, 새 이름)
ADMIN_FIELDS = [
    (re.compile(r"api_keys"), re.compile(r"""\[["']workspace_id["']\]|(?<!scope)\.workspace_id\b|\.get\(["']workspace_id["']"""),
     "API 키의 `workspace_id` → `scope.workspace_id` (전 워크스페이스 키는 scope.type=organization)"),
    (re.compile(r"rbac_groups"), re.compile(r"""\[["']roles["']\]|\.roles\b|\.get\(["']roles["']"""),
     "RBAC 그룹 `roles` → `role_ids`"),
    (re.compile(r"rbac_groups.*members|members.*rbac_groups", re.S), re.compile(r"""\[["']group_id["']\]|\.group_id\b"""),
     "RBAC 멤버 `group_id` → `rbac_group_id`"),
    (re.compile(r"rbac_roles"), re.compile(r"""\[["']name["']\]|\.get\(["']name["']"""),
     "RBAC 역할 `name` → `display_name`"),
    (re.compile(r"rate_limits"), re.compile(r"""\[["']group_type["']\]|\.group_type\b"""),
     "레이트 리밋 응답 `group_type` → `group.type` (쿼리 파라미터 group_type은 그대로)"),
    (re.compile(r"analytics|user_usage_report|user_cost_report"), re.compile(r"""actor\.email\b(?!_)|\[["']actor["']\]\[["']email["']\]"""),
     "Analytics `actor.email` → `actor.email_address`"),
    (re.compile(r"analytics|summaries"), re.compile(r"""\[["']summaries["']\]|\.summaries\b"""),
     "Analytics 활동 요약 `summaries` → `data`"),
]


def scan_code(path: str, text: str, ext: str) -> list[Finding]:
    out: list[Finding] = []
    lines = text.splitlines()
    # 주석에서 이름만 언급한 파일(다른 LLM 코드 등)이 켜지지 않게 주석 줄은 뺀다
    ctx = any(ANTHROPIC_CTX.search(ln) for ln in lines if not is_comment(ln))
    is_config = ext in CONFIG_EXTS

    def add(i: int, rule: str, level: str, msg: str) -> None:
        out.append(Finding(path, i + 1, rule, level, msg, lines[i].strip()[:140]))

    for i, line in enumerate(lines):
        if is_comment(line):
            continue
        # V05는 Anthropic 언급이 없어도 헤더 이름만으로 확실하다
        m = ANTHROPIC_VERSION.search(line)
        if m and m.group(1) == "2023-06-01":
            add(i, "V05", "info", "`anthropic-version: 2023-06-01`을 직접 보냄. V01~V03·V13을 정리한 뒤 2026-10-21로 올리거나, 이 호출만 옛 버전으로 남긴다")
        if XAPIKEY_READ.search(line) and ctx:
            add(i, "V07", "warn", "프록시·게이트웨이가 `X-Api-Key`를 읽음. SDK 2.0/1.0·`ant` 2.0은 키를 `Authorization: Bearer`로 보내므로 둘 다 읽게 고친다")
        if not ctx:
            continue
        m = SAMPLING.search(line)
        if m:
            name = m.group(1) or m.group(2)
            wrapper = bool(re.search(r"\bdef\b|:\s*(float|int|Optional|number)\b", line))
            level = "warn" if (is_config or wrapper) else "error"
            why = "래퍼 인자/설정값: Messages 요청까지 흘러가는지 확인하고 제거" if level == "warn" else "2026-10-21에서 400 (기본값을 보내도). 제거하고 프롬프트로 유도"
            add(i, "V01", level, f"`{name}` — {why}")
        if DOC_BLOCK.search(line) and last_role(lines, i) == "assistant":
            add(i, "V02", "warn", "assistant 메시지에 직접 넣은 `document` 블록은 400. user 메시지로 옮긴다 (도구 결과 안에 중첩된 문서는 허용)")
        m = CITATIONS_OPEN.search(line)
        if m and last_role(lines, i) == "user":
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if m.group(1) not in ("", "]") or (m.group(1) == "" and nxt and not nxt.startswith("]")):
                add(i, "V03", "warn", "user 메시지 text 블록의 비어 있지 않은 `citations`는 400. 제거 (assistant 쪽·`citations: {enabled: true}` 설정은 허용)")
        for pat, label in COMPLETIONS:
            # JSON·YAML은 문서 본문 같은 데이터가 많아 코드 확장자에서만 본다
            if not is_config and pat.search(line):
                removed = ext in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".java", ".kt", ".rb", ".sh", ".bash"}
                add(i, "V06", "error" if removed else "warn",
                    f"Text Completions(`{label}`)는 TypeScript·Go·Java·Ruby SDK와 `ant`에서 제거됨. Messages API로 옮긴다"
                    + ("" if removed else " (이 언어 SDK에는 아직 남아 있으나 새 모델 미지원)"))
                break
        if CTOR.search(line):
            window = "\n".join(lines[i:i + 9])
            if re.search(r"\bapi_key\s*=", window) and re.search(r"\bauth_token\s*=", window):
                add(i, "V08", "error", "한 클라이언트에 `api_key`와 `auth_token`을 함께 넘기면 Python SDK 2.0은 `ValueError`. 하나만 넘긴다")
            elif re.search(r"\bapiKey\s*:", window) and re.search(r"\bauthToken\s*:", window):
                add(i, "V08", "warn", "한 클라이언트는 자격 증명 하나만 가짐(키와 토큰이 같은 헤더). `apiKey`·`authToken` 중 하나만 넘긴다")
        if MESSAGEPARAM_CALL.search(line) and not line.lstrip().startswith(("import ", "from ")):
            add(i, "V09", "error", "`MessageParam(...)`은 2.0에서 `TypeError`. 딕셔너리 리터럴로 쓴다: `m: MessageParam = {\"role\": ..., \"content\": ...}`")
        if MESSAGEPARAM_SUBCLASS.search(line):
            add(i, "V09", "error", "`MessageParam` 상속은 `TypeError`. 역할별 `UserMessageParam` 등을 상속한다")
        if re.search(r"\bcompactionControl\b", line):
            add(i, "V10", "error", "`compactionControl`은 제거(0.129부터 이미 예외). `betas: [\"compact-2026-01-12\"]` + `context_management.edits`로 서버 측 압축")
        if MODELS_BETAS.search(line):
            add(i, "V11", "error", "비베타 `models.list/retrieve`는 `betas`를 받지 않음(TypeError). `client.beta.models.…`로 호출")
        if ext == ".go" and GO_IMPORT.search(line):
            add(i, "V12", "info", "Go SDK 2.0은 import 경로가 `github.com/anthropics/anthropic-sdk-go/v2…`")
        if ANT_INSTALL.search(line):
            add(i, "V12", "info", "`ant` 2.0의 모듈 경로는 `github.com/anthropics/anthropic-cli/v2/cmd/ant@latest`")

    # V13: 파일에 힌트 단어가 있을 때만 필드 읽기를 본다
    if ctx and re.search(r"organizations|admin", text, re.I):
        for hint, field, msg in ADMIN_FIELDS:
            for i, line in enumerate(lines):
                if is_comment(line) or not field.search(line):
                    continue
                # 필드 이름(`name`, `roles`)은 흔하므로, 같은 줄이나 바로 위 4줄에 해당 엔드포인트가 있을 때만
                near = "\n".join(lines[max(0, i - 4):i + 1])
                if hint.search(near):
                    add(i, "V13", "warn", f"2026-10-21 응답에서 옛 필드가 빠짐: {msg}")
    return out


# ─── 의존성 파일 규칙 ────────────────────────────────────────────────────────
PLATFORM_PKGS = ("@anthropic-ai/bedrock-sdk", "@anthropic-ai/vertex-sdk", "@anthropic-ai/foundry-sdk",
                 "@anthropic-ai/aws-sdk", "@anthropic-ai/google-cloud-sdk")


def major_of(spec: str) -> int | None:
    m = re.search(r"\d+", spec or "")
    return int(m.group()) if m else None


def py_spec_state(spec: str) -> str:
    """파이썬 버전 지정이 2.x를 막으면 'capped', 상한이 없으면 'open', 지정이 없으면 'unpinned'."""
    spec = (spec or "").strip()
    if not spec:
        return "unpinned"
    if spec[0] in "^~" and spec[:2] != "~=":
        mj = major_of(spec)
        return "capped" if mj is not None and mj < 2 else "open"
    for clause in spec.split(","):
        m = re.match(r"\s*(===|==|~=|<=|>=|<|>|!=)\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?", clause)
        if not m:
            continue
        op, mj = m.group(1), int(m.group(2))
        mn, pt = int(m.group(3) or 0), int(m.group(4) or 0)
        if op in ("==", "===", "~=") and mj < 2:
            return "capped"
        if op == "<=" and mj < 2:
            return "capped"
        if op == "<" and (mj < 2 or (mj == 2 and mn == 0 and pt == 0)):
            return "capped"
    return "open"


def scan_deps(path: str, text: str, base: str) -> list[Finding]:
    out: list[Finding] = []
    lines = text.splitlines()

    def add(i: int, level: str, msg: str) -> None:
        out.append(Finding(path, i + 1, "V04", level, msg, lines[i].strip()[:140] if 0 <= i < len(lines) else ""))

    if base == "package.json":
        try:
            data = json.loads(text)
        except ValueError:
            return out
        deps: dict[str, str] = {}
        for sec in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            if isinstance(data.get(sec), dict):
                deps.update(data[sec])
        sdk = deps.get("@anthropic-ai/sdk")
        sdk_major = major_of(sdk) if sdk else None

        def line_of(name: str) -> int:
            for i, ln in enumerate(lines):
                if f'"{name}"' in ln:
                    return i
            return 0
        if sdk_major is not None and sdk_major < 1:
            add(line_of("@anthropic-ai/sdk"), "info", f"`@anthropic-ai/sdk` {sdk} → 1.0.0 이상으로 올리고 플랫폼 패키지도 같은 PR에서 1.x로")
        for pkg in PLATFORM_PKGS:
            if pkg in deps:
                pm = major_of(deps[pkg])
                if sdk_major is None or pm is None:
                    continue
                if pm < 1 <= sdk_major or sdk_major < 1 <= pm:
                    add(line_of(pkg), "error", f"`{pkg}` {deps[pkg]}와 `@anthropic-ai/sdk` {sdk}의 메이저가 어긋남 — 옛 sdk가 하나 더 설치됨. 같이 1.x로")
                elif pm < 1:
                    add(line_of(pkg), "info", f"`{pkg}` {deps[pkg]} → 1.0.0 이상 (sdk와 같은 PR)")
        return out

    if base == "composer.json":
        try:
            data = json.loads(text)
        except ValueError:
            return out
        req = {**data.get("require", {}), **data.get("require-dev", {})}
        v = req.get("anthropic-ai/sdk")
        if v is not None and (major_of(v) or 0) < 1:
            idx = next((i for i, ln in enumerate(lines) if "anthropic-ai/sdk" in ln), 0)
            add(idx, "info", f"`anthropic-ai/sdk` {v} → 1.0.0 (`composer require \"anthropic-ai/sdk\"`; `composer update`만으로는 제약 안에 머문다)")
        return out

    if base == "go.mod":
        for i, ln in enumerate(lines):
            if re.search(r"github\.com/anthropics/anthropic-sdk-go\s+v\d", ln):
                add(i, "info", "Go SDK 2.0.0은 모듈 경로가 `…/anthropic-sdk-go/v2`. import를 모두 바꾸고 `go get github.com/anthropics/anthropic-sdk-go/v2`")
        return out

    if base == "Gemfile":
        for i, ln in enumerate(lines):
            m = re.match(r"""\s*gem\s+["']anthropic["'](?:\s*,\s*["']([^"']+)["'])?""", ln)
            if m and (major_of(m.group(1) or "") or 0) < 2 and m.group(1):
                add(i, "info", f"`anthropic` gem {m.group(1)} → 2.0.0")
        return out

    if base in ("pom.xml", "build.gradle", "build.gradle.kts"):
        for m in re.finditer(r"anthropic-java[^0-9\n]{0,60}?(\d+)\.\d+\.\d+", text, re.S):
            if int(m.group(1)) < 3:
                add(text.count("\n", 0, m.start()), "info", f"`anthropic-java` {m.group(0)[-12:].strip(' >:\"')} → 3.0.0")
        return out

    if base.endswith(".csproj"):
        for i, ln in enumerate(lines):
            m = re.search(r"""Include=["']Anthropic["']\s+Version=["'](\d+)""", ln)
            if m and int(m.group(1)) < 13:
                add(i, "info", f"`Anthropic` NuGet {m.group(1)}.x → 13.0.0")
        return out

    # requirements*.txt, pyproject.toml, setup.cfg, Pipfile
    pep = re.compile(r"""^\s*["']?anthropic(?:\[[^\]]*\])?(?![\w.\-])\s*([<>=!~][^"'#\s;]*(?:\s*,\s*[<>=!~][^"'#\s;]*)*)?""")
    poetry = re.compile(r"""^\s*anthropic\s*=\s*(?:\{[^}]*version\s*=\s*)?["']([^"']*)["']""")
    for i, ln in enumerate(lines):
        if is_comment(ln):
            continue
        spec = None
        m = poetry.match(ln)
        if m:
            spec = m.group(1)
        else:
            m = pep.match(ln)
            if m:
                spec = (m.group(1) or "").replace(" ", "")
            else:
                continue
        state = py_spec_state(spec)
        if state == "capped":
            add(i, "info", f"`anthropic` {spec or '(핀 없음)'}가 2.x를 막음 → `>=2,<3`으로 (SDK 2.0이 `2026-10-21`을 기본으로 보냄)")
        elif state == "unpinned":
            add(i, "warn", "`anthropic` 버전 핀이 없음 — 다음 설치가 2.x를 받아 V01~V03이 한꺼번에 터질 수 있다. `>=1.17,<2`로 묶고 계획적으로 올린다")
    return out


DEP_BASENAMES = ("package.json", "composer.json", "go.mod", "Gemfile", "pom.xml", "build.gradle", "build.gradle.kts",
                 "pyproject.toml", "setup.cfg", "Pipfile")


def is_dep_file(base: str) -> bool:
    return base in DEP_BASENAMES or base.endswith(".csproj") or bool(re.match(r"requirements.*\.txt$", base))


def iter_files(paths: list[str], excludes: set[str]):
    for p in paths:
        if os.path.isfile(p):
            yield p
            continue
        for root, dirs, files in os.walk(p):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and d not in excludes)
            for f in sorted(files):
                if f in excludes:
                    continue
                yield os.path.join(root, f)


def lint_file(path: str) -> list[Finding]:
    base = os.path.basename(path)
    ext = os.path.splitext(base)[1].lower()
    dep = is_dep_file(base)
    if not dep and ext not in CODE_EXTS and ext not in CONFIG_EXTS and base != "Dockerfile" and base != "nginx.conf":
        return []
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return []
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return []
    out: list[Finding] = []
    if dep:
        out += scan_deps(path, text, base)
        if ext not in CODE_EXTS:
            return out
    if ext in CODE_EXTS or ext in CONFIG_EXTS or base in ("Dockerfile", "nginx.conf"):
        if not base.startswith("package-lock") and base not in ("package.json", "composer.json"):
            out += scan_code(path, text, ext)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Claude API 버전 2026-10-21 업그레이드 사전 점검")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--json", action="store_true", help="기계용 JSON 출력")
    ap.add_argument("--min-level", choices=list(LEVELS), default="info")
    ap.add_argument("--ignore", default="", help="쉼표로 구분한 규칙 ID (예: V05,V12)")
    ap.add_argument("--exclude", action="append", default=[], help="건너뛸 폴더·파일 이름 (여러 번 가능)")
    args = ap.parse_args(argv)

    ignore = {r.strip().upper() for r in args.ignore.split(",") if r.strip()}
    unknown = ignore - set(RULES)
    if unknown:
        print(f"알 수 없는 규칙: {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    for p in args.paths:
        if not os.path.exists(p):
            print(f"경로 없음: {p}", file=sys.stderr)
            return 2

    findings: list[Finding] = []
    nfiles = 0
    for f in iter_files(args.paths, set(args.exclude)):
        nfiles += 1
        findings += lint_file(f)
    seen = set()
    uniq = []
    for f in findings:
        key = (f.file, f.line, f.rule, f.message)
        if key in seen or f.rule in ignore or LEVELS[f.level] > LEVELS[args.min_level]:
            continue
        seen.add(key)
        uniq.append(f)
    uniq.sort(key=lambda f: (f.file, f.line, f.rule))
    counts = {lv: sum(1 for f in uniq if f.level == lv) for lv in LEVELS}
    by_rule: dict[str, int] = {}
    for f in uniq:
        by_rule[f.rule] = by_rule.get(f.rule, 0) + 1

    if args.json:
        print(json.dumps({"findings": [asdict(f) for f in uniq], "summary": {**counts, "by_rule": by_rule, "files_scanned": nfiles}},
                         ensure_ascii=False, indent=2))
    else:
        cur = None
        for f in uniq:
            if f.file != cur:
                cur = f.file
                print(f"\n{f.file}")
            print(f"  {f.line:>5}  {f.rule}  {LEVEL_LABEL[f.level]}  {f.message}")
            if f.snippet:
                print(f"         │ {f.snippet}")
        print(f"\n합계: error {counts['error']} · warn {counts['warn']} · info {counts['info']}  (파일 {nfiles}개 검사)")
        if by_rule:
            print("규칙별: " + ", ".join(f"{r}×{n}" for r, n in sorted(by_rule.items())))
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    sys.exit(main())

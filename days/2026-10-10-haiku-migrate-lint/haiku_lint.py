#!/usr/bin/env python3
"""haiku-migrate-lint — Claude Haiku 4.5 → 5.5 마이그레이션 정적 린터.

표준 라이브러리만 쓴다. API 키·네트워크 불필요.

    python3 haiku_lint.py <path>... [--platform api|bedrock|vertex] [--json]
                                     [--fix] [--dry-run] [--min-level error|warn|info]

규칙 출처: https://platform.claude.com/docs/en/models/haiku-5-5/migration-guide
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from dataclasses import dataclass, asdict

EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".jsonl",
        ".yaml", ".yml", ".toml", ".ipynb", ".sh", ".md", ".env", ".txt"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next"}
MAX_BYTES = 2_000_000

LEVELS = {"error": 0, "warn": 1, "info": 2}
LEVEL_LABEL = {"error": "ERROR 400 확정", "warn": "WARN  확인 필요", "info": "INFO  권장"}

# ─── 모델 ID 치환표 (플랫폼별) ───────────────────────────────────────────────
MODEL_ID_PATTERNS = [
    # (정규식, 설명, {platform: 새 ID})
    (r"claude-haiku-4-5(?:-20251001)?(?![\w@-])", "Claude API / Foundry / Platform on AWS Haiku 4.5 ID",
     {"api": "claude-haiku-5-5", "bedrock": "anthropic.claude-haiku-5-5", "vertex": "claude-haiku-5-5"}),
    (r"claude-haiku-4-5@20251001", "Google Cloud(Vertex) Haiku 4.5 ID",
     {"api": "claude-haiku-5-5", "bedrock": "anthropic.claude-haiku-5-5", "vertex": "claude-haiku-5-5"}),
    (r"anthropic\.claude-haiku-4-5(?:-20251001)?(?:-v1:0)?(?![\w-])", "Amazon Bedrock Haiku 4.5 ID",
     {"api": "claude-haiku-5-5", "bedrock": "anthropic.claude-haiku-5-5", "vertex": "claude-haiku-5-5"}),
    (r"claude-3-5-haiku(?:-20241022|-latest)?(?![\w@-])", "Haiku 3.5 ID (API에서 retired)",
     {"api": "claude-haiku-5-5", "bedrock": "anthropic.claude-haiku-5-5", "vertex": "claude-haiku-5-5"}),
    (r"claude-3-5-haiku@20241022", "Haiku 3.5 Vertex ID (deprecated)",
     {"api": "claude-haiku-5-5", "bedrock": "anthropic.claude-haiku-5-5", "vertex": "claude-haiku-5-5"}),
    (r"claude-3-haiku-20240307(?![\w@-])", "Haiku 3 ID (retired)",
     {"api": "claude-haiku-5-5", "bedrock": "anthropic.claude-haiku-5-5", "vertex": "claude-haiku-5-5"}),
]

# Bedrock 쪽 모델 ID 내부에 'anthropic.' 접두가 이미 붙은 경우 중복 치환 방지를 위해
# 가장 긴 패턴(anthropic.…)을 먼저 적용한다.
MODEL_ID_PATTERNS.sort(key=lambda p: -len(p[0]))

TOOL_PATTERNS = [
    # (정규식, 규칙ID, {platform: 치환}, 메시지)
    (r"computer_20250124", "H05", {"api": "computer_toolset_20260801", "vertex": "computer_toolset_20260801",
                                   "bedrock": "computer_20251124"},
     "computer_20250124 는 Haiku 5.5에서 400. API/Vertex는 toolset `computer_toolset_20260801`, Bedrock은 `computer_20251124`"),
    (r"computer-use-2025-01-24", "H05", {"api": None, "vertex": None, "bedrock": "computer-use-2025-11-24"},
     "베타 헤더 computer-use-2025-01-24 는 제거(API/Vertex, toolset은 헤더 불필요) 또는 computer-use-2025-11-24(Bedrock)"),
    (r"code_execution_20250522", "H08", {"api": "code_execution_20250825", "vertex": "code_execution_20250825",
                                         "bedrock": "code_execution_20250825"},
     "레거시 code_execution_20250522 → code_execution_20250825 이상"),
    (r"text_editor_2024\d{4}|text_editor_20250124|text_editor_20250429", "H08",
     {"api": "text_editor_20250728", "vertex": "text_editor_20250728", "bedrock": "text_editor_20250728"},
     "구 text_editor 버전 → text_editor_20250728 (undo_edit 없음)"),
]

RE_BUDGET = re.compile(r"""["']?budget_tokens["']?\s*[:=]""")
RE_THINK_ENABLED = re.compile(r"""["']?type["']?\s*[:=]\s*["']enabled["']""")
RE_SAMPLING = re.compile(r"""(?<![\w.])["']?(temperature|top_p|top_k)["']?\s*[:=]\s*([-+]?\d*\.?\d+)?""")
RE_ROLE = re.compile(r"""["']role["']\s*:\s*["'](assistant|user)["']""")
RE_ROLE_KW = re.compile(r"""\brole\s*=\s*["'](assistant|user)["']""")
RE_FIRST_BLOCK = re.compile(r"""\.content\[0\]|content\[0\]\.text|content\[0\]\["text"\]|\.content\?\.\[0\]""")
RE_MAX_TOKENS = re.compile(r"""["']?max_tokens["']?\s*[:=]\s*(\d+)""")
RE_STRICT = re.compile(r"""["']?strict["']?\s*[:=]\s*(true|True)""")
RE_OUTPUT_FORMAT = re.compile(r"""output_config[^\n]{0,80}format|["']format["']\s*:\s*\{[^\n]{0,40}json_schema""")
RE_BEDROCK = re.compile(r"""AnthropicBedrock|bedrock-runtime|invoke_model|anthropic\.claude-""")
RE_CREATE = re.compile(r"""messages\.create\(|messages\.stream\(|/v1/messages|invoke_model|InvokeModel|beta\.messages\.create\(""")
RE_REFUSAL = re.compile(r"""refusal""")
RE_FGTS = re.compile(r"""fine-grained-tool-streaming-2025-05-14""")
RE_TOOLSET = re.compile(r"""computer_toolset_20260801|browser_toolset_20260801""")
RE_HAIKU_ANY = re.compile(r"""haiku""", re.I)


@dataclass
class Finding:
    rule: str
    level: str
    file: str
    line: int
    snippet: str
    message: str
    fix: str | None = None  # 자동 치환이 가능한 경우 "old → new"


def detect_platform(text: str) -> str:
    if RE_BEDROCK.search(text):
        return "bedrock"
    if re.search(r"AnthropicVertex|aiplatform|@\d{8}", text):
        return "vertex"
    return "api"


def iter_files(paths):
    for p in paths:
        if os.path.isfile(p):
            yield p
            continue
        for root, dirs, files in os.walk(p):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                if os.path.splitext(f)[1] in EXTS or f.startswith(".env"):
                    yield os.path.join(root, f)


def lint_text(path: str, text: str, platform: str | None, scope: str = "haiku") -> tuple[list[Finding], str]:
    plat = platform or detect_platform(text)
    lines = text.splitlines()
    out: list[Finding] = []
    # scope=haiku: 모델 ID(H01)와 도구 버전(H05/H08)은 항상 보고, 호출 파라미터 규칙은
    # 파일 어딘가에 "haiku"가 있을 때만 본다(Sonnet/Opus 전용 파일의 temperature를 잡지 않기 위해).
    param_rules_on = scope == "all" or bool(RE_HAIKU_ANY.search(text))

    def add(rule, level, i, msg, fix=None):
        out.append(Finding(rule, level, path, i + 1, lines[i].strip()[:140], msg, fix))

    # H01 모델 ID
    for i, ln in enumerate(lines):
        for pat, desc, repl in MODEL_ID_PATTERNS:
            for m in re.finditer(pat, ln):
                new = repl[plat]
                add("H01", "error", i, f"{desc} → `{new}` (Haiku 5.5는 날짜 접미사·별칭 없음)", f"{m.group(0)} → {new}")
                break  # 한 줄에 같은 패턴 여러 번이면 한 번만

    if not param_rules_on:
        # 도구 버전만 더 보고 끝낸다
        for i, ln in enumerate(lines):
            for pat, rule, repl, msg in TOOL_PATTERNS:
                m = re.search(pat, ln)
                if m:
                    new = repl[plat]
                    add(rule, "error", i, msg, f"{m.group(0)} → {new}" if new else f"{m.group(0)} → (제거)")
        return out, plat

    # H02 thinking enabled / budget_tokens
    for i, ln in enumerate(lines):
        if RE_BUDGET.search(ln):
            add("H02", "error", i, "`budget_tokens`(수동 확장 사고)는 400. `thinking: {\"type\": \"adaptive\"}` + `output_config.effort`로")
        elif RE_THINK_ENABLED.search(ln) and ("thinking" in ln or any("thinking" in lines[j] for j in range(max(0, i - 2), i))):
            add("H02", "error", i, "`thinking.type: enabled`는 400. `adaptive`로 바꾸고 effort(low/medium/high)로 조절")

    # H03 샘플링 파라미터
    for i, ln in enumerate(lines):
        for m in RE_SAMPLING.finditer(ln):
            name, val = m.group(1), m.group(2)
            if name == "temperature" and val is not None and float(val) == 1.0:
                add("H03", "warn", i, "`temperature: 1`은 허용되지만 `top_p`와 함께 보내면 400. 제거 권장")
            elif name == "top_p" and val is not None and float(val) == 0.99:
                add("H03", "warn", i, "`top_p: 0.99`(기본값)만 허용. `temperature`와 함께면 400. 제거 권장")
            else:
                add("H03", "error", i, f"`{name}`은 Haiku 5.5에서 400. 제거하고 프롬프트로 유도")

    # H04 assistant prefill (마지막 메시지가 assistant인지 휴리스틱)
    for i, ln in enumerate(lines):
        m = RE_ROLE.search(ln) or RE_ROLE_KW.search(ln)
        if not m or m.group(1) != "assistant":
            continue
        # 앞으로 최대 12줄: 다음 role이 나오기 전에 messages 배열이 닫히면 prefill 의심
        suspicious = False
        depth_hint = 0
        for j in range(i + 1, min(len(lines), i + 13)):
            nxt = lines[j]
            if RE_ROLE.search(nxt) or RE_ROLE_KW.search(nxt):
                break
            if re.search(r"\]\s*,?\s*$|\]\s*\)|\],", nxt) or re.search(r"^\s*\]", nxt):
                suspicious = True
                break
        # 같은 줄에서 바로 닫히는 경우: {"role":"assistant",...}]
        if re.search(r"""role["']?\s*[:=]\s*["']assistant["'][^\]]*\]""", ln):
            suspicious = True
        if suspicious:
            add("H04", "warn", i, "messages가 assistant 턴으로 끝나면(prefill) 400. user 턴으로 끝내고 구조화 출력·시스템 프롬프트로 대체")

    # H05/H08 도구 버전
    for i, ln in enumerate(lines):
        for pat, rule, repl, msg in TOOL_PATTERNS:
            m = re.search(pat, ln)
            if m:
                new = repl[plat]
                fix = f"{m.group(0)} → {new}" if new else f"{m.group(0)} → (제거)"
                add(rule, "error", i, msg, fix)
        if RE_FGTS.search(ln) and (RE_TOOLSET.search(text) or (plat != "bedrock" and "computer_20250124" in text)):
            add("H05", "error", i, "toolset(computer_20250124를 옮기면 toolset)과 `fine-grained-tool-streaming-2025-05-14` 헤더를 같이 보내면 400. 헤더 제거",
                "fine-grained-tool-streaming-2025-05-14 → (제거)")

    # H06 Bedrock 구조화 출력
    if plat == "bedrock":
        for i, ln in enumerate(lines):
            if RE_STRICT.search(ln) or RE_OUTPUT_FORMAT.search(ln):
                add("H06", "error", i, "Bedrock의 Haiku 5.5는 구조화 출력 미지원. 프롬프트로 형식 설명 + strict 없는 tool + 코드 검증")

    # H07 첫 블록 가정
    for i, ln in enumerate(lines):
        if RE_FIRST_BLOCK.search(ln):
            add("H07", "warn", i, "응답이 `thinking` 블록으로 시작할 수 있음. `content[0]` 대신 `type == \"text\"`로 골라야")

    # H09 작은 max_tokens
    for i, ln in enumerate(lines):
        m = RE_MAX_TOKENS.search(ln)
        if m and int(m.group(1)) < 1024:
            add("H09", "warn", i, f"max_tokens={m.group(1)}: thinking 토큰이 max_tokens에 포함되고 토큰 수가 약 30% 늘어 잘릴 수 있음. 올리거나 effort low")

    # H10 refusal 처리 (파일 단위)
    if RE_CREATE.search(text) and not RE_REFUSAL.search(text):
        first = next((i for i, ln in enumerate(lines) if RE_CREATE.search(ln)), 0)
        add("H10", "info", first, "`stop_reason: \"refusal\"` 처리가 없음. Haiku 5.5는 안전 분류기로 거절할 수 있고 서버 폴백이 없다")

    return out, plat


def apply_fixes(text: str, findings: list[Finding]) -> str:
    """H01/H05/H08의 `old → new` 치환만 적용한다. 제거(→ (제거))는 손으로."""
    new = text
    for f in findings:
        if not f.fix or "(제거)" in f.fix:
            continue
        old, repl = [s.strip() for s in f.fix.split("→", 1)]
        new = new.replace(old, repl)
    return new


def render_text(findings: list[Finding], plat_by_file: dict[str, str], min_level: str) -> str:
    lim = LEVELS[min_level]
    rows = [f for f in findings if LEVELS[f.level] <= lim]
    if not rows:
        return "✓ Haiku 4.5 → 5.5 호환성 문제를 찾지 못했다.\n"
    out = []
    by_file: dict[str, list[Finding]] = {}
    for f in rows:
        by_file.setdefault(f.file, []).append(f)
    for file, fs in by_file.items():
        out.append(f"\n{file}  (platform: {plat_by_file.get(file, '?')})")
        for f in sorted(fs, key=lambda x: (x.line, x.rule)):
            out.append(f"  {f.line:>5}  {f.rule}  {LEVEL_LABEL[f.level]}  {f.message}")
            out.append(f"         │ {f.snippet}")
            if f.fix:
                out.append(f"         └ fix: {f.fix}")
    counts = {k: sum(1 for f in rows if f.level == k) for k in LEVELS}
    out.append(f"\n합계: error {counts['error']} · warn {counts['warn']} · info {counts['info']}  (파일 {len(by_file)}개)")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--platform", choices=["api", "bedrock", "vertex"], help="미지정이면 파일마다 자동 감지")
    ap.add_argument("--json", action="store_true", help="JSON으로 출력")
    ap.add_argument("--fix", action="store_true", help="H01/H05/H08 문자열 치환을 파일에 적용")
    ap.add_argument("--dry-run", action="store_true", help="--fix와 함께: 파일을 바꾸지 않고 diff만 출력")
    ap.add_argument("--min-level", choices=list(LEVELS), default="info")
    ap.add_argument("--scope", choices=["haiku", "all"], default="haiku",
                    help="haiku(기본): 파라미터 규칙은 'haiku'가 언급된 파일만. all: 모든 파일")
    a = ap.parse_args(argv)

    all_f: list[Finding] = []
    plat_by_file: dict[str, str] = {}
    diffs = []
    for path in iter_files(a.paths):
        try:
            if os.path.getsize(path) > MAX_BYTES:
                continue
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        fs, plat = lint_text(path, text, a.platform, a.scope)
        if not fs:
            continue
        plat_by_file[path] = plat
        all_f.extend(fs)
        if a.fix:
            new = apply_fixes(text, fs)
            if new != text:
                if a.dry_run:
                    diffs.append("".join(difflib.unified_diff(
                        text.splitlines(True), new.splitlines(True), f"a/{path}", f"b/{path}")))
                else:
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(new)
                    diffs.append(f"fixed: {path}")

    if a.json:
        print(json.dumps({"findings": [asdict(f) for f in all_f],
                          "platform": plat_by_file,
                          "summary": {k: sum(1 for f in all_f if f.level == k) for k in LEVELS}},
                         ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(render_text(all_f, plat_by_file, a.min_level))
        for d in diffs:
            print(d)
    return 1 if any(f.level == "error" for f in all_f) else 0


if __name__ == "__main__":
    sys.exit(main())

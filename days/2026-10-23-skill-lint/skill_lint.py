#!/usr/bin/env python3
"""skill-lint — Agent Skills(SKILL.md) 규격·이식성·위험 패턴 점검 린터.

표준 라이브러리만 쓴다. API 키·네트워크·모델 불필요.

    python3 skill_lint.py <path>... [--json] [--min-level error|warn|info]
                                    [--ignore F02,X05] [--no-scripts]

<path>는 스킬 폴더(SKILL.md가 있는 폴더) 또는 그 상위 폴더(안의 SKILL.md를 전부 찾는다).
레벨: error = 규격 위반이거나 스킬이 로드·업로드되지 않거나 실행하면 위험이 확정 /
      warn = 동작이 어긋나거나 사람이 봐야 함 / info = 이식성·품질 제안.
종료 코드: 0 = error 없음, 1 = error 있음, 2 = 사용 오류(없는 경로·SKILL.md 없음).
규칙 출처: https://agentskills.io/specification , https://code.claude.com/docs/en/skills
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from dataclasses import dataclass, asdict

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "vendor"}
SCRIPT_EXTS = {".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".cjs", ".ts", ".rb", ".ps1", ".pl"}
MAX_BYTES = 1_000_000

PORTABLE_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
CLAUDE_CODE_KEYS = {"when_to_use", "argument-hint", "arguments", "disable-model-invocation",
                    "user-invocable", "disallowed-tools", "model", "effort", "context", "agent",
                    "background", "hooks", "paths", "shell"}
COMMON_EXTRA_KEYS = {"version", "author", "tags", "category", "categories", "keywords", "homepage", "repository", "triggers"}
BOOL_KEYS = {"disable-model-invocation", "user-invocable", "background"}
STRICT_BOOL = {"true", "false"}
LOOSE_BOOL = {"yes", "no", "on", "off", "1", "0"}

LEVELS = {"error": 0, "warn": 1, "info": 2}
LEVEL_LABEL = {"error": "ERROR", "warn": "WARN ", "info": "INFO "}

RULES = {
    "F01": "frontmatter 없음·닫히지 않음 (스킬이 필드 없이 로드됨)",
    "F02": "YAML 파싱 오류 (따옴표 없는 값 안의 ': ' 등 → 필드 전부 무시)",
    "F03": "따옴표 없는 값 안의 ' #' (그 뒤가 주석으로 잘림)",
    "F04": "SKILL.md 파일명 대소문자 (skill.md 등)",
    "N01": "name 없음 (규격은 필수, Claude Code는 폴더명으로 대체)",
    "N02": "name 규칙 위반 (소문자·숫자·하이픈, 64자, 양끝·연속 하이픈 금지)",
    "N03": "name이 폴더 이름과 다름",
    "D01": "description 없음·비어 있음",
    "D02": "description 1024자 초과 (규격 위반)",
    "D03": "description + when_to_use 1536자 초과 (목록에서 잘림)",
    "D04": "description이 너무 짧거나 '언제 쓰는지'가 없음",
    "C01": "compatibility가 비었거나 500자 초과",
    "M01": "metadata가 문자열→문자열 맵이 아님",
    "K01": "알 수 없는 frontmatter 키 (Claude Code는 조용히 무시 — 오타?)",
    "K02": "Claude Code 전용 키 (claude.ai 업로드·Skills API·package_skill.py에서는 하드 에러)",
    "B01": "본문 500줄 초과 (references/로 분리 권장)",
    "B02": "본문이 비어 있음",
    "R01": "본문이 가리키는 파일이 스킬 폴더에 없음",
    "R02": "참조 파일이 또 다른 참조를 가리킴 (한 단계 깊이 권장)",
    "T01": "allowed-tools가 너무 넓음 (Bash 전체 등)",
    "T02": "불리언 키에 불리언이 아닌 값 / yes·no는 v2.1.218 미만에서 안 먹음",
    "T03": "스킬이 hooks를 등록함 (호출 뒤 세션 끝까지 유지)",
    "X01": "내려받아 바로 셸·인터프리터로 실행 (curl … | sh)",
    "X02": "가드 없는 rm -rf (변수·$HOME·~·/)",
    "X03": "비밀·자격 증명 파일을 읽음",
    "X04": "비밀을 읽는 파일이 외부로도 보냄 (유출 조합)",
    "X05": "네트워크를 쓰는데 compatibility에 적지 않음",
    "X06": "sudo·chmod 777·eval·base64 해독 실행",
    "X07": "보이지 않는 문자 (zero-width·bidi 제어)",
    "X08": "모델에게 사용자 몰래 하라는 지시처럼 읽히는 문구",
    "X09": "셸 프로필·설정·크론·SSH 키를 바꿈 (설치 뒤에도 남는 변경)",
}


@dataclass
class Finding:
    skill: str
    file: str
    line: int
    rule: str
    level: str
    message: str
    snippet: str = ""


# ---------------------------------------------------------------- frontmatter

class FMError(Exception):
    def __init__(self, line: int, msg: str):
        super().__init__(msg)
        self.line, self.msg = line, msg


class NonStr:
    """따옴표 없는 숫자·불리언·null 값 (YAML이 문자열로 읽지 않는다)."""
    def __init__(self, raw: str):
        self.raw = raw


def _unquote(v: str):
    """따옴표 값을 벗긴다. 따옴표 없는 값은 (값, False)."""
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1], True
    return v, False


def parse_frontmatter(lines: list[str]):
    """줄 목록(--- 사이)에서 최상위 키를 뽑는다. 반환: {키: (값, 줄번호, 따옴표여부)}.

    값은 str | list[str] | dict[str,str] | None. 진짜 YAML 파서가 아니라 SKILL.md에서 흔한 모양만 다룬다.
    첫 줄이 line_no=2 (SKILL.md의 2번째 줄)가 되도록 호출자가 offset을 준다.
    """
    out: dict = {}
    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        ln = i + 2
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise FMError(ln, "들여쓰기에 탭이 있다")
        if raw[0] in " \t":
            raise FMError(ln, "최상위 키 없이 들여쓴 줄")
        m = re.match(r"^([A-Za-z_][\w.-]*)\s*:(?:\s+(.*))?$", raw.rstrip())
        if not m:
            raise FMError(ln, "'키: 값' 모양이 아닌 줄")
        key, rest = m.group(1), (m.group(2) or "")
        # 이어지는 들여쓴 줄 모으기
        j = i + 1
        block: list[tuple[int, str]] = []
        while j < n and (not lines[j].strip() or lines[j][0] in " \t" or lines[j].startswith("- ")):
            if "\t" in lines[j][: len(lines[j]) - len(lines[j].lstrip())]:
                raise FMError(j + 2, "들여쓰기에 탭이 있다")
            block.append((j + 2, lines[j]))
            j += 1
        while block and not block[-1][1].strip():
            block.pop()
        rest_s = rest.strip()
        if rest_s and rest_s[0] in "|>":
            val = "\n".join(b[1].strip() for b in block)
            out[key] = (val, ln, True)
        elif not rest_s:
            items = [(l, t) for l, t in block if t.strip() and not t.lstrip().startswith("#")]
            if not items:
                out[key] = (None, ln, False)
            elif not re.match(r"^\s+[\w.-]+\s*:(\s|$)", items[0][1]) and not items[0][1].lstrip().startswith("- "):
                first = items[0][1].strip()
                joined = " ".join(t.strip() for _, t in items)
                if first[0] in "\"'":
                    if len(joined) < 2 or joined[-1] != first[0]:
                        raise FMError(ln, f"{first[0]} 따옴표가 닫히지 않았다")
                    out[key] = (joined[1:-1], ln, True)
                else:
                    for l, t in items:
                        if re.search(r":(\s|$)", t.strip()):
                            raise FMError(l, "따옴표 없는 값 안에 ': '가 있다")
                    out[key] = (joined, ln, False)
            elif all(t.lstrip().startswith("- ") for _, t in items):
                out[key] = ([_unquote(t.lstrip()[2:])[0] for _, t in items], ln, True)
            else:
                d: dict = {}
                for l, t in items:
                    mm = re.match(r"^\s+([^:#\s][^:]*?)\s*:\s*(.*)$", t)
                    if mm:
                        v2, quoted = _unquote(mm.group(2)) if mm.group(2).strip() else (None, False)
                        if not quoted and v2 is not None and re.fullmatch(r"-?\d+(\.\d+)?|true|false|yes|no|on|off|null|~", v2, re.I):
                            v2 = NonStr(v2)
                        d[mm.group(1)] = v2
                    else:
                        d[f"__raw{l}"] = t.strip()
                out[key] = (d, ln, True)
        else:
            if rest_s[0] in "[{" :
                out[key] = (_flow(rest_s, ln), ln, True)
            elif rest_s[0] in "\"'":
                q = rest_s[0]
                if rest_s.count(q) < 2 or not rest_s.rstrip().endswith(q):
                    if not block:
                        raise FMError(ln, f"{q} 따옴표가 닫히지 않았다")
                    joined = rest_s + " " + " ".join(t.strip() for _, t in block)
                    if not joined.rstrip().endswith(q):
                        raise FMError(ln, f"{q} 따옴표가 닫히지 않았다")
                    out[key] = (_unquote(joined)[0], ln, True)
                else:
                    out[key] = (_unquote(rest_s)[0], ln, True)
            else:
                if rest_s[0] in "*&!%@`":
                    raise FMError(ln, f"따옴표 없는 값이 '{rest_s[0]}'로 시작한다 (YAML 예약 문자)")
                text = rest_s
                for l, t in block:
                    if t.strip():
                        text += " " + t.strip()
                        if re.search(r":(\s|$)", t.strip()):
                            raise FMError(l, "따옴표 없는 값 안에 ': '가 있다")
                if re.search(r":(\s|$)", rest_s):
                    raise FMError(ln, "따옴표 없는 값 안에 ': '가 있다 (description을 따옴표로 감싸거나 | 블록으로)")
                if re.search(r"\s#", rest_s):
                    out.setdefault("__hash__", []).append((key, ln))
                    text = re.split(r"\s#", text, 1)[0].strip()
                out[key] = (text, ln, False)
        i = j
    return out


def _flow(s: str, ln: int):
    s = s.strip()
    if s.startswith("["):
        if not s.endswith("]"):
            raise FMError(ln, "[ ] 목록이 닫히지 않았다")
        inner = s[1:-1].strip()
        return [_unquote(x)[0] for x in inner.split(",") if x.strip()] if inner else []
    if not s.endswith("}"):
        raise FMError(ln, "{ } 맵이 닫히지 않았다")
    d = {}
    for part in s[1:-1].split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            d[k.strip()] = _unquote(v)[0]
    return d


# ---------------------------------------------------------------- 점검

NET_RE = re.compile(r"\b(curl|wget|nc|ncat|scp|rsync|ssh|requests\.|urllib\.request|urlopen|httpx|fetch\(|axios|http\.client|Invoke-WebRequest|git\s+(clone|pull|fetch)|pip\s+install|npm\s+(i|install)\b)")
UPLOAD_RE = re.compile(r"(curl[^\n|]*(?:-d\s*@|--data(?:-binary|-raw|-urlencode)?\s*@|-F\s|--upload-file|-T\s)|\bnc\s|\bncat\s|requests\.(post|put)\(|urlopen\(|\bscp\s|\bwget[^\n]*--post-file|Invoke-RestMethod[^\n]*-Method\s+Post)")
SECRET_RE = re.compile(r"(~|\$HOME|\$\{HOME\}|/home/\w+|/Users/\w+)?/?\.(ssh|aws|gnupg|kube|docker|netrc|npmrc|pypirc|git-credentials)\b|id_(rsa|ed25519|ecdsa)\b|credentials\.json|(?<![\w.])\.env\b(?!\.example|\.sample)|keychain|security\s+find-(generic|internet)-password|/etc/shadow|gh\s+auth\s+token|\bprintenv\b|\benv\s*\|")
PIPE_SH_RE = re.compile(r"(curl|wget)\b[^\n|;]*\|\s*(sudo\s+)?(ba|z|da)?sh\b|(curl|wget)\b[^\n|;]*\|\s*(sudo\s+)?(python3?|node|ruby|perl)\b|\b(ba)?sh\s+<\(\s*(curl|wget)|eval\s+[\"']?\$\(\s*(curl|wget)|iwr\b[^\n|]*\|\s*iex|Invoke-WebRequest[^\n|]*\|\s*(iex|Invoke-Expression)")
RM_RE = re.compile(r"(?:^|[;&|(`]|\$\(|\b(?:then|do|else|sudo|xargs|exec)\s)\s*rm\s+(-[a-zA-Z]*[rR][a-zA-Z]*f?[a-zA-Z]*|-[a-zA-Z]*f[a-zA-Z]*[rR][a-zA-Z]*|--recursive)\b([^\n;&|]*)")
RM_PY = re.compile(r"shutil\.rmtree\(\s*(os\.path\.expanduser|Path\.home|os\.environ)")
SUDO_RE = re.compile(r"(^|[\s;&|(])sudo\s|chmod\s+(-R\s+)?(0?777|a\+rwx)\b|\beval\s+[\"'$]|base64\s+(-d|--decode)[^\n]*\|\s*(ba|z)?sh|\bexec\(\s*base64|\bexec\(\s*compile\(")
PERSIST_RE = re.compile(r"(>>?|tee\s+-a|sed\s+-i[^\n]*)\s*[\"']?(~|\$HOME|\$\{HOME\})?/?\.?(bashrc|zshrc|bash_profile|zprofile|profile|zshenv)\b|(>>?|tee)\s*[\"']?(~|\$HOME)/\.ssh/authorized_keys|crontab\s+(-|\S+\s*<)|\(crontab\s+-l|git\s+config\s+--global|(>>?|tee)\s*[\"']?(~|\$HOME)/\.claude/settings(\.local)?\.json|launchctl\s+load|systemctl\s+(--user\s+)?enable")
INJECT_RE = re.compile(r"(ignore|disregard)\s+(all\s+)?(previous|prior|above)\s+(instructions|rules)|(do\s+not|don't|never)\s+(tell|inform|notify)\s+the\s+user\b(?!\s+(that|unless|whether|if|until)\b)|without\s+(telling|informing|notifying|asking)\s+the\s+user|never\s+(reveal|disclose)\s+(this|these)\s+instructions|사용자에게\s*(알리지|말하지)\s*(말|마)|사용자 몰래|묻지\s*(말고|않고)\s*(바로\s*)?(실행|삭제|전송)", re.I)
HIDDEN_RE = re.compile("[​‌‍⁠﻿‪-‮⁦-⁩]")
NETWORK_DECL_RE = re.compile(r"network|internet|online|http|api|네트워크|인터넷|온라인|접속", re.I)
FENCE_RE = re.compile(r"^\s*(```|~~~)")


READ_VERB_RE = re.compile(r"\b(cat|less|more|head|tail|grep|rg|source|cp|mv|tar|zip|scp|rsync|open|read_text|readFile\w*|load_dotenv|dotenv|base64|xxd|strings)\b|(?<![<>=!])<\s*[\"'~$./]")
COMPARE_RE = re.compile(r"==|!=|=~|\bcase\b|pattern:|\bmatch(es)?\b", re.I)


def reads_secret_line(line: str) -> bool:
    m = SECRET_RE.search(line)
    if not m:
        return False
    if COMPARE_RE.search(line):
        return False
    weak = re.fullmatch(r"\.env", m.group(0).strip("/"))
    return bool(READ_VERB_RE.search(line)) if weak or m.group(0) in ("printenv", "env |") else True


def is_comment(line: str) -> bool:
    s = line.strip()
    return s.startswith("#") or s.startswith("//") or s.startswith("--")


def read_text(path: str):
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return None
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


class Skill:
    def __init__(self, md_path: str):
        self.md_path = md_path
        self.dir = os.path.dirname(os.path.abspath(md_path))
        self.dirname = os.path.basename(self.dir)
        self.rel = os.path.relpath(self.dir)
        self.findings: list[Finding] = []

    def add(self, file: str, line: int, rule: str, level: str, msg: str, snippet: str = ""):
        self.findings.append(Finding(self.rel, os.path.relpath(file, self.dir) if os.path.isabs(file) else file,
                                     line, rule, level, msg, snippet.strip()[:160]))


def check_skill(sk: Skill, scripts: bool = True):
    md = sk.md_path
    base = os.path.basename(md)
    if base != "SKILL.md":
        sk.add(base, 1, "F04", "error", f"파일 이름이 {base} — 규격은 정확히 SKILL.md")
    text = read_text(md)
    if text is None:
        sk.add(base, 1, "F01", "error", "읽을 수 없거나 1MB 초과")
        return
    lines = text.split("\n")
    fm_lines: list[str] = []
    body_start = 0
    fm: dict = {}
    if lines and lines[0].strip() == "---":
        end = next((k for k in range(1, len(lines)) if lines[k].strip() == "---"), None)
        if end is None:
            sk.add(base, 1, "F01", "error", "frontmatter의 닫는 --- 가 없다 — 스킬이 필드 없이 로드된다")
        else:
            fm_lines = lines[1:end]
            body_start = end + 1
            try:
                fm = parse_frontmatter(fm_lines)
            except FMError as e:
                sk.add(base, e.line, "F02", "error", f"YAML 파싱 오류: {e.msg} — Claude Code는 필드를 전부 무시하고 로드한다",
                       lines[e.line - 1] if e.line - 1 < len(lines) else "")
    else:
        sk.add(base, 1, "F01", "error", "첫 줄이 --- 가 아니다 — frontmatter 없음(name·description 필수 위반)")
    body_lines = lines[body_start:]
    body = "\n".join(body_lines)

    for key, ln in fm.pop("__hash__", []):
        sk.add(base, ln, "F03", "warn", f"'{key}' 값 안의 ' #' 뒤는 YAML 주석이라 잘린다 (따옴표로 감싸기)", lines[ln - 1])

    def val(k):
        return fm[k][0] if k in fm else None

    def line_of(k):
        return fm[k][1] if k in fm else 1

    # name
    parse_ok = bool(fm) or not fm_lines
    name = val("name")
    if "name" not in fm:
        if fm_lines and parse_ok:
            sk.add(base, 1, "N01", "error", "name이 없다 — 규격은 필수 (Claude Code는 폴더 이름 '%s'을 쓴다)" % sk.dirname)
    elif not isinstance(name, str) or not name:
        sk.add(base, line_of("name"), "N01", "error", "name이 비어 있다")
    else:
        probs = []
        if len(name) > 64:
            probs.append(f"{len(name)}자 (최대 64)")
        if not re.fullmatch(r"[a-z0-9-]+", name):
            bad = sorted(set(re.sub(r"[a-z0-9-]", "", name)))
            probs.append("허용되지 않는 문자 " + "".join(bad))
        if name.startswith("-") or name.endswith("-"):
            probs.append("하이픈으로 시작·끝")
        if "--" in name:
            probs.append("연속 하이픈")
        if probs:
            sk.add(base, line_of("name"), "N02", "error", f"name '{name}': " + ", ".join(probs), lines[line_of("name") - 1])
        if name != sk.dirname:
            sk.add(base, line_of("name"), "N03", "error", f"name '{name}' ≠ 폴더 이름 '{sk.dirname}' — 규격은 일치를 요구한다", lines[line_of("name") - 1])

    # description
    desc = val("description")
    wtu = val("when_to_use")
    if fm_lines and parse_ok:
        if not isinstance(desc, str) or not desc.strip():
            sk.add(base, line_of("description"), "D01", "error",
                   "description이 없거나 비어 있다 — 규격 필수, Claude Code는 본문 첫 줄로 대체해 스킬을 고르는 근거가 약해진다")
        else:
            if len(desc) > 1024:
                sk.add(base, line_of("description"), "D02", "error", f"description {len(desc)}자 (규격 최대 1024)")
            combined = len(desc) + (len(wtu) if isinstance(wtu, str) else 0)
            if combined > 1536:
                cut = (desc + " " + (wtu if isinstance(wtu, str) else ""))[1500:1536]
                sk.add(base, line_of("description"), "D03", "warn",
                       f"description+when_to_use {combined}자 — 1536자 뒤는 목록에서 잘린다 (핵심 사용처를 앞에)", "…" + cut)
            if len(desc.strip()) < 30 or not re.search(r"\b(use|when|if|whenever|for)\b|때|경우|사용|호출|요청", desc, re.I):
                sk.add(base, line_of("description"), "D04", "info",
                       "description이 짧거나 '무엇을 하고 언제 쓰는지'가 안 보인다 — 모델이 이 스킬을 고르는 유일한 단서", desc[:100])

    # compatibility / metadata
    if "compatibility" in fm:
        c = val("compatibility")
        if not isinstance(c, str) or not c.strip() or len(c) > 500:
            sk.add(base, line_of("compatibility"), "C01", "error", "compatibility는 1~500자 문자열이어야 한다")
    if "metadata" in fm:
        m = val("metadata")
        bad = [k for k, v in m.items() if not isinstance(v, str) or k.startswith("__raw")] if isinstance(m, dict) else None
        if bad is None or bad:
            which = f" ('{bad[0]}')" if bad else ""
            sk.add(base, line_of("metadata"), "M01", "error",
                   f"metadata는 문자열→문자열 맵이어야 한다{which} (숫자·불리언은 따옴표로: version: \"1.0\")", lines[line_of("metadata") - 1])

    # 키
    for key in fm:
        if key in PORTABLE_KEYS:
            continue
        if key in CLAUDE_CODE_KEYS:
            sk.add(base, line_of(key), "K02", "info", f"'{key}'는 Claude Code 전용 — 다른 에이전트는 무시하고, claude.ai 업로드·Skills API에서는 하드 에러")
            continue
        if key in COMMON_EXTRA_KEYS:
            sk.add(base, line_of(key), "K01", "info", f"'{key}'는 스킬 규격에 없는 키 — Claude Code는 무시한다. 'metadata:' 아래로 옮기면 규격에 맞는다", lines[line_of(key) - 1])
            continue
        if key == "tools":
            sk.add(base, line_of(key), "K01", "warn", "'tools'는 서브에이전트 정의의 키다 — 스킬에서는 무시된다. 스킬은 'allowed-tools'", lines[line_of(key) - 1])
            continue
        guess = difflib.get_close_matches(key.replace("_", "-"), sorted(PORTABLE_KEYS | CLAUDE_CODE_KEYS), n=1, cutoff=0.75)
        hint = f" — '{guess[0]}'의 오타?" if guess else ""
        sk.add(base, line_of(key), "K01", "warn", f"알 수 없는 키 '{key}'{hint} Claude Code는 에러 없이 무시한다", lines[line_of(key) - 1])

    # 불리언
    for key in BOOL_KEYS & set(fm):
        v = val(key)
        if not isinstance(v, str):
            sk.add(base, line_of(key), "T02", "error", f"'{key}'는 true/false여야 한다", lines[line_of(key) - 1])
        elif v.lower() in LOOSE_BOOL:
            sk.add(base, line_of(key), "T02", "info", f"'{key}: {v}' — yes/no/on/off/1/0은 v2.1.218 이상에서만 인식, 그 미만은 true/false만", lines[line_of(key) - 1])
        elif v.lower() not in STRICT_BOOL:
            sk.add(base, line_of(key), "T02", "error", f"'{key}: {v}'은 불리언이 아니다", lines[line_of(key) - 1])

    # allowed-tools
    for key in ("allowed-tools",):
        if key in fm:
            v = val(key)
            toks = v if isinstance(v, list) else re.findall(r"[\w:.-]+(?:\([^)]*\))?|\*", v) if isinstance(v, str) else []
            for t in toks:
                if t in ("Bash", "Bash(*)", "Bash(*:*)", "Bash(**)", "*") or re.fullmatch(r"Bash\(\s*(sudo|sh|bash|zsh|eval|curl|wget|python3?|node|ruby|perl|env|xargs)\s*[: ]?\s*\*{0,2}\s*\)", t):
                    sk.add(base, line_of(key), "T01", "warn",
                           f"'{t}'는 범위가 넓다 — 스킬이 호출된 턴에 묻지 않고 허용된다(인터프리터·셸 와일드카드는 사실상 임의 실행). 'Bash(git status:*)'처럼 좁히기", lines[line_of(key) - 1])
    if "hooks" in fm:
        sk.add(base, line_of("hooks"), "T03", "warn", "스킬이 hooks를 등록한다 — 호출 뒤 세션 끝까지 남는다. 어떤 명령을 거는지 읽어 볼 것", lines[line_of("hooks")-1])

    # 본문
    nbody = len(body_lines)
    if nbody > 500:
        sk.add(base, body_start + 501, "B01", "warn", f"본문 {nbody}줄 — 500줄 이하 권장, 상세는 references/로")
    if not body.strip() and fm_lines:
        sk.add(base, body_start + 1, "B02", "warn", "frontmatter 뒤 본문이 비어 있다")

    check_refs(sk, lines, body_start)
    check_invisible_and_inject(sk, md, lines, body_start)
    # 스크립트·코드 블록 위험 패턴
    scanned: dict[str, list[tuple[int, str]]] = {}
    fenced = []
    infence = False
    for k in range(body_start, len(lines)):
        ln = lines[k]
        if FENCE_RE.match(ln):
            infence = not infence
            continue
        if infence or ln.lstrip().startswith("!`") or re.search(r"!`[^`]+`", ln):
            fenced.append((k + 1, ln))
    scanned[base] = fenced
    if scripts:
        for root, dirs, files in os.walk(sk.dir):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in sorted(files):
                p = os.path.join(root, f)
                if os.path.abspath(p) == os.path.abspath(md):
                    continue
                ext = os.path.splitext(f)[1].lower()
                t = read_text(p)
                if t is None:
                    continue
                if ext in SCRIPT_EXTS or t.startswith("#!"):
                    rel = os.path.relpath(p, sk.dir)
                    scanned[rel] = [(i + 1, l) for i, l in enumerate(t.split("\n"))]
                    check_invisible_and_inject(sk, p, t.split("\n"), 0, rel)
    check_risks(sk, scanned, fm)


def check_refs(sk: Skill, lines: list[str], body_start: int):
    seen = set()
    refs = []
    infence = False
    for k in range(body_start, len(lines)):
        ln = lines[k]
        if FENCE_RE.match(ln):
            infence = not infence
        if re.search(r"\be\.g\.|\bexamples?\b(?![.\w])|\bfor example\b|예시|예:|예를 들", ln, re.I):
            continue  # 예시 파일 이름을 나열하는 줄
        for m in re.finditer(r"\]\(([^)\s]+)\)", ln):
            refs.append((k + 1, m.group(1), "error"))
        for m in re.finditer(r"(?<![\w/.-])((?:\./)?(?:scripts|references|assets)/[\w./-]+[\w])", ln):
            runs = re.search(r"\b(python3?|bash|sh|node|ruby|source|run|execute|실행)\s+[`\"']?$|(^|\s)\./$", ln[: m.start(1)] + ("./" if m.group(1).startswith("./") else ""), re.I)
            refs.append((k + 1, m.group(1), "error" if runs else "warn"))
    for ln, r, lvl in refs:
        r = r.split("#")[0].split("?")[0]
        if not r or re.match(r"^[a-z]+:", r) or r.startswith(("/", "~", "#")) or re.search(r"[<>{}$*]", r) or not re.search(r"[/.]", r):
            continue
        if (ln, r) in seen:
            continue
        seen.add((ln, r))
        if not os.path.exists(os.path.join(sk.dir, r)):
            sk.add(os.path.basename(sk.md_path), ln, "R01", lvl,
                   f"'{r}'가 스킬 폴더에 없다" + ("" if lvl == "error" else " (본문에서 언급만 됨 — 예시 이름이면 무시)"), lines[ln - 1])
        elif r.lower().endswith(".md") and os.path.isfile(os.path.join(sk.dir, r)):
            sub = read_text(os.path.join(sk.dir, r)) or ""
            for m in re.finditer(r"\]\(((?:\./)?(?:references|scripts|assets)/[^)\s#]+\.md)\)", sub):
                sk.add(r, 1, "R02", "info", f"'{r}'가 다시 '{m.group(1)}'를 가리킨다 — SKILL.md에서 한 단계 깊이로 두는 것이 권장")
                break


def check_invisible_and_inject(sk: Skill, path: str, lines: list[str], start: int, label: str | None = None):
    label = label or os.path.basename(path)
    for k in range(start, len(lines)):
        ln = lines[k]
        m = HIDDEN_RE.search(ln)
        if m:
            sk.add(label, k + 1, "X07", "error", "보이지 않는 문자 U+%04X — 눈에 안 보이는 지시를 숨길 수 있다" % ord(m.group()), repr(ln[:80]))
        mi = INJECT_RE.search(ln) if label.endswith(".md") else None
        if mi and not (mi.start() > 0 and ln[mi.start() - 1] in "\"'`“‘"):
            sk.add(label, k + 1, "X08", "warn", "사용자에게 숨기거나 이전 지시를 무시하라는 문구", ln)


def check_risks(sk: Skill, scanned: dict[str, list[tuple[int, str]]], fm: dict):
    compat = fm.get("compatibility", (None,))[0]
    declared_net = isinstance(compat, str) and bool(NETWORK_DECL_RE.search(compat))
    for file, rows in scanned.items():
        is_md = file.endswith(".md")
        reads_secret = [(n, l) for n, l in rows if not is_comment(l) and reads_secret_line(l)]
        uploads = [(n, l) for n, l in rows if not is_comment(l) and UPLOAD_RE.search(l)]
        net_rows = [(n, l) for n, l in rows if not is_comment(l) and NET_RE.search(l)]
        for n, l in rows:
            if is_comment(l):
                continue
            if PIPE_SH_RE.search(l):
                sk.add(file, n, "X01", "error", "내려받은 내용을 바로 실행한다 — 받은 뒤 내용을 보고 실행하거나 해시를 고정", l)
            m = RM_RE.search(l)
            if m:
                target = m.group(2).strip().strip("\"'")
                first = target.split()[0].replace('"', "").replace("'", "") if target.split() else ""
                guarded = re.search(r"\$\{\w+:\?|\$\{\w+:-[^}]+\}", first) or (":?" in first)
                risky = (first in ("/", "~", "$HOME", "${HOME}", "*", "/*", "~/", "$HOME/", ".", "..") or
                         re.fullmatch(r'\$\{?\w+\}?/?\*?', first) or re.fullmatch(r'(~|\$HOME|\$\{HOME\})/\S*', first))
                if risky and not guarded:
                    sk.add(file, n, "X02", "error", "가드 없는 rm -rf — 변수가 비면 상위 경로·홈이 지워진다 (${VAR:?} 또는 기준 폴더 검사)", l)
            elif RM_PY.search(l):
                sk.add(file, n, "X02", "error", "홈·환경 변수 경로에 shutil.rmtree", l)
            if SUDO_RE.search(l):
                sk.add(file, n, "X06", "warn", "sudo·chmod 777·eval·base64 해독 실행 — 스킬이 권한 상승이나 난독화된 실행을 한다", l)
            if PERSIST_RE.search(l):
                sk.add(file, n, "X09", "warn", "셸 프로필·SSH 키·크론·전역 git/Claude 설정을 바꾼다 — 스킬을 지워도 남는다", l)
        if reads_secret:
            n, l = reads_secret[0]
            if uploads:
                sk.add(file, uploads[0][0], "X04", "error",
                       f"{file}이(가) 비밀 경로를 읽고(줄 {n}) 외부로도 보낸다 — 유출 조합", uploads[0][1])
            else:
                sk.add(file, n, "X03", "warn", "비밀·자격 증명 경로를 읽는다 — 정말 필요한지, 출력에 내보내지 않는지 확인", l)
        if net_rows and not declared_net and not is_md:
            n, l = net_rows[0]
            sk.add(file, n, "X05", "info", "네트워크를 쓰는데 frontmatter compatibility에 적혀 있지 않다 (설치 전에 알 수 없음)", l)


# ---------------------------------------------------------------- 수집·출력

def find_skills(paths: list[str]) -> list[Skill]:
    found: dict[str, Skill] = {}
    for p in paths:
        if os.path.isfile(p):
            if os.path.basename(p).lower() == "skill.md":
                found[os.path.abspath(p)] = Skill(p)
            continue
        for root, dirs, files in os.walk(p):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for f in sorted(files):
                if f.lower() == "skill.md":
                    full = os.path.join(root, f)
                    found[os.path.abspath(full)] = Skill(full)
    return list(found.values())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Agent Skills(SKILL.md) 규격·이식성·위험 패턴 린터")
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--min-level", choices=list(LEVELS), default="info")
    ap.add_argument("--ignore", default="", help="쉼표로 구분한 규칙 ID (예: K02,X05)")
    ap.add_argument("--no-scripts", action="store_true", help="scripts/ 등 스킬 폴더 안 코드 파일은 보지 않는다")
    ap.add_argument("--list-rules", action="store_true")
    a = ap.parse_args(argv)
    if a.list_rules:
        for k, v in RULES.items():
            print(f"{k}  {v}")
        return 0
    if not a.paths:
        ap.error("점검할 경로가 필요하다")
    ignore = {x.strip() for x in a.ignore.split(",") if x.strip()}
    unknown = ignore - set(RULES)
    if unknown:
        print("알 수 없는 규칙: " + ", ".join(sorted(unknown)), file=sys.stderr)
        return 2
    for p in a.paths:
        if not os.path.exists(p):
            print(f"경로가 없다: {p}", file=sys.stderr)
            return 2
    skills = find_skills(a.paths)
    if not skills:
        print("SKILL.md를 찾지 못했다: " + " ".join(a.paths), file=sys.stderr)
        return 2
    for sk in skills:
        check_skill(sk, scripts=not a.no_scripts)
    allf = [f for sk in skills for f in sk.findings if f.rule not in ignore and LEVELS[f.level] <= LEVELS[a.min_level]]
    counts = {lv: sum(1 for f in allf if f.level == lv) for lv in LEVELS}
    if a.json:
        print(json.dumps({"skills": [s.rel for s in skills], "counts": counts,
                          "findings": [asdict(f) for f in sorted(allf, key=lambda f: (f.skill, LEVELS[f.level], f.file, f.line))]},
                         ensure_ascii=False, indent=1))
    else:
        for sk in skills:
            mine = sorted((f for f in allf if f.skill == sk.rel), key=lambda f: (LEVELS[f.level], f.file, f.line))
            tag = "OK" if not any(f.level == "error" for f in mine) else "FAIL"
            print(f"## {sk.rel}  [{tag}]  error {sum(f.level=='error' for f in mine)} · warn {sum(f.level=='warn' for f in mine)} · info {sum(f.level=='info' for f in mine)}")
            for f in mine:
                print(f"  {LEVEL_LABEL[f.level]} {f.rule} {f.file}:{f.line}  {f.message}")
                if f.snippet:
                    print(f"        > {f.snippet}")
        print(f"\n스킬 {len(skills)}개 · error {counts['error']} · warn {counts['warn']} · info {counts['info']}")
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    sys.exit(main())

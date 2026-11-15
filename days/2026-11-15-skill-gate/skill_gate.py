#!/usr/bin/env python3
"""skill-gate — 예약 작업·/loop 에서 스킬이 승인 대기로 멈출지 미리 점검한다.

Claude Code 2.1.325 부터 예약 작업과 /loop 는 `allowed-tools` 나 `hooks` 를 선언한
스킬을 실행하기 전에 묻는다. 무인으로 돌리려면 permissions.allow 에 Skill(이름)을
넣어야 한다. 이 도구는 스킬을 찾아 그 규칙이 settings.json 에 있는지 대조하고,
빠진 것을 permissions.allow 조각으로 출력한다.

    python3 skill_gate.py [경로...] [--settings FILE ...] [--json] [--print-allow] [--quiet]

종료 코드: 0 = 막힐 스킬 없음, 1 = 허용 규칙이 빠졌거나 deny·ask 로 막힌 스킬 있음, 2 = 사용 오류.
표준 라이브러리만 쓴다. 키·네트워크·모델 불필요.
출처: https://github.com/anthropics/claude-code/releases/tag/v2.1.325
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "vendor"}
MAX_BYTES = 1_000_000
INJECT_LINE = re.compile(r"^\s*!`[^`]+`")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")


def read_text(path):
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return None
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def split_frontmatter(text):
    """(frontmatter 줄 목록, 본문 시작 줄 번호(1부터)). 없으면 ([], 1)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return [], 1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], i + 2
    return [], 1


def parse_top_level(fm):
    """최상위 키 → (같은 줄 값, 들여쓴 이어지는 줄 목록). 진짜 YAML 파서는 아니다."""
    out, key = {}, None
    for raw in fm:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:(.*)$", raw) if not raw[0].isspace() else None
        if m:
            key = m.group(1)
            out[key] = (m.group(2).strip(), [])
        elif key is not None and raw[0].isspace():
            out[key][1].append(raw.strip())
    return out


def unquote(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def declared(entry):
    """키 값이 실제로 뭔가를 선언하는가 (빈 값·[]·{}·null·| > 만 있는 것은 아님)."""
    if entry is None:
        return False
    inline, cont = entry
    v = unquote(inline)
    if v in ("", "|", ">", "|-", ">-", "[]", "{}", "~", "null", "None"):
        return any(c for c in cont if not c.startswith("#"))
    return True


def tool_tokens(entry):
    inline, cont = entry
    v = unquote(inline)
    parts = [v] if v and v not in ("|", ">", "|-", ">-") else []
    parts += [c[2:] if c.startswith("- ") else c for c in cont]
    return " ".join(parts).strip()


def find_injections(text, body_start):
    """! + 백틱 한 줄, 또는 ```! 펜스의 시작 줄 번호. 일반 펜스 안의 예시는 제외."""
    found, fence = [], None
    for n, line in enumerate(text.splitlines(), 1):
        if n < body_start:
            continue
        m = FENCE.match(line)
        if m:
            mark, info = m.group(1), m.group(2).strip()
            if fence is None:
                if info.startswith("!"):
                    found.append(n)
                fence = mark[0]
            elif mark[0] == fence:
                fence = None
            continue
        if fence is None and INJECT_LINE.match(line):
            found.append(n)
    return found


def find_skills(paths):
    seen, res = set(), []
    for p in paths:
        if os.path.isfile(p):
            files = [p] if os.path.basename(p) == "SKILL.md" else []
        else:
            files = []
            for d, dirs, names in os.walk(p):
                dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
                if "SKILL.md" in names:
                    files.append(os.path.join(d, "SKILL.md"))
        for f in files:
            rp = os.path.realpath(f)
            if rp not in seen:
                seen.add(rp)
                res.append((f, p))
    return res


def analyze(path):
    text = read_text(path)
    if text is None:
        return None
    fm, body_start = split_frontmatter(text)
    top = parse_top_level(fm)
    name = unquote(top["name"][0]) if "name" in top and top["name"][0] else os.path.basename(os.path.dirname(os.path.abspath(path)))
    triggers = []
    if declared(top.get("allowed-tools")):
        triggers.append("allowed-tools")
    if declared(top.get("hooks")):
        triggers.append("hooks")
    return {
        "name": name,
        "path": path,
        "triggers": triggers,
        "tools": tool_tokens(top["allowed-tools"]) if "allowed-tools" in top and "allowed-tools" in triggers else "",
        "injections": find_injections(text, body_start),
        "has_frontmatter": bool(fm),
    }


def settings_files_for(skill_path, arg_root):
    """스킬이 .claude/skills/<이름>/SKILL.md 위치면 그 프로젝트 루트, 아니면 인자 경로의 .claude 설정."""
    ap = os.path.abspath(skill_path)
    marker = os.sep + os.path.join(".claude", "skills") + os.sep
    root = ap.split(marker)[0] if marker in ap else os.path.abspath(arg_root if os.path.isdir(arg_root) else os.path.dirname(arg_root))
    return [os.path.join(root, ".claude", "settings.json"), os.path.join(root, ".claude", "settings.local.json")]


def load_rules(files, warnings):
    """파일 목록 → {'allow': [...], 'deny': [...], 'ask': [...]} (Skill 규칙만)."""
    rules = {"allow": [], "deny": [], "ask": []}
    used = []
    for f in files:
        if not os.path.isfile(f):
            continue
        text = read_text(f)
        try:
            data = json.loads(text) if text is not None else None
        except ValueError as e:
            warnings.append(f"설정 파일을 JSON으로 읽지 못함: {f} ({e})")
            continue
        if not isinstance(data, dict):
            warnings.append(f"설정 파일 최상위가 객체가 아님: {f}")
            continue
        used.append(f)
        perms = data.get("permissions")
        if not isinstance(perms, dict):
            continue
        for kind in rules:
            lst = perms.get(kind)
            if isinstance(lst, list):
                rules[kind] += [x.strip() for x in lst if isinstance(x, str) and re.match(r"^\s*Skill(\(|$)", x)]
    return rules, used


def rule_matches(rule, name):
    """Skill / Skill(이름) / Skill(이름 *) / Skill(이름:*) 이 이름과 맞는지."""
    if rule == "Skill":
        return True
    m = re.match(r"^Skill\((.*)\)$", rule)
    if not m:
        return False
    arg = m.group(1).strip()
    if arg in ("*", ""):
        return True
    for suffix in (" *", ":*"):
        if arg.endswith(suffix):
            arg = arg[: -len(suffix)]
            break
    return arg == name


def verdict(skill, rules):
    if not skill["triggers"]:
        return "FREE", None
    for kind, label in (("deny", "DENIED"), ("ask", "ASK")):
        hit = next((r for r in rules[kind] if rule_matches(r, skill["name"])), None)
        if hit:
            return label, hit
    hit = next((r for r in rules["allow"] if rule_matches(r, skill["name"])), None)
    if hit:
        return "ALLOWED", hit
    return "NEEDS-ALLOW", None


def run(paths, extra_settings):
    warnings, results = [], []
    skills = find_skills(paths)
    cache = {}
    for f, arg in skills:
        info = analyze(f)
        if info is None:
            warnings.append(f"읽지 못함: {f}")
            continue
        if not info["has_frontmatter"]:
            warnings.append(f"frontmatter 없음(이름은 폴더명, 선언 없음으로 처리): {f}")
        files = settings_files_for(f, arg) + list(extra_settings)
        key = tuple(files)
        if key not in cache:
            cache[key] = load_rules(files, warnings)
        rules, used = cache[key]
        v, rule = verdict(info, rules)
        info.update(verdict=v, rule=rule, settings=used)
        results.append(info)
    return results, warnings


def allow_snippet(results):
    names = sorted({r["name"] for r in results if r["verdict"] == "NEEDS-ALLOW"})
    return {"permissions": {"allow": [f"Skill({n})" for n in names]}}


ORDER = {"NEEDS-ALLOW": 0, "DENIED": 1, "ASK": 2, "ALLOWED": 3, "FREE": 4}
EXPLAIN = {
    "NEEDS-ALLOW": "무인 실행 시 실행 전에 묻는다 — permissions.allow 에 규칙 필요",
    "DENIED": "deny 규칙에 걸려 실행되지 않는다",
    "ASK": "ask 규칙이 있어 무인 실행에서 계속 묻는다",
    "ALLOWED": "허용 규칙 있음",
    "FREE": "allowed-tools·hooks 선언 없음 — 이 확인 대상 아님",
}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="skill_gate", description="예약 작업·/loop 에서 승인 대기로 멈출 스킬을 찾는다.")
    ap.add_argument("paths", nargs="*", default=["."], help="스킬이 있는 폴더(기본 .)")
    ap.add_argument("--settings", action="append", default=[], metavar="FILE",
                    help="규칙을 더 읽을 settings.json (예: ~/.claude/settings.json). 여러 번 가능")
    ap.add_argument("--json", action="store_true", help="JSON으로 출력")
    ap.add_argument("--print-allow", action="store_true", help="빠진 규칙을 permissions.allow JSON 조각으로만 출력")
    ap.add_argument("--quiet", action="store_true", help="막힐 스킬만 보여 준다(FREE·ALLOWED 숨김)")
    a = ap.parse_args(argv)

    for p in a.paths:
        if not os.path.exists(p):
            print(f"skill-gate: 경로가 없음: {p}", file=sys.stderr)
            return 2
    for f in a.settings:
        if not os.path.isfile(f):
            print(f"skill-gate: --settings 파일이 없음: {f}", file=sys.stderr)
            return 2
    results, warnings = run(a.paths, a.settings)
    if not results:
        print("skill-gate: SKILL.md 를 찾지 못함", file=sys.stderr)
        return 2
    results.sort(key=lambda r: (ORDER[r["verdict"]], r["name"]))
    blocked = [r for r in results if r["verdict"] in ("NEEDS-ALLOW", "DENIED", "ASK")]
    code = 1 if blocked else 0

    if a.print_allow:
        print(json.dumps(allow_snippet(results), ensure_ascii=False, indent=2))
        return code
    if a.json:
        print(json.dumps({"skills": results, "warnings": warnings, "allow_snippet": allow_snippet(results)},
                         ensure_ascii=False, indent=2))
        return code

    shown = [r for r in results if r["verdict"] in ORDER and (not a.quiet or r in blocked)]
    for r in shown:
        decl = ",".join(r["triggers"]) or "-"
        print(f"{r['verdict']:<11} {r['name']}  [{decl}]  {r['path']}")
        print(f"            {EXPLAIN[r['verdict']]}" + (f" (규칙: {r['rule']})" if r["rule"] else ""))
        if r["injections"]:
            print(f"            참고: ! 주입 줄 {len(r['injections'])}개(줄 {','.join(map(str, r['injections'][:5]))}) — 렌더링 때 실행됨")
    for w in warnings:
        print(f"주의: {w}")
    counts = {k: sum(1 for r in results if r["verdict"] == k) for k in ORDER}
    print("합계: " + " ".join(f"{k}={v}" for k, v in counts.items()))
    if any(r["verdict"] == "NEEDS-ALLOW" for r in results):
        print("\n빠진 규칙(permissions.allow 에 합칠 것):")
        print(json.dumps(allow_snippet(results), ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())

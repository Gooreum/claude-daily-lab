#!/usr/bin/env python3
"""read-guard — 쓸모없는 "전체 읽기"를 막는 Claude Code PreToolUse 훅 + 설정 점검기.

훅 모드 (기본): stdin의 PreToolUse JSON을 읽는다.
  - Read: 락 파일·*.min.js·*.map·의존성/빌드 폴더·압축/바이너리의 "전체 읽기"를 거부(exit 2).
          offset/limit로 일부만 읽는 호출, 작은 파일, 없는 파일은 통과.
  - Bash: 같은 파일을 cat/less/more/bat/nl로 통째로 찍는 명령을 거부. 파이프(| head 등)나
          head/tail/grep/wc/rg/jq는 통과.
  거부 이유는 stderr로 나가 모델에게 보인다. READ_GUARD_LOG가 있으면 판정을 JSONL로 남긴다.

--audit DIR : .claudeignore가 있는데 Read deny 규칙이 없으면 알리고, 옮길 규칙을 JSON으로 낸다.
--stats LOG : READ_GUARD_LOG 파일을 요약한다(차단 횟수·파일별 상위·추정 절약 토큰).
"""
import argparse
import fnmatch
import json
import os
import shlex
import sys
from collections import Counter

MIN_BYTES = int(os.environ.get("READ_GUARD_MIN_BYTES", "8192"))   # 이보다 작으면 통과
MAX_LIMIT = int(os.environ.get("READ_GUARD_MAX_LIMIT", "200"))    # limit이 이 이하면 "부분 읽기"

LOCKFILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "npm-shrinkwrap.json", "Cargo.lock",
    "poetry.lock", "uv.lock", "Pipfile.lock", "Gemfile.lock", "composer.lock", "go.sum",
    "bun.lock", "pdm.lock",
}
GLOBS = ["*.min.js", "*.min.css", "*.map", "*.bundle.js", "*.chunk.js"]
DIRS = {"node_modules", "dist", "build", "vendor", ".next", "__pycache__", ".venv", "target"}
BINARY_EXT = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".so", ".dylib", ".dll", ".exe",
              ".o", ".a", ".pyc", ".class", ".jar", ".wasm", ".bin", ".sqlite", ".db", ".woff", ".woff2"}
CAT_LIKE = {"cat", "less", "more", "bat", "nl"}
SEPARATORS = {";", "&&", "||", "|", "&"}


def classify(path):
    """무거운 파일이면 이유(kind)를, 아니면 None."""
    base = os.path.basename(path)
    ext = os.path.splitext(base)[1].lower()
    if base in LOCKFILES:
        return "lockfile"
    if any(fnmatch.fnmatch(base, g) for g in GLOBS):
        return "bundle"
    if ext in BINARY_EXT:
        return "binary"
    parts = set(path.replace("\\", "/").split("/"))
    if parts & DIRS:
        return "dependency-or-build-dir"
    return None


def resolve(path, cwd):
    return path if os.path.isabs(path) else os.path.join(cwd or os.getcwd(), path)


def file_size(path):
    try:
        return os.stat(path).st_size
    except OSError:
        return None  # 없는 파일 → 판단 보류(통과)


def judge_read(tool_input, cwd):
    path = tool_input.get("file_path") or ""
    kind = classify(path)
    if not kind:
        return None
    limit = tool_input.get("limit")
    if isinstance(limit, int) and 0 < limit <= MAX_LIMIT:
        return None
    # offset만 있고 limit이 없으면 끝까지 읽으므로 전체 읽기로 본다
    size = file_size(resolve(path, cwd))
    if size is None:
        return None
    if kind != "binary" and size < MIN_BYTES:
        return None
    return {"path": path, "kind": kind, "bytes": size}


def judge_bash(command, cwd):
    try:
        toks = shlex.split(command, posix=True)
    except ValueError:
        return None
    # 명령을 구분자로 나눈다. 구분자가 "|"로 이어지는 앞 세그먼트는 출력이 걸러지므로 통과.
    segs, cur, seps = [], [], []
    for t in toks:
        if t in SEPARATORS:
            segs.append(cur)
            seps.append(t)
            cur = []
        else:
            cur.append(t)
    segs.append(cur)
    seps.append(";")
    for seg, sep in zip(segs, seps):
        if not seg or sep == "|":
            continue
        if os.path.basename(seg[0]) not in CAT_LIKE:
            continue
        for arg in seg[1:]:
            if arg.startswith("-"):
                continue
            kind = classify(arg)
            size = file_size(resolve(arg, cwd))
            if kind and size is not None and (kind == "binary" or size >= MIN_BYTES):
                return {"path": arg, "kind": kind, "bytes": size, "via": seg[0]}
    return None


def reason_text(hit):
    p, k, b = hit["path"], hit["kind"], hit["bytes"]
    return (f"read-guard: {p} ({b:,} bytes, {k}) 전체 읽기는 컨텍스트를 낭비합니다. "
            f"필요한 부분만 읽으세요: Grep으로 찾은 뒤 Read에 offset/limit(≤{MAX_LIMIT}줄)을 주거나, "
            f"`grep -n <패턴> {p}`, `head -n 50 {p}`, `wc -l {p}`를 쓰세요.")


def log_event(log, event):
    if not log:
        return
    try:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass


def run_hook():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # 입력이 이상해도 작업을 막지 않는다
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    if tool == "Read":
        hit = judge_read(ti, cwd)
    elif tool == "Bash":
        hit = judge_bash(ti.get("command", ""), cwd)
    else:
        return 0
    log = os.environ.get("READ_GUARD_LOG")
    if hit:
        log_event(log, {"tool": tool, "decision": "deny", **hit})
        print(reason_text(hit), file=sys.stderr)
        return 2
    return 0


def deny_rule(pattern):
    p = pattern.strip().rstrip("/")
    if p.startswith("/"):
        p = p[1:]
    if pattern.strip().endswith("/"):
        return f"Read(./{p}/**)"
    return f"Read(./{p})" if "/" in p else f"Read(./**/{p})"


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def audit(root):
    result = {"root": root, "claudeignore": None, "deny_rules": [], "guard_hook": False,
              "missing_rules": [], "status": "ok"}
    ci = os.path.join(root, ".claudeignore")
    if os.path.isfile(ci):
        with open(ci, encoding="utf-8") as f:
            entries = [ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
        result["claudeignore"] = entries
    for name in ("settings.json", "settings.local.json"):
        s = load_json(os.path.join(root, ".claude", name))
        result["deny_rules"] += [r for r in s.get("permissions", {}).get("deny", []) if r.startswith("Read(")]
        for grp in s.get("hooks", {}).get("PreToolUse", []):
            for h in grp.get("hooks", []):
                if "read_guard" in h.get("command", "") or "read-guard" in h.get("command", ""):
                    result["guard_hook"] = True
    if result["claudeignore"] is not None:
        wanted = [deny_rule(e) for e in result["claudeignore"]]
        result["missing_rules"] = [r for r in wanted if r not in result["deny_rules"]]
        if result["missing_rules"]:
            result["status"] = "claudeignore-has-no-effect"
    if not result["guard_hook"] and result["status"] == "ok":
        result["status"] = "no-guard-hook"
    return result


def print_audit(res):
    print(f"# read-guard 점검 — {res['root']}")
    if res["claudeignore"] is None:
        print("- .claudeignore: 없음")
    else:
        print(f"- .claudeignore: {len(res['claudeignore'])}개 항목. Claude Code는 이 파일을 읽지 않습니다 — 항목은 아무것도 막지 못합니다.")
    print(f"- Read deny 규칙: {len(res['deny_rules'])}개")
    print(f"- read-guard 훅 등록: {'예' if res['guard_hook'] else '아니오'}")
    if res["missing_rules"]:
        print("\n.claude/settings.json의 permissions.deny에 옮길 규칙:")
        print(json.dumps({"permissions": {"deny": res["missing_rules"]}}, indent=2, ensure_ascii=False))
        print("(주의: deny 규칙은 부분 읽기까지 전부 막습니다. 락 파일처럼 가끔 일부는 읽어야 하는 것은 훅에 맡기세요.)")
    if not res["guard_hook"]:
        print("\nPreToolUse 훅 등록 예: settings.example.json 참고")
    print(f"\n판정: {res['status']}")


def stats(log):
    events = []
    with open(log, encoding="utf-8") as f:
        for ln in f:
            try:
                events.append(json.loads(ln))
            except ValueError:
                pass
    denies = [e for e in events if e.get("decision") == "deny"]
    by_path = Counter(e["path"] for e in denies)
    by_kind = Counter(e["kind"] for e in denies)
    saved = sum(min(e.get("bytes", 0), 256 * 1024) for e in denies) // 4  # 바이트/4 ≈ 토큰 (거친 추정)
    print(f"# read-guard 통계 — {log}")
    print(f"- 차단 {len(denies)}건, 추정 절약 약 {saved:,} 토큰 (바이트÷4, 거친 추정)")
    for k, n in by_kind.most_common():
        print(f"- 종류 {k}: {n}건")
    for p, n in by_path.most_common(5):
        print(f"- {p}: {n}건")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--audit", metavar="DIR", help=".claudeignore와 Read deny 규칙, 훅 등록을 점검")
    ap.add_argument("--stats", metavar="LOG", help="READ_GUARD_LOG 요약")
    ap.add_argument("--json", action="store_true", help="--audit 결과를 JSON으로")
    a = ap.parse_args()
    if a.audit:
        res = audit(a.audit)
        if a.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print_audit(res)
        return 0 if res["status"] == "ok" else 1
    if a.stats:
        return stats(a.stats)
    return run_hook()


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""review-gate — Claude Code Review(GitHub) 체크런을 병합 관문으로 읽고, REVIEW.md를 점검한다.

  review_gate.py gate --file check-runs.json            # 저장해 둔 JSON으로
  review_gate.py gate --repo OWNER/REPO --sha SHA       # gh api로 직접
  review_gate.py lint [DIR|REVIEW.md] [--base origin/main]

gate 종료 코드: 0 통과 · 1 기준 초과 · 2 입력/사용법 오류 · 3 판정 없음(리뷰 미완료·건너뜀·개수 줄 없음)
lint 종료 코드: 0 오류 없음 · 1 오류(또는 --strict에서 경고) · 2 입력 오류
표준 라이브러리만 쓴다. 비밀값은 다루지 않는다(gh 로그인은 gh가 처리).
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

CHECK_NAME = "Claude Code Review"
NO_ISSUES_TITLE = "code review found no issues"
SEVERITY_RE = re.compile(r"bughunter-severity:\s*(\{[^{}]*\})\s*-->")
# 문서: normal = Important(🔴), nit = Nit(🟡), pre_existing = Pre-existing(🟣)
LABELS = {"normal": "Important", "nit": "Nit", "pre_existing": "Pre-existing"}


# ---------------------------------------------------------------- gate

def pick_check_run(runs):
    cands = [r for r in runs if isinstance(r, dict) and r.get("name") == CHECK_NAME]
    if not cands:
        return None
    key = lambda r: (r.get("completed_at") or r.get("started_at") or "", r.get("id") or 0)
    return max(cands, key=key)


def parse_counts(text):
    """본문 마지막 bughunter-severity 주석을 읽는다. (counts|None, 이유)"""
    found = SEVERITY_RE.findall(text or "")
    if not found:
        return None, "본문에 bughunter-severity 줄이 없다"
    try:
        data = json.loads(found[-1])
    except ValueError:
        return None, "bughunter-severity JSON을 해석할 수 없다"
    if not isinstance(data, dict) or not isinstance(data.get("normal"), int) or isinstance(data.get("normal"), bool):
        return None, "bughunter-severity에 정수 normal 값이 없다"
    counts = {}
    for k in LABELS:
        v = data.get(k, 0)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            return None, f"bughunter-severity의 {k} 값이 정수가 아니다"
        counts[k] = v
    return counts, "ok"


def evaluate(run, args):
    """체크런 하나 → {verdict: pass|fail|none, reason, counts}"""
    if run is None:
        return {"verdict": "none", "reason": f"'{CHECK_NAME}' 체크런이 없다(리뷰가 아직 안 시작됐거나 꺼져 있다)", "counts": None}
    status, concl = run.get("status"), run.get("conclusion")
    if status != "completed":
        return {"verdict": "none", "reason": f"리뷰가 아직 끝나지 않았다(status={status})", "counts": None}
    if concl == "skipped":
        return {"verdict": "none", "reason": "리뷰가 건너뛰어졌다(push에 바뀐 파일 없음 등)", "counts": None}
    out = run.get("output") or {}
    counts, why = parse_counts(out.get("text"))
    if counts is None and args.trust_title and (out.get("title") or "").strip().lower().startswith(NO_ISSUES_TITLE):
        counts, why = {k: 0 for k in LABELS}, "제목이 '발견 없음'(--trust-title)"
    if counts is None:
        return {"verdict": "none", "reason": f"{why}. 0개가 아니라 판정 없음으로 본다(실패·타임아웃·교체된 리뷰일 수 있다)", "counts": None}
    limits = {"normal": args.max_important, "nit": args.max_nit, "pre_existing": args.max_pre_existing}
    over = [f"{LABELS[k]} {counts[k]} > {lim}" for k, lim in limits.items() if lim is not None and counts[k] > lim]
    if over:
        return {"verdict": "fail", "reason": "기준 초과: " + ", ".join(over), "counts": counts}
    return {"verdict": "pass", "reason": why, "counts": counts}


def gh(argv, gh_bin="gh"):
    p = subprocess.run([gh_bin] + argv, capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError(f"gh {' '.join(argv)} 실패: {p.stderr.strip() or p.stdout.strip()}")
    return p.stdout


def load_runs(args):
    if args.file:
        raw = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict) and "check_runs" in data:
            return data["check_runs"]
        return data if isinstance(data, list) else [data]
    path = f"repos/{args.repo}/commits/{args.sha}/check-runs"
    if args.dry_run:
        print(f"gh api {path} --paginate --jq '.check_runs[]'")
        print(f"(Claude Code Review 체크런의 output.text가 비어 있으면) gh api repos/{args.repo}/check-runs/<id>")
        return None
    out = gh(["api", path, "--paginate", "--jq", ".check_runs[]"])
    runs = [json.loads(line) for line in out.splitlines() if line.strip()]
    run = pick_check_run(runs)
    if run and not (run.get("output") or {}).get("text") and run.get("id"):
        runs = [json.loads(gh(["api", f"repos/{args.repo}/check-runs/{run['id']}"]))]
    return runs


def cmd_gate(args):
    if bool(args.file) == bool(args.repo and args.sha):
        print("--file 또는 (--repo 와 --sha) 중 하나만 준다", file=sys.stderr)
        return 2
    try:
        runs = load_runs(args)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as e:
        print(f"입력 오류: {e}", file=sys.stderr)
        return 2
    if runs is None:
        return 0
    res = evaluate(pick_check_run(runs), args)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, sort_keys=True))
    else:
        c = res["counts"]
        line = "" if c is None else " · ".join(f"{LABELS[k]} {c[k]}" for k in LABELS)
        print(f"[{res['verdict'].upper()}] {line}".rstrip() + f"\n  {res['reason']}")
    if res["verdict"] == "none":
        return 0 if args.on_no_verdict == "pass" else 3
    return 0 if res["verdict"] == "pass" else 1


# ---------------------------------------------------------------- lint

_NUM = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|a few|no)"
NIT_CAP = re.compile(
    r"((at most|up to|no more than|max\w*|limit\w*|cap\w*)\s+(?:of\s+)?" + _NUM + r"\s+(?:\w+\s+)?nits?\b"
    r"|nits?\b.{0,40}(?:at most|up to|no more than|max\w*|limit\w*)\s+" + _NUM + r"\b"
    r"|(?:cap|limit)\w*\s+(?:the\s+)?(?:\w+\s+)?nits?\b.{0,20}" + _NUM + r"\b"
    r"|nits?\b.{0,40}(?:limited|capped)\s+to\s+" + _NUM + r"\b"
    r"|최대\s*\d+\s*개?\s*(?:의\s*)?nits?|nits?\w*.{0,20}최대\s*\d+)", re.I)
SKIP = re.compile(r"(do not report|don'?t report|never report|skip|ignore|exclude|제외|보고하지|무시)", re.I)
GENERAL = re.compile(r"(npm (run|install|test)|pip install|pytest|make \w+|how to (build|run|install)|빌드 방법|설치 방법|실행 방법|docker compose)", re.I)
OPEN_ENDED = re.compile(r"(flag everything|report (all|every)|every (issue|nit|style)|all (issues|style)|모든 (이슈|문제|스타일)|전부 (지적|보고))", re.I)


def find_review_files(target):
    t = Path(target)
    if t.is_file():
        return [t], t.parent
    files = sorted(p for p in t.rglob("REVIEW.md") if ".git" not in p.parts and "node_modules" not in p.parts)
    return files, t


def lint_text(text):
    issues = []
    lines = text.splitlines()
    if not text.strip():
        return [("error", "R001", 1, "파일이 비어 있다")]
    if not re.search(r"important", text, re.I):
        issues.append(("warn", "R010", 1, "'Important'가 무엇인지 정의하지 않았다. 기본 기준은 운영 코드용이라 문서·설정 저장소에선 과하게 🔴가 붙는다"))
    if not NIT_CAP.search(text):
        issues.append(("warn", "R011", 1, "Nit 개수 상한이 없다(예: 'Report at most five Nits per review.')"))
    if not SKIP.search(text):
        issues.append(("warn", "R012", 1, "건너뛸 경로·범주가 없다(생성 파일, 락파일, CI가 이미 막는 린트 등)"))
    for i, ln in enumerate(lines, 1):
        if OPEN_ENDED.search(ln):
            issues.append(("warn", "R021", i, "범위 제한 없는 지시('모두 보고')는 Nit를 늘린다. 클래스를 좁혀라"))
        if GENERAL.search(ln):
            issues.append(("warn", "R020", i, "프로젝트 일반 안내(빌드·설치)로 보인다. REVIEW.md는 리뷰 동작만, 일반 맥락은 CLAUDE.md로"))
    return issues


def git_state(repo_root, base, rel):
    """(base에 존재하는가, base와 내용이 같은가)"""
    spec = f"{base}:{rel}"
    ex = subprocess.run(["git", "-C", str(repo_root), "cat-file", "-e", spec], capture_output=True)
    if ex.returncode != 0:
        return False, False
    d = subprocess.run(["git", "-C", str(repo_root), "diff", "--quiet", base, "--", rel], capture_output=True)
    return True, d.returncode == 0


def cmd_lint(args):
    files, root = find_review_files(args.path)
    if not files:
        print(f"REVIEW.md가 없다: {args.path}", file=sys.stderr)
        return 2
    n_err = n_warn = 0
    for f in files:
        issues = lint_text(f.read_text(encoding="utf-8"))
        if args.base:
            top = subprocess.run(["git", "-C", str(f.parent), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
            if top.returncode != 0:
                print(f"--base는 git 저장소 안에서만 쓴다: {f}", file=sys.stderr)
                return 2
            top = Path(top.stdout.strip())
            rel = f.resolve().relative_to(top.resolve()).as_posix()
            exists, same = git_state(top, args.base, rel)
            if not exists:
                issues.append(("error", "R030", 1, f"{args.base}에 이 파일이 없다. 리뷰는 PR 자신의 변경이 아니라 기본/베이스 브랜치의 REVIEW.md만 읽는다 — 먼저 병합하라"))
            elif not same:
                issues.append(("warn", "R031", 1, f"{args.base}의 사본과 내용이 다르다. 바뀐 부분은 병합되기 전까지 리뷰에 적용되지 않는다"))
        label = f.relative_to(root).as_posix() if root in f.parents or f.parent == root else str(f)
        print(f"{label}: {'문제 없음' if not issues else str(len(issues)) + '건'}")
        for sev, rid, ln, msg in issues:
            print(f"  {sev.upper():5} {rid} L{ln}: {msg}")
            n_err += sev == "error"
            n_warn += sev == "warn"
    print(f"파일 {len(files)}개 · 오류 {n_err} · 경고 {n_warn}")
    return 1 if n_err or (args.strict and n_warn) else 0


# ---------------------------------------------------------------- main

def build_parser():
    ap = argparse.ArgumentParser(prog="review_gate.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gate", help="Claude Code Review 체크런으로 병합 관문 판정")
    g.add_argument("--file", help="check-runs JSON 파일(- 은 stdin). {check_runs:[…]} 또는 체크런 하나/배열")
    g.add_argument("--repo", help="OWNER/REPO")
    g.add_argument("--sha", help="PR 머리 커밋 SHA")
    g.add_argument("--max-important", type=int, default=0, help="허용할 Important(🔴) 수 (기본 0)")
    g.add_argument("--max-nit", type=int, default=None, help="허용할 Nit(🟡) 수 (기본 제한 없음)")
    g.add_argument("--max-pre-existing", type=int, default=None, help="허용할 Pre-existing(🟣) 수 (기본 제한 없음)")
    g.add_argument("--on-no-verdict", choices=["fail", "pass"], default="fail", help="판정 없음일 때 종료 코드 (fail=3, pass=0)")
    g.add_argument("--trust-title", action="store_true", help="개수 줄이 없어도 제목이 'Code review found no issues'면 0개로 본다")
    g.add_argument("--json", action="store_true")
    g.add_argument("--dry-run", action="store_true", help="--repo 모드에서 부를 gh 명령만 출력")
    g.set_defaults(fn=cmd_gate)
    l = sub.add_parser("lint", help="REVIEW.md 점검")
    l.add_argument("path", nargs="?", default=".", help="저장소 디렉터리 또는 REVIEW.md 파일")
    l.add_argument("--base", help="기본/베이스 ref(예: origin/main). 거기에 병합돼 있는지 확인")
    l.add_argument("--strict", action="store_true", help="경고도 실패로 본다")
    l.set_defaults(fn=cmd_lint)
    return ap


if __name__ == "__main__":
    a = build_parser().parse_args()
    sys.exit(a.fn(a))

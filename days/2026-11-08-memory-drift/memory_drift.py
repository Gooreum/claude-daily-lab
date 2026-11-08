#!/usr/bin/env python3
"""memory-drift — 기억 노트가 가리키는 외부 사실이 저장소에서 아직 참인지 대조한다.

Anthropic 엔지니어링 글(2026-11-06)은 노트가 처음부터 틀리거나 환경이 바뀌며 낡을 수 있어,
원본(기록)과 대조하는 "드리밍"이 필요하다고 한다. 이 도구는 그중 기계가 할 수 있는 부분만 한다:
노트 안의 `백틱` 주장(경로·함수명·상수·옵션·커밋 해시)이 저장소에 아직 있는지, 노트가 사건마다 한 파일씩 불어나지 않았는지.
표준 라이브러리만 쓰고 모델·키·네트워크가 필요 없다.

종료 코드: 0 깨끗함 / 1 경고 있음 / 3 입력 오류
"""
import argparse, json, re, subprocess, sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
EXTS = {"py", "md", "sh", "json", "ts", "tsx", "js", "mjs", "yml", "yaml", "toml", "html", "css", "txt", "cfg", "ini", "go", "rs", "rb", "java", "lock"}
MAX_FILE = 1_000_000
MAX_CORPUS = 50_000_000
BACKTICK = re.compile(r"`([^`\n]+)`")
PATH_OK = re.compile(r"^[\w.@+\-]+(?:/[\w.@+\-]+)*/?$")
CALL = re.compile(r"^([A-Za-z_][\w.]*)\(\)$")
SNAKE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")
ENVVAR = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")
FLAG = re.compile(r"^--[a-z][\w-]+$")
SHA = re.compile(r"^[0-9a-f]{7,40}$")
DATED_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}|[-_]\d{8}(?:[-_.]|$)")


def parse_args(argv):
    p = argparse.ArgumentParser(description="기억 노트의 낡은 주장 점검")
    p.add_argument("memory_dir", help="MEMORY.md와 노트 .md 파일이 든 폴더")
    p.add_argument("--repo", required=True, help="노트의 주장을 대조할 저장소 폴더")
    p.add_argument("--max-files", type=int, default=30, help="이 개수를 넘으면 file-count 경고 (기본 30)")
    p.add_argument("--json", action="store_true", help="JSON으로 출력")
    return p.parse_args(argv)


def list_repo(repo):
    files = []
    for p in repo.rglob("*"):
        if any(part in SKIP_DIRS for part in p.relative_to(repo).parts):
            continue
        if p.is_file():
            files.append(p)
    return files


def build_corpus(files):
    chunks, total = [], 0
    for p in files:
        try:
            if p.stat().st_size > MAX_FILE:
                continue
            data = p.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:4096]:
            continue
        total += len(data)
        if total > MAX_CORPUS:
            break
        chunks.append(data.decode("utf-8", "replace"))
    return "\n".join(chunks)


def strip_fences(text):
    out, fenced = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        out.append("" if fenced else line)
    return out


def claims(text):
    """(줄번호, 토큰) 목록. 코드 펜스 안과 `drift:ignore`가 있는 줄은 건너뛴다."""
    found = []
    for i, line in enumerate(strip_fences(text), 1):
        if "drift:ignore" in line:
            continue
        for m in BACKTICK.finditer(line):
            found.append((i, m.group(1).strip()))
    return found


def classify(tok):
    """토큰을 (종류, 값) 으로. 대조할 수 없는 것은 (None, 사유)."""
    if re.match(r"^[a-z]+://", tok) or tok.startswith("~"):
        return None, "외부 주소·홈 경로"
    if any(c in tok for c in "*<>{}$ |=,;"):
        return None, "패턴·명령"
    if SHA.match(tok) and re.search(r"[0-9]", tok) and re.search(r"[a-f]", tok):
        return "sha", tok
    if FLAG.match(tok):
        return "flag", tok
    m = CALL.match(tok)
    if m:
        return "ident", m.group(1).split(".")[-1]
    path = re.sub(r"(?::\d+(?:-\d+)?|#[\w-]+)$", "", tok)
    if PATH_OK.match(path):
        last = path.rstrip("/").split("/")[-1]
        ext = last.rsplit(".", 1)[-1].lower() if "." in last else ""
        if re.match(r"^\.[A-Za-z0-9]+$", last):
            return None, "확장자만 적은 토큰"
        if path.endswith("/") or ext in EXTS:
            return "path", path
    if SNAKE.match(tok) or ENVVAR.match(tok):
        return "ident", tok
    return None, "대조 대상 아님"


def git_has(repo, sha):
    try:
        r = subprocess.run(["git", "-C", str(repo), "cat-file", "-e", sha + "^{commit}"],
                           capture_output=True, timeout=10)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return None


def is_git(repo):
    try:
        r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--git-dir"], capture_output=True, timeout=10)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def run(memory_dir, repo, max_files):
    notes = sorted(p for p in memory_dir.glob("*.md"))
    repo_files = list_repo(repo)
    rel = {str(p.relative_to(repo)) for p in repo_files}
    by_base = {}
    for r in rel:
        by_base.setdefault(r.rsplit("/", 1)[-1], []).append(r)
    dirs = {str(Path(r).parent) for r in rel} | {str(q) for r in rel for q in Path(r).parents}
    corpus = build_corpus(repo_files)
    git_ok = is_git(repo)
    root = str(repo.resolve())
    issues, checked, skipped = [], 0, 0

    def add(level, code, note, line, msg):
        issues.append({"level": level, "code": code, "file": note.name, "line": line, "message": msg})

    for note in notes:
        text = note.read_text(encoding="utf-8", errors="replace")
        for line, tok in claims(text):
            kind, val = classify(tok)
            if kind is None:
                skipped += 1
                continue
            if kind == "path":
                if val.startswith("/"):
                    if val.startswith(root + "/"):
                        val = val[len(root) + 1:]
                    else:
                        skipped += 1
                        continue
                checked += 1
                key = val.rstrip("/")
                if key in rel or key in dirs:
                    continue
                if "/" not in key and key in by_base:
                    continue
                hit = by_base.get(key.rsplit("/", 1)[-1])
                hint = f" (같은 이름이 {hit[0]}에 있음 — 옮겨졌나?)" if hit else ""
                add("WARN", "path-missing", note, line, f"`{tok}` 없음{hint}")
            elif kind == "ident":
                checked += 1
                if not re.search(r"(?<![\w])" + re.escape(val) + r"(?![\w])", corpus):
                    add("WARN", "ident-missing", note, line, f"`{tok}` 를 저장소에서 찾지 못함 (이름이 바뀌었거나 지워졌나?)")
            elif kind == "flag":
                checked += 1
                if val not in corpus:
                    add("INFO", "flag-missing", note, line, f"`{tok}` 를 저장소에서 찾지 못함 (외부 도구 옵션이면 무시)")
            elif kind == "sha":
                if not git_ok:
                    skipped += 1
                    continue
                checked += 1
                has = git_has(repo, val)
                if has is False:
                    add("WARN", "sha-missing", note, line, f"커밋 `{tok}` 가 저장소에 없음 (다시 쓴 이력이거나 틀린 해시)")
                else:
                    add("INFO", "sha-derivable", note, line, f"커밋 `{tok}` 는 git log로 읽히는 정보라 노트에 둘 필요가 적음")

    n = len(notes)
    dated = [p.name for p in notes if DATED_NAME.search(p.name)]
    if n >= 5 and len(dated) * 2 >= n:
        issues.append({"level": "WARN", "code": "event-ledger", "file": "(폴더)", "line": 0,
                       "message": f"노트 {n}개 중 {len(dated)}개가 날짜 이름 — 사건마다 파일 하나씩 쌓는 패턴. 주제별로 합치면 읽는 비용이 준다"})
    if n > max_files:
        issues.append({"level": "WARN", "code": "file-count", "file": "(폴더)", "line": 0,
                       "message": f"노트가 {n}개로 상한 {max_files}개를 넘음 — 주제별 병합 대상"})
    size = sum(p.stat().st_size for p in notes)
    return {"notes": n, "bytes": size, "checked": checked, "skipped": skipped, "issues": issues}


def main(argv=None):
    a = parse_args(argv)
    mem, repo = Path(a.memory_dir), Path(a.repo)
    for label, p in (("기억 폴더", mem), ("저장소", repo)):
        if not p.is_dir():
            print(f"오류: {label}가 폴더가 아님: {p}", file=sys.stderr)
            return 3
    if not list(mem.glob("*.md")):
        print(f"오류: {mem} 에 .md 노트가 없음", file=sys.stderr)
        return 3
    res = run(mem, repo, a.max_files)
    warns = sum(1 for i in res["issues"] if i["level"] == "WARN")
    infos = sum(1 for i in res["issues"] if i["level"] == "INFO")
    if a.json:
        res["warnings"], res["infos"] = warns, infos
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        for i in res["issues"]:
            loc = f"{i['file']}:{i['line']}" if i["line"] else i["file"]
            print(f"{i['level']:<5} {i['code']:<14} {loc} — {i['message']}")
        print(f"노트 {res['notes']}개({res['bytes']}바이트) · 대조한 주장 {res['checked']}개 · 건너뜀 {res['skipped']}개 · 경고 {warns} · 참고 {infos}")
    return 1 if warns else 0


if __name__ == "__main__":
    sys.exit(main())

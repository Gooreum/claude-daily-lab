#!/usr/bin/env python3
"""dream-lint — Claude 파일 기억 폴더(MEMORY.md 색인 + 프론트매터 파일)의 기계적 점검.

정리(distill)를 모델에 맡기기 전에, 규칙으로 잡히는 문제부터 걸러낸다. 표준 라이브러리만 쓰고 네트워크·키가 필요 없다.
종료 코드: 0 깨끗함 / 1 경고만 / 2 오류 있음 / 3 입력 오류
"""
import argparse, json, re, sys
from pathlib import Path

TYPES = {"user", "feedback", "project", "reference"}
# 패턴 자체가 저장소 비밀값 검사에 걸리지 않도록 조각으로 조립한다.
SECRET = re.compile("|".join([
    "sk-" + "ant-[A-Za-z0-9_-]{8,}",
    "AK" + "IA[0-9A-Z]{12,}",
    "gh" + "p_[A-Za-z0-9]{20,}",
    "BEGIN [A-Z ]*PRIV" + "ATE KEY",
]))
REL_DATE = re.compile(r"오늘|어제|내일|이번 주|다음 주|지난주|다음 달|\b(today|yesterday|tomorrow|next week|last week|this week|next month)\b", re.I)
INDEX_LINE = re.compile(r"^- \[([^\]]+)\]\(([^)]+)\)\s*(?:[—-]\s*(.*))?$")
WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")


def parse_frontmatter(text):
    """(fields, body, error). 중첩은 한 단계(metadata: type:)만 읽는다."""
    if not text.startswith("---\n"):
        return {}, text, "프론트매터가 없다(첫 줄이 ---가 아님)"
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text, "프론트매터가 닫히지 않았다"
    fields, parent = {}, None
    for raw in text[4:end].split("\n"):
        if not raw.strip():
            continue
        m = re.match(r"^(\s*)([A-Za-z_][\w-]*):\s*(.*)$", raw)
        if not m:
            return {}, text, f"프론트매터 줄을 읽지 못함: {raw!r}"
        indent, key, val = m.groups()
        if indent and parent:
            fields[f"{parent}.{key}"] = val.strip()
        else:
            parent = key if not val.strip() else None
            fields[key] = val.strip()
    body = text[end + 4:].lstrip("\n")
    return fields, body, None


def tokens(s):
    return {t for t in re.findall(r"[0-9A-Za-z가-힣]{2,}", s.lower())}


def lint(root, max_index_lines=200, max_line_len=150, dup_threshold=0.6):
    root = Path(root)
    issues = []
    def add(level, code, where, msg):
        issues.append({"level": level, "code": code, "file": where, "message": msg})

    files = sorted(p for p in root.glob("*.md") if p.name != "MEMORY.md")
    index = root / "MEMORY.md"
    indexed = {}
    if not index.exists():
        add("error", "no-index", "MEMORY.md", "색인 파일이 없다")
    else:
        lines = index.read_text(encoding="utf-8").splitlines()
        body_lines = [(i + 1, l) for i, l in enumerate(lines) if l.strip()]
        if len(body_lines) > max_index_lines:
            add("warn", "index-long", "MEMORY.md", f"색인이 {len(body_lines)}줄이다(기준 {max_index_lines}줄). 뒤쪽이 잘려 읽힐 수 있다")
        for no, line in body_lines:
            if line.startswith("---"):
                add("warn", "index-frontmatter", f"MEMORY.md:{no}", "색인에는 프론트매터를 두지 않는다")
                continue
            m = INDEX_LINE.match(line)
            if not m:
                add("warn", "index-format", f"MEMORY.md:{no}", "`- [제목](파일.md) — 한 줄 설명` 형식이 아니다")
                continue
            if len(line) > max_line_len:
                add("warn", "index-line-long", f"MEMORY.md:{no}", f"{len(line)}자다(기준 {max_line_len}자). 내용은 파일에 두고 색인은 한 줄로")
            target = m.group(2)
            if not (root / target).exists():
                add("error", "index-dangling", f"MEMORY.md:{no}", f"색인이 없는 파일을 가리킨다: {target}")
            if target in indexed:
                add("warn", "index-duplicate", f"MEMORY.md:{no}", f"같은 파일이 색인에 두 번 나온다: {target}")
            indexed[target] = no

    meta = {}
    for p in files:
        text = p.read_text(encoding="utf-8")
        fields, body, err = parse_frontmatter(text)
        if p.name not in indexed:
            add("warn", "not-indexed", p.name, "MEMORY.md 색인에 없다. 읽히지 않는 기억이다")
        if SECRET.search(text):
            add("error", "secret", p.name, "키·토큰·개인키 패턴이 들어 있다. 지우고 회전해야 한다")
        if err:
            add("error", "frontmatter", p.name, err)
            continue
        for k in ("name", "description", "metadata.type"):
            if not fields.get(k):
                add("error", "missing-field", p.name, f"필수 항목이 없다: {k}")
        name, typ = fields.get("name", ""), fields.get("metadata.type", "")
        if name and name != p.stem and not p.stem.startswith(name):
            add("warn", "name-mismatch", p.name, f"name({name})이 파일명({p.stem})과 다르다")
        if typ and typ not in TYPES:
            add("error", "bad-type", p.name, f"type은 {sorted(TYPES)} 중 하나여야 한다: {typ}")
        if typ in ("feedback", "project"):
            for need in ("**Why:**", "**How to apply:**"):
                if need not in body:
                    add("warn", "missing-why", p.name, f"{typ} 기억에 {need} 줄이 없다")
        if typ == "project" and REL_DATE.search(body):
            add("warn", "relative-date", p.name, f"상대 날짜({REL_DATE.search(body).group(0)})가 있다. 절대 날짜로 바꿔야 나중에도 읽힌다")
        if not body.strip():
            add("warn", "empty-body", p.name, "본문이 비어 있다")
        meta[p.stem] = {"name": name, "desc": fields.get("description", ""), "file": p.name}
        for ref in WIKILINK.findall(body):
            meta[p.stem].setdefault("links", set()).add(ref.strip())

    names = {v["name"] for v in meta.values() if v["name"]} | set(meta)
    for stem, v in sorted(meta.items()):
        for ref in sorted(v.get("links", ())):
            if ref not in names:
                add("info", "link-pending", v["file"], f"[[{ref}]]에 해당하는 기억이 아직 없다(쓸 거리로 남겨 둔 것일 수 있다)")

    stems = sorted(meta)
    for i, a in enumerate(stems):
        ta = tokens(meta[a]["desc"])
        for b in stems[i + 1:]:
            tb = tokens(meta[b]["desc"])
            if len(ta) >= 3 and len(tb) >= 3:
                j = len(ta & tb) / len(ta | tb)
                if j >= dup_threshold:
                    add("warn", "similar", meta[a]["file"], f"{meta[b]['file']}와 설명이 {j:.0%} 겹친다. 하나로 합칠지 본다")
    return issues, len(files)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Claude 파일 기억 폴더 점검")
    ap.add_argument("dir", help="MEMORY.md가 있는 폴더")
    ap.add_argument("--json", action="store_true", help="JSON으로 출력")
    ap.add_argument("--strict", action="store_true", help="경고도 종료 코드 2로")
    ap.add_argument("--max-index-lines", type=int, default=200)
    ap.add_argument("--max-line-len", type=int, default=150)
    ap.add_argument("--dup-threshold", type=float, default=0.6)
    a = ap.parse_args(argv)
    if not Path(a.dir).is_dir():
        print(f"폴더가 아니다: {a.dir}", file=sys.stderr)
        return 3
    issues, n = lint(a.dir, a.max_index_lines, a.max_line_len, a.dup_threshold)
    cnt = {k: sum(1 for i in issues if i["level"] == k) for k in ("error", "warn", "info")}
    if a.json:
        print(json.dumps({"files": n, "counts": cnt, "issues": issues}, ensure_ascii=False, indent=2))
    else:
        for i in sorted(issues, key=lambda x: ("error warn info".split().index(x["level"]), x["file"])):
            print(f"{i['level'].upper():5} {i['code']:<16} {i['file']}: {i['message']}")
        print(f"기억 파일 {n}개 · 오류 {cnt['error']} · 경고 {cnt['warn']} · 참고 {cnt['info']}")
    if cnt["error"] or (a.strict and cnt["warn"]):
        return 2
    return 1 if cnt["warn"] else 0


if __name__ == "__main__":
    sys.exit(main())

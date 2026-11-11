#!/usr/bin/env python3
"""adr-guard: Claude Code UserPromptSubmit 훅.

프롬프트를 보내기 직전에, 저장소의 ADR(설계 결정 기록) 중 "채택하지 않은(rejected /
not_adopted) 결정"과 겹치는 것을 찾아 사실 문장으로 컨텍스트에 붙인다.
표준 라이브러리만 쓴다. 모델·네트워크 호출 없음. 훅 모드는 항상 exit 0.

  훅:            echo '{"prompt":"..."}' | python3 adr_guard.py [--json]
  실행 없이 시험: python3 adr_guard.py --dry-run "프롬프트 문장"
  ADR 점검:       python3 adr_guard.py --lint
  상시 규칙 한 줄: python3 adr_guard.py --print-rule
  설정 조각:      python3 adr_guard.py --print-settings
"""
import json
import os
import re
import sys

DEFAULT_DIRS = ["docs/adr", "docs/adrs", "adr", "docs/decisions", "doc/adr"]
REJECTED = {
    "not_adopted", "not adopted", "not-adopted", "rejected", "declined",
    "wontfix", "won't fix", "withdrawn", "기각", "미채택", "채택 안 함", "채택하지 않음",
}
MAX_HITS = 3
MAX_REASON = 240
MAX_TOTAL = 3000          # 컨텍스트에 붙이는 전체 상한(훅 출력 1만 자 한계보다 한참 아래)
MIN_SHARED = 2            # 제목·keywords와 겹쳐야 하는 서로 다른 단어 수

STOP = set("""the and for with that this from into over under onto about have has had are was were will
would could should can not but you your our their its use using used make makes made add adds added
new old all any some more most less than then when what where which who how why please let lets want
need needs get gets got put set run runs file files code change changes update fix fixes implement
한다 하자 해줘 해주세요 하고 하는 있는 있다 그리고 이것 저것 코드 파일 수정 추가 변경 구현""".split())
JOSA = ("으로", "에서", "에게", "이다", "은", "는", "이", "가", "을", "를", "에", "의", "로", "와", "과", "도", "만")


def tokens(text):
    """영문 단어(3자 이상)와 한글 단어(2자 이상)를 소문자로 뽑는다. 한글은 흔한 조사를 뗀다."""
    out = set()
    for w in re.findall(r"[A-Za-z][A-Za-z0-9_+-]{2,}|[가-힣]{2,}", text or ""):
        w = w.lower()
        if re.match(r"[가-힣]", w):
            for j in JOSA:
                if w.endswith(j) and len(w) - len(j) >= 2:
                    w = w[: -len(j)]
                    break
        # 영문 복수형(-s)은 단수와 같은 단어로 센다. redis·class 같은 -is/-ss/-us 끝은 건드리지 않는다.
        if w.endswith("s") and len(w) > 4 and not w.endswith(("ss", "is", "us")):
            w = w[:-1]
        if w not in STOP:
            out.add(w)
    return out


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(200_000)
    except OSError:
        return ""


def parse_adr(path, text):
    """ADR 한 파일에서 제목·상태·사유·keywords를 뽑는다. 못 찾은 것은 빈 문자열."""
    fm = {}
    body = text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            k, sep, v = line.partition(":")
            if sep:
                fm[k.strip().lower()] = v.strip().strip("\"'")
        body = text[m.end():]
    title = fm.get("title", "")
    if not title:
        t = re.search(r"^#\s+(.+)$", body, re.M)
        title = t.group(1).strip() if t else os.path.splitext(os.path.basename(path))[0]
    status = fm.get("status", "")
    if not status:
        s = re.search(r"^[-*\s]*\**status\**\s*[:：]\s*\**(.+?)\**\s*$", body, re.I | re.M)
        if s:
            status = s.group(1)
        else:  # "## Status" 절 다음 첫 줄
            s = re.search(r"^#{1,6}\s*status\s*\n+\s*([^\n#]+)", body, re.I | re.M)
            if s:
                status = s.group(1)
    status = re.sub(r"[*`_]", " ", status).strip().lower()
    status = re.sub(r"\s+", " ", status)
    reason = fm.get("reason", "")
    if not reason:
        r = re.search(r"^[-*\s]*\**(?:reason|why|rationale|사유|이유)\**\s*[:：]\s*(.+)$", body, re.I | re.M)
        if r:
            reason = r.group(1)
    if not reason:  # "## Reason / Why / Decision / 이유" 절의 첫 문단 첫 줄
        r = re.search(r"^#{1,6}\s*(?:reason|why[^\n]*|rationale|decision|사유|이유|결정)\s*\n+\s*([^\n#][^\n]*)",
                      body, re.I | re.M)
        if r:
            reason = r.group(1)
    reason = re.sub(r"\s+", " ", re.sub(r"[*`]", "", reason)).strip()
    return {
        "path": path, "title": title.strip(), "status": status, "reason": reason,
        "keywords": fm.get("keywords", ""),
    }


def is_rejected(status):
    s = status.strip().lower()
    return s in REJECTED or any(s.startswith(r) for r in REJECTED)


def find_dirs(root, override=None):
    names = override or DEFAULT_DIRS
    return [os.path.join(root, d) for d in names if os.path.isdir(os.path.join(root, d))]


def load_config(root):
    try:
        with open(os.path.join(root, ".claude", "adr-guard.json"), encoding="utf-8") as f:
            c = json.load(f)
        return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def load_adrs(root, dirs):
    adrs = []
    for d in dirs:
        for dp, _dn, fns in os.walk(d):
            for fn in sorted(fns):
                if fn.lower().endswith(".md") and fn.lower() != "readme.md":
                    p = os.path.join(dp, fn)
                    adrs.append(parse_adr(os.path.relpath(p, root), read_text(p)))
    return adrs


def match(prompt, adrs, min_shared=MIN_SHARED):
    """프롬프트와 채택 안 된 ADR의 겹침을 점수 순으로 돌려준다."""
    pt = tokens(prompt)
    hits = []
    for a in adrs:
        if not is_rejected(a["status"]):
            continue
        at = tokens(a["title"]) | tokens(a["keywords"])
        shared = sorted(pt & at)
        need = 1 if a["keywords"] and (pt & tokens(a["keywords"])) and len(tokens(a["keywords"])) <= 3 else min_shared
        if len(shared) >= need:
            hits.append((len(shared), a, shared))
    hits.sort(key=lambda h: (-h[0], h[1]["path"]))
    return hits[:MAX_HITS]


def render(hits):
    lines = ["Rejected design decisions recorded in this repository that share words with this prompt:"]
    for _n, a, shared in hits:
        reason = a["reason"][:MAX_REASON] + ("…" if len(a["reason"]) > MAX_REASON else "")
        line = f"- {a['title']} (status: {a['status']}, {a['path']})"
        line += f" — recorded reason: {reason}" if reason else " — no reason recorded"
        line += f" [shared words: {', '.join(shared[:5])}]"
        lines.append(line)
    lines.append("Whether this prompt reopens any of them has not been checked.")
    out = "\n".join(lines)
    return out[:MAX_TOTAL]


def project_root():
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def analyze(prompt, root):
    cfg = load_config(root)
    dirs = find_dirs(root, os.environ.get("ADR_GUARD_DIR", "").split(",") if os.environ.get("ADR_GUARD_DIR") else cfg.get("dirs"))
    if not dirs:
        return ""
    min_shared = cfg.get("min_shared", MIN_SHARED)
    if not isinstance(min_shared, int) or min_shared < 1:
        min_shared = MIN_SHARED
    hits = match(prompt, load_adrs(root, dirs), min_shared)
    return render(hits) if hits else ""


def lint(root):
    cfg = load_config(root)
    dirs = find_dirs(root, os.environ.get("ADR_GUARD_DIR", "").split(",") if os.environ.get("ADR_GUARD_DIR") else cfg.get("dirs"))
    if not dirs:
        print("ADR 폴더를 찾지 못했다 (찾는 곳: " + ", ".join(DEFAULT_DIRS) + ")")
        return 1
    adrs = load_adrs(root, dirs)
    rej = [a for a in adrs if is_rejected(a["status"])]
    nostatus = [a for a in adrs if not a["status"]]
    noreason = [a for a in rej if not a["reason"]]
    print(f"ADR {len(adrs)}개 · 채택 안 됨 {len(rej)}개 · 상태 없음 {len(nostatus)}개 · 사유 없는 기각 {len(noreason)}개")
    for a in nostatus:
        print(f"  상태 없음: {a['path']}")
    for a in noreason:
        print(f"  사유 없음: {a['path']}  (한 줄이면 충분하다: 'Reason: ...')")
    return 1 if (nostatus or noreason) else 0


RULE = ("Before designing or proposing a change, check the rejected decisions in docs/adr/ "
        "(status not_adopted or rejected) and say which ones the request touches.")

SETTINGS = {
    "hooks": {
        "UserPromptSubmit": [
            {"hooks": [{"type": "command",
                        "command": "python3 \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/adr_guard.py",
                        "timeout": 10}]}
        ]
    }
}


def main(argv):
    root = project_root()
    if "--print-rule" in argv:
        print(RULE)
        return 0
    if "--print-settings" in argv:
        print(json.dumps(SETTINGS, indent=2))
        return 0
    if "--lint" in argv:
        return lint(root)
    if "--dry-run" in argv:
        i = argv.index("--dry-run")
        prompt = " ".join(a for a in argv[i + 1:] if not a.startswith("--"))
        out = analyze(prompt, root)
        print(out if out else "(겹치는 기각 결정 없음 — 훅은 아무것도 출력하지 않는다)")
        return 0
    # 훅 모드: 어떤 경우에도 exit 0
    try:
        raw = sys.stdin.read()
        try:
            data = json.loads(raw) if raw.strip() else {}
        except ValueError:
            data = {}
        prompt = data.get("prompt", "") if isinstance(data, dict) else ""
        if not isinstance(prompt, str):
            prompt = ""
        if isinstance(data, dict) and isinstance(data.get("cwd"), str) and not os.environ.get("CLAUDE_PROJECT_DIR"):
            root = data["cwd"]
        out = analyze(prompt, root) if prompt else ""
        if out:
            if "--json" in argv:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                         "additionalContext": out}}, ensure_ascii=False))
            else:
                print(out)
    except BaseException:  # noqa: BLE001 — 훅은 프롬프트를 막지 않는다
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

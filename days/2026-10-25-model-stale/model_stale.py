#!/usr/bin/env python3
"""model-stale — 저장소에 박힌 Claude 모델 ID가 퇴역·퇴역 예정·구형인지 날짜 기준으로 점검한다.

표준 라이브러리만 쓴다. 키·모델 호출 없음. 모델 수명주기 표(models.json)는
공식 "Model deprecations" 페이지에서 `--import`로 갱신한다.

규칙
  M01 error  퇴역(Retired)한 모델 — 요청이 실패한다
  M02 error  Deprecated 모델의 퇴역일이 지났다 / warn 퇴역일이 남았다(남은 날수 표시)
  M03 warn   Active지만 "가장 이른 퇴역일"이 지났거나 --warn-days 안이다
  M04 info   같은 계열에 더 새 모델이 있다 (구형이지만 아직 서비스 중)
  M05 warn   표에 없는 claude-* ID (오타이거나 표보다 새 모델)
  M06 info   날짜가 박힌 ID인데 날짜 없는 별칭이 있다

종료 코드: 0=--min-level 이상 없음, 1=있음, 2=사용법 오류.
"""
import argparse
import datetime as dt
import fnmatch
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TABLE = os.path.join(HERE, "models.json")
LEVELS = {"info": 0, "warn": 1, "error": 2}
FAMILIES = ("opus", "sonnet", "haiku", "fable", "mythos")
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next", "target"}
MAX_BYTES = 2_000_000
ALLOW_MARK = "model-stale: allow"
TABLE_STALE_DAYS = 45

ID_RE = re.compile(
    r"(?<![A-Za-z0-9_.\-])"
    r"((?:(?:global|us|eu|apac|jp|au|us-gov)\.)?(?:anthropic\.)?"
    r"claude-(?:(?:instant-)?\d\.\d"
    r"|(?:\d(?:[.\-]\d)?-)?(?:opus|sonnet|haiku|fable|mythos)"
    r"(?:-\d{1,2}){0,2}(?:-\d{8}|@\d{8}|-latest|-preview)?)"
    r"(?:-v\d+:\d+)?)"
    r"(?![A-Za-z0-9])"
)
REGION_RE = re.compile(r"^(?:global|us|eu|apac|jp|au|us-gov)\.")


# ---------- 표 ----------

def parse_date(s):
    return dt.date.fromisoformat(s) if s else None


def family_of(mid):
    for f in FAMILIES:
        if "-" + f in mid or mid.startswith(f):
            return f
    return "legacy"


def version_of(mid):
    """(major, minor) — 날짜·계열 이름을 뺀 숫자. 없으면 (0, 0)."""
    s = re.sub(r"[-@]\d{8}$", "", mid)
    s = s.replace("claude-", "", 1)
    for f in FAMILIES + ("instant",):
        s = s.replace(f, "")
    nums = [int(n) for n in re.findall(r"\d+", s)]
    nums = (nums + [0, 0])[:2]
    return tuple(nums)


def undated(mid):
    return re.sub(r"-\d{8}$", "", mid)


class Table:
    def __init__(self, data):
        self.data = data
        self.as_of = parse_date(data["as_of"])
        self.models = data["models"]
        self.index = {}
        extra = data.get("extra_aliases", {})
        for m in self.models:
            names = {m["id"]}
            if re.search(r"-\d{8}$", m["id"]):
                u = undated(m["id"])
                names |= {u, u + "-latest"}
            names |= set(extra.get(m["id"], []))
            m["_names"] = names
        for m in self.models:  # 같은 별칭이 겹치면 목록 앞쪽(더 새 것)이 이긴다
            for n in m["_names"]:
                self.index.setdefault(n, m)
        self.latest = {}
        for m in self.models:
            if m["state"] != "active":
                continue
            f = family_of(m["id"])
            if f not in self.latest or version_of(m["id"]) > version_of(self.latest[f]["id"]):
                self.latest[f] = m

    def lookup(self, mid):
        return self.index.get(mid)


def load_table(path):
    with open(path, encoding="utf-8") as f:
        return Table(json.load(f))


# ---------- 정규화 ----------

def normalize(raw):
    """원문 토큰 → (정규 ID, 플랫폼). 플랫폼: api / bedrock / vertex."""
    s = raw
    platform = "api"
    if REGION_RE.match(s):
        s = REGION_RE.sub("", s)
        platform = "bedrock"
    if s.startswith("anthropic."):
        s = s[len("anthropic."):]
        platform = "bedrock"
    s = re.sub(r"-v\d+:\d+$", "", s)
    m = re.search(r"@(\d{8})$", s)
    if m:
        s = s[: m.start()] + "-" + m.group(1)
        platform = "vertex"
    return s, platform


# ---------- 판정 ----------

def suggestion(m, table):
    """권장 이전 대상: 계열 최신. 문서가 다른 모델을 권하면 괄호로 덧붙인다."""
    doc = m.get("replacement")
    newest = table.latest.get(family_of(m["id"]))
    if newest is None:
        return doc
    if doc and doc != newest["id"]:
        return "%s (문서 권장: %s)" % (newest["id"], doc)
    return newest["id"]


def judge(raw, table, today, warn_days):
    """토큰 하나 → [(rule, level, message, suggestion)]."""
    mid, platform = normalize(raw)
    m = table.lookup(mid)
    if m is None:
        return [("M05", "warn", "표에 없는 모델 ID — 오타이거나 표(%s 기준)보다 새 모델" % table.as_of, None)], None
    out = []
    state = m["state"]
    rep = suggestion(m, table)
    retires = parse_date(m.get("retires"))
    tent = m.get("retires_tentative")
    if state == "retired":
        out.append(("M01", "error", "퇴역한 모델 (%s) — 요청이 실패한다" % (retires or "날짜 미상"), rep))
    elif state == "deprecated":
        if retires is None:
            out.append(("M02", "warn", "Deprecated, 퇴역일 미정", rep))
        elif retires <= today:
            out.append(("M02", "error", "Deprecated 모델의 퇴역일(%s)이 지났다" % retires, rep))
        else:
            out.append(("M02", "warn", "Deprecated — %s 퇴역(D-%d)" % (retires, (retires - today).days), rep))
    elif state == "active":
        if retires is not None and (retires - today).days <= warn_days:
            if retires <= today:
                out.append(("M03", "warn", "가장 이른 퇴역일(%s)이 지났다 — 아직 서비스 중이지만 언제든 퇴역할 수 있다" % retires,
                            table.latest.get(family_of(m["id"]), m)["id"]))
            else:
                out.append(("M03", "warn", "가장 이른 퇴역일 %s (D-%d)" % (retires, (retires - today).days),
                            table.latest.get(family_of(m["id"]), m)["id"]))
        newest = table.latest.get(family_of(m["id"]))
        if not out and newest and version_of(newest["id"]) > version_of(m["id"]):
            out.append(("M04", "info", "같은 계열에 더 새 모델이 있다", newest["id"]))
    if platform == "api" and re.search(r"-\d{8}$", mid) and state == "active" and raw == mid:
        out.append(("M06", "info", "날짜가 박힌 ID — 별칭 사용 권장", undated(mid)))
    return out, m


# ---------- 스캔 ----------

def iter_files(paths, excludes):
    for p in paths:
        if os.path.isfile(p):
            yield p
            continue
        for root, dirs, files in os.walk(p):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not any(fnmatch.fnmatch(d, g) for g in excludes))
            for fn in sorted(files):
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, p)
                if any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(fn, g) for g in excludes):
                    continue
                yield full


def read_text(path):
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return None
        with open(path, "rb") as f:
            b = f.read()
    except OSError:
        return None
    if b"\0" in b[:4096]:
        return None
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return None


def scan(paths, table, today, warn_days, excludes):
    findings = []
    for path in iter_files(paths, excludes):
        text = read_text(path)
        if text is None or "claude-" not in text:
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if "claude-" not in line:
                continue
            if ALLOW_MARK in line or (i > 0 and ALLOW_MARK in lines[i - 1]):
                continue
            for mt in ID_RE.finditer(line):
                raw = mt.group(1)
                res, _ = judge(raw, table, today, warn_days)
                for rule, level, msg, sug in res:
                    findings.append({"file": path, "line": i + 1, "id": raw, "rule": rule,
                                     "level": level, "message": msg, "suggest": sug,
                                     "text": line.strip()[:160]})
    return findings


# ---------- 표 갱신 ----------

MONTHS = "%B %d, %Y"
STATUS_RE = re.compile(r"^\|\s*(claude-[\w.\-]+)\s*\|\s*(Active|Deprecated|Retired|Legacy)\s*\|([^|]*)\|([^|]*)\|")
HISTORY_RE = re.compile(r"^\|\s*([A-Z][a-z]+ \d{1,2}, \d{4})\s*\|\s*`(claude-[^`]+)`\s*\|\s*`(claude-[^`]+)`\s*\|")


def _date(s):
    s = s.strip()
    m = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", s)
    if not m:
        return None
    return dt.datetime.strptime(m.group(1), MONTHS).date().isoformat()


def parse_deprecations(md):
    status, hist = {}, {}
    for line in md.splitlines():
        m = STATUS_RE.match(line)
        if m:
            mid, state, dep, ret = m.groups()
            status[mid] = {"state": state.lower(), "deprecated": _date(dep), "retires": _date(ret),
                           "retires_tentative": "not sooner than" in ret.lower()}
            continue
        m = HISTORY_RE.match(line)
        if m:
            when, mid, rep = m.groups()
            hist[mid] = {"retires": dt.datetime.strptime(when, MONTHS).date().isoformat(), "replacement": rep}
    return status, hist


def import_table(md, table_path, today):
    status, hist = parse_deprecations(md)
    if not status:
        raise ValueError("Model status 표를 찾지 못했다 — 페이지 형식이 바뀌었을 수 있다")
    try:
        with open(table_path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {"models": [], "extra_aliases": {}}
    by_id = {m["id"]: m for m in data["models"]}
    added, changed = [], []
    for mid, st in status.items():
        row = by_id.get(mid)
        if row is None:
            row = {"id": mid}
            by_id[mid] = row
            added.append(mid)
        before = {k: row.get(k) for k in ("state", "deprecated", "retires", "retires_tentative")}
        row.update(st)
        if mid in hist:
            row["replacement"] = hist[mid]["replacement"]
        if before != {k: row.get(k) for k in before} and mid not in added:
            changed.append(mid)
    for mid, h in hist.items():  # 상태 표에서 빠진 옛 모델은 퇴역으로 보존
        if mid not in by_id:
            by_id[mid] = {"id": mid, "state": "retired", "deprecated": None, "retires": h["retires"],
                          "retires_tentative": False, "replacement": h["replacement"]}
            added.append(mid)
    models = sorted(by_id.values(), key=lambda m: (family_of(m["id"]), version_of(m["id"]), m["id"]), reverse=True)
    for m in models:
        m.pop("_names", None)
    data.update({"as_of": today.isoformat(), "source": "https://platform.claude.com/docs/en/about-claude/model-deprecations",
                 "models": models})
    with open(table_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return added, changed


# ---------- 출력 ----------

def render(findings, table, today, show_summary):
    out = []
    age = (today - table.as_of).days
    if age > TABLE_STALE_DAYS:
        out.append("⚠ 모델 표가 %d일 전(%s) 기준이다 — `--import`로 갱신하라" % (age, table.as_of))
    for f in sorted(findings, key=lambda x: (-LEVELS[x["level"]], x["file"], x["line"])):
        sug = " → %s" % f["suggest"] if f["suggest"] else ""
        out.append("%-5s %s %s:%d  %s  %s%s" % (f["level"], f["rule"], f["file"], f["line"], f["id"], f["message"], sug))
    if show_summary and findings:
        agg = {}
        for f in findings:
            a = agg.setdefault(f["id"], {"n": 0, "worst": "info", "files": set()})
            a["n"] += 1
            a["files"].add(f["file"])
            if LEVELS[f["level"]] > LEVELS[a["worst"]]:
                a["worst"] = f["level"]
        out.append("")
        out.append("| 모델 ID | 최고 수준 | 건수 | 파일 수 |")
        out.append("|---|---|---|---|")
        for k, a in sorted(agg.items(), key=lambda kv: (-LEVELS[kv[1]["worst"]], -kv[1]["n"])):
            out.append("| `%s` | %s | %d | %d |" % (k, a["worst"], a["n"], len(a["files"])))
    counts = {l: sum(1 for f in findings if f["level"] == l) for l in LEVELS}
    out.append("")
    out.append("error %d · warn %d · info %d (기준일 %s, 표 %s)" % (counts["error"], counts["warn"], counts["info"], today, table.as_of))
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="저장소의 Claude 모델 ID 수명주기 점검")
    ap.add_argument("paths", nargs="*", help="파일·폴더 (기본: .)")
    ap.add_argument("--table", default=DEFAULT_TABLE, help="모델 표 JSON (기본: 스크립트 옆 models.json)")
    ap.add_argument("--today", help="기준일 YYYY-MM-DD (기본: 오늘, 테스트용)")
    ap.add_argument("--warn-days", type=int, default=90, help="M03 경고 창 (기본 90일)")
    ap.add_argument("--min-level", choices=list(LEVELS), default="error", help="이 수준 이상이 있으면 exit 1")
    ap.add_argument("--ignore", default="", help="끌 규칙, 쉼표 구분 (예: M04,M06)")
    ap.add_argument("--exclude", action="append", default=[], help="제외 glob (여러 번 가능)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--summary", action="store_true", help="모델 ID별 요약 표를 덧붙인다")
    ap.add_argument("--import", dest="imp", metavar="FILE|URL|live",
                    help="Model deprecations 페이지(.md)로 표를 갱신한다. live=공식 URL")
    args = ap.parse_intermixed_args(argv)

    try:
        today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    except ValueError:
        print("--today는 YYYY-MM-DD", file=sys.stderr)
        return 2

    if args.imp:
        src = args.imp
        if src == "live":
            src = "https://platform.claude.com/docs/en/about-claude/model-deprecations.md"
        try:
            if src.startswith("http"):
                req = urllib.request.Request(src, headers={"User-Agent": "model-stale/1.0 (+curl-compatible)"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    md = r.read().decode("utf-8")
            else:
                with open(src, encoding="utf-8") as f:
                    md = f.read()
            added, changed = import_table(md, args.table, today)
        except (OSError, ValueError) as e:
            print("import 실패: %s" % e, file=sys.stderr)
            return 2
        print("표 갱신: 추가 %d %s · 변경 %d %s" % (len(added), added, len(changed), changed))
        return 0

    ignore = {r.strip().upper() for r in args.ignore.split(",") if r.strip()}
    bad = ignore - {"M01", "M02", "M03", "M04", "M05", "M06"}
    if bad:
        print("모르는 규칙: %s" % ", ".join(sorted(bad)), file=sys.stderr)
        return 2
    paths = args.paths or ["."]
    for p in paths:
        if not os.path.exists(p):
            print("경로 없음: %s" % p, file=sys.stderr)
            return 2
    try:
        table = load_table(args.table)
    except (OSError, ValueError, KeyError) as e:
        print("표를 읽지 못했다: %s" % e, file=sys.stderr)
        return 2

    findings = [f for f in scan(paths, table, today, args.warn_days, args.exclude) if f["rule"] not in ignore]
    if args.json:
        print(json.dumps({"today": today.isoformat(), "table_as_of": table.as_of.isoformat(), "findings": findings},
                         ensure_ascii=False, indent=1))
    else:
        print(render(findings, table, today, args.summary))
    gate = LEVELS[args.min_level]
    return 1 if any(LEVELS[f["level"]] >= gate for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())

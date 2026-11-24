#!/usr/bin/env python3
"""approvals-walk: 승인 정책 파일(.claude/approvals.yml)을 오프라인으로 걸어 보는 시뮬레이터.

변경 파일 목록과 코드 리뷰 결과(pass/fail/error/incomplete/none)를 주면,
파일마다 어떤 규칙이 적용되고 PR 전체가 몇 명의 승인과 어떤 Claude 판정을 요구하는지 표로 보여 준다.
Claude Approvals 스킬 문서의 "How a policy decides"를 옮긴 근사치이며 서버 판정의 대체물이 아니다.
표준 라이브러리만 쓴다. 키·모델·네트워크 없음.
"""
import argparse
import json
import re
import sys

LEVELS = ["none", "minimal", "low", "medium", "high", "critical"]
CLAUDE_RANK = {"approves": 0, "comments": 1, "blocks": 2}
RESULTS = ["pass", "fail", "error", "incomplete", "none"]
# 문서가 보호 파일로 못 박은 것들만. 목록은 Anthropic이 바꿀 수 있어 이 이상 믿지 않는다.
PROTECTED = ["**/.claude/approvals.yml", "**/approvals.yml", ".claude/classifiers/**",
             "**/.gitattributes", "**/.gitmodules", "REVIEW.md"]

FILE_KEYS = {"version", "mode", "nested", "run", "locals", "rules"}
RULE_KEYS = {"purpose", "paths", "verdict", "if", "override", "advisory", "reuse", "use",
             "mode", "nested", "run", "findings"}
OVERRIDE_KEYS = {"if", "verdict", "reuse", "findings", "purpose", "use"}
VERDICT_KEYS = {"claude", "seats", "max_age"}
NOT_SIMULATED = ["use", "nested", "locals", "run", "reuse", "findings", "advisory"]


class PolicyError(Exception):
    pass


# ---------------------------------------------------------------- 작은 YAML 파서
def _strip_comment(line):
    out, q = [], None
    for i, ch in enumerate(line):
        if q:
            out.append(ch)
            if ch == q and not (q == '"' and line[i - 1] == "\\"):
                q = None
        elif ch in "\"'":
            q = ch
            out.append(ch)
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def _scalar(text):
    t = text.strip()
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    if t in ("true", "false"):
        return t == "true"
    if t in ("null", "~", ""):
        return None
    return t


class _Flow:
    def __init__(self, text):
        self.t, self.i = text, 0

    def ws(self):
        while self.i < len(self.t) and self.t[self.i] in " \t":
            self.i += 1

    def value(self):
        self.ws()
        c = self.t[self.i] if self.i < len(self.t) else ""
        if c == "{":
            return self.map()
        if c == "[":
            return self.seq()
        if c in ("'", '"'):
            return self.quoted()
        return self.plain()

    def quoted(self):
        q, buf = self.t[self.i], []
        self.i += 1
        while self.i < len(self.t):
            c = self.t[self.i]
            if q == '"' and c == "\\" and self.i + 1 < len(self.t):
                buf.append(self.t[self.i + 1])
                self.i += 2
                continue
            if c == q:
                if q == "'" and self.t[self.i + 1:self.i + 2] == "'":
                    buf.append("'")
                    self.i += 2
                    continue
                self.i += 1
                return "".join(buf)
            buf.append(c)
            self.i += 1
        raise PolicyError("따옴표가 닫히지 않았다: " + self.t)

    def plain(self, stops=",}]"):
        j = self.i
        while j < len(self.t) and self.t[j] not in stops:
            j += 1
        s = self.t[self.i:j]
        self.i = j
        return _scalar(s)

    def seq(self):
        self.i += 1
        out = []
        while True:
            self.ws()
            if self.i >= len(self.t):
                raise PolicyError("] 가 없다: " + self.t)
            if self.t[self.i] == "]":
                self.i += 1
                return out
            out.append(self.value())
            self.ws()
            if self.t[self.i:self.i + 1] == ",":
                self.i += 1

    def map(self):
        self.i += 1
        out = {}
        while True:
            self.ws()
            if self.i >= len(self.t):
                raise PolicyError("} 가 없다: " + self.t)
            if self.t[self.i] == "}":
                self.i += 1
                return out
            if self.t[self.i] in "\"'":
                key = self.quoted()
            else:
                j = self.t.find(":", self.i)
                if j < 0:
                    raise PolicyError("키 뒤에 : 가 없다: " + self.t)
                key, self.i = self.t[self.i:j].strip(), j
            self.ws()
            if self.t[self.i:self.i + 1] != ":":
                raise PolicyError("키 뒤에 : 가 없다: " + self.t)
            self.i += 1
            out[key] = self.value()
            self.ws()
            if self.t[self.i:self.i + 1] == ",":
                self.i += 1


def _inline(text):
    t = text.strip()
    if t[:1] in ("{", "[", '"', "'"):
        f = _Flow(t)
        v = f.value()
        f.ws()
        if f.i != len(t):
            raise PolicyError("값 뒤에 남은 글자: " + t[f.i:])
        return v
    return _scalar(t)


_KEY = re.compile(r"""^("[^"]*"|'[^']*'|[^:\s{\["'][^:]*?):(?:\s+(.*))?$""")


def _split_key(text):
    m = _KEY.match(text)
    if not m:
        return None
    return m.group(1).strip("\"'"), (m.group(2) or "").strip()


def _is_item(text):
    return text == "-" or text.startswith("- ")


def _block(lines, i, ind):
    if _is_item(lines[i][1]):
        res = []
        while i < len(lines) and lines[i][0] == ind and _is_item(lines[i][1]):
            body = lines[i][1][1:].lstrip()
            if body == "":
                i += 1
                v, i = _block(lines, i, lines[i][0])
                res.append(v)
                continue
            off = ind + (len(lines[i][1]) - len(body))
            lines[i] = (off, body)
            if _split_key(body):
                v, i = _block(lines, i, off)
            else:
                v, i = _inline(body), i + 1
            res.append(v)
        return res, i
    res = {}
    while i < len(lines) and lines[i][0] == ind and not _is_item(lines[i][1]):
        kv = _split_key(lines[i][1])
        if not kv:
            raise PolicyError("키: 값 꼴이 아닌 줄: " + lines[i][1])
        key, rest = kv
        if rest == "":
            i += 1
            if i < len(lines) and (lines[i][0] > ind or (lines[i][0] == ind and _is_item(lines[i][1]))):
                v, i = _block(lines, i, lines[i][0])
            else:
                v = None
        else:
            v, i = _inline(rest), i + 1
        res[key] = v
    return res, i


def parse_yaml(text):
    lines = []
    for raw in text.splitlines():
        s = _strip_comment(raw.replace("\t", "  "))
        if s.strip() in ("", "---"):
            continue
        lines.append((len(s) - len(s.lstrip(" ")), s.strip()))
    if not lines:
        return {}
    val, i = _block(lines, 0, lines[0][0])
    if i != len(lines):
        raise PolicyError("해석하지 못한 줄: " + lines[i][1])
    return val


# ---------------------------------------------------------------- 정책 검증
def _check_keys(obj, allowed, where):
    for k in obj:
        if k not in allowed:
            raise PolicyError("모르는 키 '%s' (%s) — 제품은 모르는 키가 하나라도 있으면 파일 전체를 거부한다" % (k, where))


def _check_verdict(v, where):
    if not isinstance(v, dict):
        raise PolicyError("%s: verdict는 { claude, seats } 꼴이어야 한다" % where)
    _check_keys(v, VERDICT_KEYS, where + " verdict")
    if "claude" in v and v["claude"] not in CLAUDE_RANK:
        raise PolicyError("%s: claude는 approves·comments·blocks 중 하나여야 한다 (받은 값: %r)" % (where, v["claude"]))


def load_policy(text):
    doc = parse_yaml(text)
    if not isinstance(doc, dict):
        raise PolicyError("최상위는 매핑이어야 한다")
    _check_keys(doc, FILE_KEYS, "파일 최상위")
    if doc.get("version") != 1:
        raise PolicyError("version: 1 이 필요하다")
    rules = doc.get("rules")
    if not isinstance(rules, list) or not rules:
        raise PolicyError("rules 목록이 비어 있다")
    for n, r in enumerate(rules, 1):
        where = "규칙 %d" % n
        if not isinstance(r, dict):
            raise PolicyError(where + "은 매핑이어야 한다")
        _check_keys(r, RULE_KEYS, where)
        if "purpose" not in r or "paths" not in r:
            raise PolicyError(where + ": purpose와 paths는 필수다")
        if not isinstance(r["paths"], list):
            raise PolicyError(where + ": paths는 목록이어야 한다")
        if "verdict" in r:
            _check_verdict(r["verdict"], where)
        for m, o in enumerate(r.get("override") or [], 1):
            w = "%s override %d" % (where, m)
            if not isinstance(o, dict) or "if" not in o:
                raise PolicyError(w + ": if가 필수다")
            _check_keys(o, OVERRIDE_KEYS, w)
            if "verdict" in o:
                _check_verdict(o["verdict"], w)
    return doc


# ---------------------------------------------------------------- 경로 글롭
def _glob_body(p):
    i, out = 0, ""
    while i < len(p):
        c = p[i]
        if p.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif p.startswith("**", i):
            out += ".*"
            i += 2
        elif c == "*":
            out += "[^/]*"
            i += 1
        elif c == "?":
            out += "[^/]"
            i += 1
        elif c == "{":
            j = p.find("}", i)
            if j < 0:
                out += re.escape(c)
                i += 1
            else:
                out += "(?:" + "|".join(_glob_body(a) for a in p[i + 1:j].split(",")) + ")"
                i = j + 1
        else:
            out += re.escape(c)
            i += 1
    return out


def glob_match(pattern, path):
    return re.fullmatch(_glob_body(pattern), path) is not None


def paths_match(patterns, path):
    pos = [p for p in patterns if not str(p).startswith("!")]
    neg = [p[1:] for p in patterns if str(p).startswith("!")]
    return any(glob_match(p, path) for p in pos) and not any(glob_match(n, path) for n in neg)


# ---------------------------------------------------------------- 조건 평가 (3값 논리: True/False/None=결과 없음)
def _cmp(a, op, b):
    return {"=": a == b, "!=": a != b, "<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]


def _atom(text, facts, notes):
    t = text.strip()
    m = re.fullmatch(r"claude/code_review\s*(=|!=)\s*(\w+)", t)
    if m:
        op, want = m.groups()
        r = facts["review"]
        if want in ("error", "incomplete"):
            if r in ("error", "incomplete"):
                return _cmp(r, op, want)
            return None if r == "none" else (op == "!=")
        if r in ("pass", "fail"):
            return _cmp(r, op, want)
        return None  # error·incomplete·none 은 결과 없음
    m = re.fullmatch(r"claude/code_review\.severity\s*(<=|>=|<|>|=|!=)\s*(\w+)", t)
    if m:
        op, want = m.groups()
        if want not in LEVELS:
            raise PolicyError("모르는 심각도 '%s' (%s)" % (want, ", ".join(LEVELS)))
        if facts["severity"] is None:
            return None
        return _cmp(LEVELS.index(facts["severity"]), op, LEVELS.index(want))
    m = re.fullmatch(r"pr/(diff_lines|files_changed)\s*(<=|>=|<|>|=|!=)\s*(\d+)", t)
    if m:
        name, op, n = m.groups()
        return _cmp(facts[name], op, int(n))
    m = re.fullmatch(r"(ALL|ANY)\s+pr/authors\s*=\s*(.+)", t)
    if m:
        q, rhs = m.groups()
        want = _inline(rhs)
        want = want if isinstance(want, list) else [want]
        hits = [a in want for a in facts["authors"]]
        return all(hits) if q == "ALL" else any(hits)
    m = re.fullmatch(r"pr/base\s*=\s*'(.*)'", t)
    if m:
        return glob_match(m.group(1), facts["base"])
    notes.add("시뮬레이션하지 않는 조건 '%s' — 결과 없음으로 취급했다" % t)
    return None


def eval_cond(text, facts, notes):
    ors = []
    for part in re.split(r"\s+OR\s+", str(text)):
        vals = [_atom(a, facts, notes) for a in re.split(r"\s+AND\s+", part)]
        ors.append(False if False in vals else (None if None in vals else True))
    return True if True in ors else (None if None in ors else False)


# ---------------------------------------------------------------- 판정
def seats_of(seats):
    """seats 값을 (인원, 작성자 제외 여부)로 줄인다."""
    if seats is None:
        return 0, False
    if isinstance(seats, int):
        return seats, False
    if isinstance(seats, list):
        n, indep = 0, False
        for s in seats:
            if isinstance(s, int):
                n += s
            elif isinstance(s, dict):
                n += int(s.get("count", 1))
                indep = indep or "!pr/authors" in (s.get("from") or [])
        return n, indep
    return 0, False


def decide_file(policy, path, facts, notes):
    matched, applied, red = False, [], None
    for idx, rule in enumerate(policy["rules"], 1):
        if "verdict" not in rule:
            if "use" in rule:
                notes.add("규칙 %d는 use로 verdict를 가져오는 것 같다 — use는 시뮬레이션하지 않아 건너뛴다" % idx)
            continue
        if not paths_match(rule["paths"], path):
            continue
        matched = True
        if "if" in rule:
            v = eval_cond(rule["if"], facts, notes)
            if v is None:
                red = "규칙 %d의 if가 결과 없는 비교라 체크가 빨개진다" % idx
                continue
            if not v:
                continue
        verdict = dict(rule["verdict"])
        via = None
        for k, o in enumerate(rule.get("override") or [], 1):
            v = eval_cond(o["if"], facts, notes)
            if v is None:
                break  # 결과가 필요한 첫 override에서 읽기를 멈추고 규칙 기본 판정이 남는다
            if v:
                verdict.update(o.get("verdict") or {})
                via = k
                break
        applied.append({"rule": idx, "purpose": rule["purpose"], "override": via,
                        "claude": verdict.get("claude", "comments"), "seats": verdict.get("seats", 0)})
    protected = any(glob_match(p, path) for p in PROTECTED)
    if not applied:
        status = "red" if (matched or red) else "unreviewed"
        return {"path": path, "status": status, "why": red, "protected": protected, "rules": []}
    claude = max((a["claude"] for a in applied), key=lambda c: CLAUDE_RANK[c])
    n, indep = 0, False
    for a in applied:
        k, i = seats_of(a["seats"])
        if k > n or (k == n and i):
            n, indep = k, i
    return {"path": path, "status": "ok", "claude": claude, "seats": n, "independent": indep,
            "protected": protected, "rules": applied}


def walk(policy, files, review, severity=None, diff_lines=0, authors=("human",), base="main"):
    notes = set()
    if severity is None and review == "pass":
        severity = "none"  # 가정: 통과한 리뷰에는 열린 지적이 없다. --severity 로 덮어쓴다
        notes.add("review=pass 이고 --severity 가 없어 가장 높은 심각도를 none 으로 가정했다")
    facts = {"review": review, "severity": severity, "diff_lines": diff_lines,
             "files_changed": len(files), "authors": list(authors), "base": base}
    per = [decide_file(policy, f, facts, notes) for f in files]
    res = {"review": review, "files": per}
    if policy.get("mode") == "observe":
        res.update(state="neutral", summary="관찰 모드 — 아무것도 결정하지 않는다(체크는 보통 neutral로 끝나 통과로 센다)")
        res["notes"] = sorted(notes)
        return res
    reds = [p for p in per if p["status"] == "red"]
    ok = [p for p in per if p["status"] == "ok"]
    unrev = [p for p in per if p["status"] == "unreviewed"]
    for p in unrev:
        if p["protected"]:
            p["status"] = "protected-only"
    prot_only = [p for p in per if p["status"] == "protected-only"]
    res["unreviewed"] = [p["path"] for p in unrev if p["status"] == "unreviewed"]
    if reds:
        res.update(state="red", summary="체크가 빨개진다: " + "; ".join(
            "%s (%s)" % (p["path"], p["why"] or "맞는 규칙이 있지만 if가 모두 거짓") for p in reds))
    elif any(p.get("claude") == "blocks" for p in ok):
        names = ", ".join(p["path"] for p in ok if p["claude"] == "blocks")
        res.update(state="blocked", summary="막힘(blocks) — 누가 승인해도 빨갛다: " + names)
    elif not ok and not prot_only:
        res.update(state="neutral", summary="파일을 맞춘 규칙이 하나도 없다 — 체크가 neutral로 끝나 아무도 심사하지 않은 채 병합될 수 있다")
    else:
        seats = max([p["seats"] for p in ok] + [1 if p["protected"] else 0 for p in per] + [0])
        indep = any(p.get("independent") and p["seats"] == seats for p in ok)
        claude_ok = bool(ok) and all(p["claude"] == "approves" for p in ok) \
            and not any(p["protected"] for p in per) and not unrev
        res.update(state="needs", seats=seats, independent=indep, claude_may_approve=claude_ok)
        res["summary"] = "승인 %d명 필요%s · %s" % (
            seats, "(작성자 제외)" if indep else "",
            "Claude가 승인할 수 있음" if claude_ok else "Claude는 댓글만(승인 못 함)")
    if res.get("unreviewed"):
        res["summary"] += " · 무심사 파일 %d개" % len(res["unreviewed"])
    if any(p["protected"] for p in per):
        res["summary"] += " · 보호 파일 포함(사람 한 명 필수, 봇은 안 셈)"
    res["notes"] = sorted(notes)
    return res


# ---------------------------------------------------------------- CLI
def build_parser():
    ap = argparse.ArgumentParser(description="승인 정책 파일을 오프라인으로 걸어 보는 시뮬레이터")
    ap.add_argument("policy", help=".claude/approvals.yml 경로")
    ap.add_argument("--files", action="append", default=[], help="변경 파일(쉼표 구분, 여러 번 가능)")
    ap.add_argument("--files-from", help="변경 파일 목록 파일(한 줄에 하나, - 는 표준입력)")
    ap.add_argument("--review", default="all", help="all 또는 %s" % "|".join(RESULTS))
    ap.add_argument("--severity", choices=LEVELS, help="코드 리뷰가 남긴 가장 높은 심각도(생략 시 pass는 none, 그 밖은 결과 없음)")
    ap.add_argument("--diff-lines", type=int, default=0)
    ap.add_argument("--author", action="append", default=[], help="human 또는 bot:dependabot (여러 번 가능)")
    ap.add_argument("--base", default="main", help="대상 브랜치 (pr/base 조건용)")
    ap.add_argument("--json", action="store_true", help="JSON으로 출력")
    ap.add_argument("-v", "--verbose", action="store_true", help="파일별 적용 규칙도 출력")
    ap.add_argument("--strict", action="store_true", help="빨강·막힘·무심사 파일이 하나라도 있으면 exit 1")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        with open(args.policy, encoding="utf-8") as f:
            policy = load_policy(f.read())
    except (OSError, PolicyError) as e:
        print("정책 파일을 읽지 못했다: %s" % e, file=sys.stderr)
        return 2
    files = [x.strip() for chunk in args.files for x in chunk.split(",") if x.strip()]
    if args.files_from:
        src = sys.stdin if args.files_from == "-" else open(args.files_from, encoding="utf-8")
        files += [l.strip() for l in src.read().splitlines() if l.strip()]
    if not files:
        print("변경 파일이 없다: --files 또는 --files-from 을 준다", file=sys.stderr)
        return 2
    reviews = RESULTS if args.review == "all" else [args.review]
    if any(r not in RESULTS for r in reviews):
        print("--review는 all 또는 %s 중 하나" % "|".join(RESULTS), file=sys.stderr)
        return 2
    try:
        results = [walk(policy, files, r, args.severity, args.diff_lines, args.author or ["human"], args.base)
                   for r in reviews]
    except PolicyError as e:
        print("정책을 평가하지 못했다: %s" % e, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        mode = "관찰(observe)" if policy.get("mode") == "observe" else "적용(enforce)"
        print("정책: %s [%s]   PR: 파일 %d개, diff %d줄, 작성자 %s" % (
            args.policy, mode, len(files), args.diff_lines, ",".join(args.author or ["human"])))
        for r in results:
            print("  review=%-10s → %s" % (r["review"], r["summary"]))
            if args.verbose:
                for p in r["files"]:
                    if p["status"] == "ok":
                        rules = ", ".join("규칙%d%s" % (a["rule"], "+override%d" % a["override"] if a["override"] else "")
                                         for a in p["rules"])
                        print("      %-34s claude=%-8s seats=%s  (%s)" % (p["path"], p["claude"], p["seats"], rules))
                    else:
                        print("      %-34s %s" % (p["path"], p["status"]))
        notes = sorted({n for r in results for n in r["notes"]})
        for n in notes:
            print("  ※ " + n)
        print("  ※ 작성자는 승인하지 않아도 자리 하나를 채운다(seats: 1은 작성자 혼자로 충족). 서버 판정의 근사치다.")
    bad = any(r["state"] in ("red", "blocked") or r.get("unreviewed") for r in results)
    return 1 if (args.strict and bad) else 0


if __name__ == "__main__":
    sys.exit(main())

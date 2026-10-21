#!/usr/bin/env python3
"""home-canary: 스크립트의 '진짜 홈 삭제' 사고를 막는 두 가지 도구.

  lint PATH...   셸 스크립트에서 가드 없는 `rm -r… $변수`와, 그런 스크립트에
                 진짜 경로($HOME, ~, /)를 넘기는 테스트를 찾는다. (정적)
  run -- CMD...  임시 가짜 HOME에 미끼 파일을 심고 CMD를 돌린 뒤, 미끼가
                 지워지거나 바뀌었는지 확인한다. (동적)

종료 코드: lint 0=깨끗 1=지적 있음 / run: 미끼 훼손 3, 그 외 CMD의 종료 코드.
표준 라이브러리만 쓴다.
"""
import argparse, hashlib, json, os, re, subprocess, sys, tempfile

CANARIES = {
    ".ssh/id_canary": "not a real key\n",
    "Documents/notes.txt": "canary: do not delete\n",
    "work/project/.git/HEAD": "ref: refs/heads/main\n",
    "work/project/src/main.txt": "canary source\n",
    ".config/app/settings.json": '{"canary": true}\n',
}

# 명령 위치(줄 머리, ; & | ( { ' " 뒤)의 rm + 재귀 옵션. 뒤따르는 인자는 rm_targets()가 따로 본다
RM_CMD = re.compile(r"""(?:^|[;&|({'"`]|\bdo\b|\bthen\b)\s*rm\s+(?:-[A-Za-z]*[rR][A-Za-z]*|--recursive)\b([^;&|)\n'`]*)""")
MKTEMP_VAR = re.compile(r'\b([A-Za-z_]\w*)=["\']?\$\(\s*mktemp\b|\b([A-Za-z_]\w*)=["\']?`\s*mktemp\b')
# 앞쪽 줄에 홈·루트·빈 값 가드가 있는지
GUARD = re.compile(r'(\$HOME|\$\{HOME\}|~|"/"|\[\s+"/"|-z\s+"?\$|\[\[?\s+-n|:\?|realpath|readlink)')
REAL_PATH = re.compile(r'(\$HOME|\$\{HOME\}|"~"|\s~(?:/|\s|$)|\s/\s|\s"/"|\$\(\s*echo\s+~)')


def is_shell(path):
    if path.endswith((".sh", ".bash")):
        return True
    try:
        with open(path, "rb") as f:
            first = f.readline(200)
    except OSError:
        return False
    return first.startswith(b"#!") and re.search(rb"\b(ba|z|da)?sh\b", first) is not None


def walk(paths):
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
                for fn in sorted(files):
                    fp = os.path.join(root, fn)
                    if is_shell(fp):
                        yield fp
        elif os.path.isfile(p):
            yield p


def code_lines(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f, 1):
            s = line.strip()
            if s and not s.startswith("#"):
                yield n, line.rstrip("\n")


def rm_targets(args):
    """rm 인자 중 변수가 경로의 뿌리(`$x`, `"$x"/*`, `${x}`)인 것들. `/tmp/x.$$`처럼 앞이 리터럴이면 제외."""
    out = []
    for tok in re.findall(r'"[^"]*"\S*|\'[^\']*\'|\S+', args):
        if tok.startswith("-"):
            continue
        t = tok.lstrip("\"'")
        m = re.match(r'\$\{?([A-Za-z_]\w*|[0-9@*])', t)
        if m:
            out.append(m.group(1))
    return out


def lint(paths):
    files = list(walk(paths))
    findings, destructive = [], {}
    for fp in files:
        seen_guard = False
        safe_vars = set()
        for n, line in code_lines(fp):
            for m in MKTEMP_VAR.finditer(line):
                safe_vars.add(m.group(1) or m.group(2))
            m = RM_CMD.search(line)
            risky = [v for v in rm_targets(m.group(1)) if v not in safe_vars] if m else []
            if risky:
                if not seen_guard:
                    findings.append({"file": fp, "line": n, "rule": "unguarded-rm",
                                     "text": line.strip()})
                    destructive.setdefault(os.path.basename(fp), fp)
            elif GUARD.search(line):
                seen_guard = True
    for fp in files:
        base = os.path.basename(fp)
        if base in destructive:
            continue
        has_tmp = False
        calls = []
        for n, line in code_lines(fp):
            if "mktemp" in line:
                has_tmp = True
            for name in destructive:
                if name in line and REAL_PATH.search(line.split(name, 1)[1]):
                    calls.append((n, line.strip(), name))
        for n, text, name in calls:
            findings.append({"file": fp, "line": n, "rule": "real-path-to-destructive",
                             "text": text, "target": name})
        for n, line in code_lines(fp):
            if any(name in line for name in destructive) and not has_tmp and \
                    not any(c[0] == n for c in calls):
                findings.append({"file": fp, "line": n, "rule": "no-tmpdir",
                                 "text": line.strip()})
    return files, findings


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def make_home(root):
    manifest = {}
    for rel, body in CANARIES.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(body)
        manifest[rel] = sha(p)
    return manifest


def check_home(root, manifest):
    damage = []
    for rel, digest in manifest.items():
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            damage.append({"path": rel, "state": "deleted"})
        elif sha(p) != digest:
            damage.append({"path": rel, "state": "modified"})
    return damage


def run(cmd, keep, dry, as_json):
    if not cmd:
        print("실행할 명령이 없다: run -- CMD...", file=sys.stderr)
        return 2
    base = tempfile.mkdtemp(prefix="home-canary-")
    home = os.path.join(base, "home")
    os.makedirs(home)
    manifest = make_home(home)
    env = dict(os.environ, HOME=home, USERPROFILE=home, CANARY_HOME=home,
               XDG_CONFIG_HOME=os.path.join(home, ".config"))
    result = {"fake_home": home, "canaries": sorted(manifest), "command": cmd}
    if dry:
        result.update(dry_run=True, damage=[], rc=None)
        out = result
        rc = 0
    else:
        try:
            p = subprocess.run(cmd, env=env)
            crc = p.returncode
        except FileNotFoundError:
            crc = 127
        damage = check_home(home, manifest)
        result.update(dry_run=False, damage=damage, rc=crc)
        rc = 3 if damage else crc
        out = result
    if as_json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(f"가짜 HOME: {home} (미끼 {len(manifest)}개)")
        if dry:
            print("--dry-run: 명령은 실행하지 않았다")
        elif out["damage"]:
            print(f"미끼 훼손 {len(out['damage'])}개 — 이 명령은 진짜 HOME에서 돌리면 위험하다")
            for d in out["damage"]:
                print(f"  {d['state']}: ~/{d['path']}")
        else:
            print(f"미끼 {len(manifest)}개 모두 무사 (명령 종료 코드 {out['rc']})")
    if not keep:
        subprocess.run(["rm", "-rf", base])
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("lint", help="셸 스크립트의 위험한 삭제·테스트 호출을 찾는다")
    pl.add_argument("paths", nargs="+")
    pl.add_argument("--json", action="store_true")
    pr = sub.add_parser("run", help="가짜 HOME에서 명령을 돌려 미끼가 무사한지 본다")
    pr.add_argument("--keep", action="store_true", help="끝나도 임시 폴더를 남긴다")
    pr.add_argument("--dry-run", action="store_true", help="가짜 HOME만 만들고 명령은 실행하지 않는다")
    pr.add_argument("--json", action="store_true")
    pr.add_argument("command", nargs=argparse.REMAINDER)
    a = ap.parse_args(argv)
    if a.cmd == "lint":
        files, findings = lint(a.paths)
        if a.json:
            print(json.dumps({"files": len(files), "findings": findings}, ensure_ascii=False))
        else:
            for f in findings:
                print(f"{f['file']}:{f['line']}: [{f['rule']}] {f['text']}")
            print(f"검사 {len(files)}개 파일, 지적 {len(findings)}건")
        return 1 if findings else 0
    cmd = a.command[1:] if a.command[:1] == ["--"] else a.command
    return run(cmd, a.keep, a.dry_run, a.json)


if __name__ == "__main__":
    sys.exit(main())

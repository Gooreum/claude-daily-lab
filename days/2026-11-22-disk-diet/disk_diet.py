#!/usr/bin/env python3
"""disk-diet — Claude Code가 로컬 디스크에 쌓은 것을 읽기 전용으로 재고, 줄일 후보를 보여 준다.

하위 명령:
  audit  [--home DIR] [--days N] [--keep-versions N] [--top N] [--json] [--oneline] [--budget-mb N]
  plan   (audit과 같은 옵션) 정리 후보를 지우는 명령을 '출력만' 한다. 실행하지 않는다.
  slim   FILE.jsonl [-o OUT]  대화 기록에서 base64 이미지만 뺀 사본을 새 파일로 쓴다. 원본은 그대로.

이 도구는 어떤 파일도 지우거나 고치지 않는다. 쓰는 것은 `slim`의 새 사본뿐이다.
표준 라이브러리만 쓴다.
"""
import argparse
import json
import os
import shlex
import sys
import time

DAY = 86400
# 건드리지 않는 곳: 설정·인증·메모리가 사는 자리. 크기 합계에는 넣지만 정리 후보로는 절대 올리지 않는다.
PROTECTED_HINT = "settings.json · .credentials.json · CLAUDE.md · 프로젝트 memory/"


def human(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024


def dir_stats(path):
    """(총 크기, 가장 최근 파일 수정 시각, 파일 수). 심볼릭 링크는 따라가지 않고 크기에도 넣지 않는다.
    시각은 파일 기준이다: 링크 하나를 만들어도 폴더 mtime이 바뀌어 '최근 활동'으로 보이면 안 된다."""
    total, newest, count = 0, 0.0, 0
    try:
        st = os.lstat(path)
    except OSError:
        return 0, 0.0, 0
    if not os.path.isdir(path) or os.path.islink(path):
        if os.path.islink(path):
            return 0, 0.0, 0
        return st.st_size, st.st_mtime, 1
    for root, dirs, files in os.walk(path, followlinks=False):
        for name in files:
            p = os.path.join(root, name)
            try:
                s = os.lstat(p)
            except OSError:
                continue
            if os.path.islink(p):
                continue
            total += s.st_size
            count += 1
            newest = max(newest, s.st_mtime)
    if count == 0:
        newest = st.st_mtime  # 파일이 하나도 없으면 폴더 자체의 시각
    return total, newest, count


def walk_images(node, found):
    """JSON 안의 base64 이미지 블록 경로를 모은다. found에 (container, key_or_index, block) 추가."""
    if isinstance(node, dict):
        for k, v in list(node.items()):
            if is_image(v):
                found.append((node, k, v))
            else:
                walk_images(v, found)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            if is_image(v):
                found.append((node, i, v))
            else:
                walk_images(v, found)


def is_image(b):
    if not (isinstance(b, dict) and b.get("type") == "image"):
        return False
    src = b.get("source")
    return isinstance(src, dict) and src.get("type") == "base64" and isinstance(src.get("data"), str)


def scan_jsonl(path):
    """한 세션 파일의 (이미지 개수, 이미지 base64 글자 수, 이미지 표시는 있는데 JSON으로 못 읽은 줄 수)."""
    n_img, img_bytes, broken = 0, 0, 0
    with open(path, "rb") as f:
        for raw in f:
            if b'"base64"' not in raw:
                continue
            try:
                obj = json.loads(raw)
            except ValueError:
                broken += 1
                continue
            found = []
            if is_image(obj):
                found.append((None, None, obj))
            else:
                walk_images(obj, found)
            for _, _, blk in found:
                n_img += 1
                img_bytes += len(blk["source"]["data"])
    return n_img, img_bytes, broken


def audit(args):
    home = os.path.abspath(os.path.expanduser(args.home))
    now = time.time()
    claude = os.path.join(home, ".claude")
    proj = os.path.join(claude, "projects")
    wts = os.path.join(claude, "worktrees")
    vers = os.path.join(home, ".local", "share", "claude", "versions")

    r = {"home": home, "days": args.days, "keep_versions": args.keep_versions}

    # 전체 크기
    r["claude_total"] = dir_stats(claude)[0]
    r["versions_total"] = dir_stats(vers)[0]

    # 대화 기록
    sessions = []
    t_total, t_files = 0, 0
    if os.path.isdir(proj):
        for root, dirs, files in os.walk(proj, followlinks=False):
            for name in files:
                if not name.endswith(".jsonl"):
                    continue
                p = os.path.join(root, name)
                if os.path.islink(p):
                    continue
                try:
                    size = os.lstat(p).st_size
                except OSError:
                    continue
                t_total += size
                t_files += 1
                sessions.append({"path": p, "size": size})
    sessions.sort(key=lambda s: s["size"], reverse=True)
    img_total, img_count, broken_total = 0, 0, 0
    for s in sessions:
        s["images"], s["image_bytes"], s["broken_lines"] = scan_jsonl(s["path"])
        img_total += s["image_bytes"]
        img_count += s["images"]
        broken_total += s["broken_lines"]
    r["transcripts"] = {"total": t_total, "files": t_files, "image_bytes": img_total,
                        "images": img_count, "broken_lines": broken_total,
                        "top": sessions[: args.top]}

    # 옛 실행 파일: 가장 최근 N개만 남기고 나머지가 후보
    entries = []
    if os.path.isdir(vers):
        for name in os.listdir(vers):
            p = os.path.join(vers, name)
            size, newest, _ = dir_stats(p)
            try:
                mt = os.lstat(p).st_mtime
            except OSError:
                mt = newest
            entries.append({"path": p, "name": name, "size": size, "mtime": mt})
    entries.sort(key=lambda e: e["mtime"], reverse=True)
    r["versions"] = {"count": len(entries),
                     "keep": entries[: args.keep_versions],
                     "stale": entries[args.keep_versions:]}

    # worktree: 마지막 수정이 N일 넘은 것이 후보
    wlist = []
    if os.path.isdir(wts):
        for name in sorted(os.listdir(wts)):
            p = os.path.join(wts, name)
            if os.path.islink(p) or not os.path.isdir(p):
                continue
            size, newest, files = dir_stats(p)
            wlist.append({"path": p, "name": name, "size": size, "files": files,
                          "idle_days": int((now - newest) // DAY) if newest else 0})
    wlist.sort(key=lambda w: w["size"], reverse=True)
    r["worktrees"] = {"all": wlist,
                      "stale": [w for w in wlist if w["idle_days"] >= args.days]}

    r["reclaimable"] = {
        "images": img_total,
        "versions": sum(e["size"] for e in r["versions"]["stale"]),
        "worktrees": sum(w["size"] for w in r["worktrees"]["stale"]),
    }
    r["reclaimable"]["total"] = sum(r["reclaimable"].values())
    r["tracked_total"] = r["claude_total"] + r["versions_total"]
    return r


def print_report(r):
    t, v, w, rc = r["transcripts"], r["versions"], r["worktrees"], r["reclaimable"]
    print(f"disk-diet — {r['home']}")
    print()
    print("| 자리 | 크기 | 비고 |")
    print("|------|------|------|")
    print(f"| ~/.claude 전체 | {human(r['claude_total'])} | 설정·인증이 섞여 있어 통째로 지우지 않는다 |")
    print(f"| 대화 기록(projects/*.jsonl) | {human(t['total'])} | 세션 {t['files']}개 · "
          f"base64 이미지 {t['images']}장 {human(t['image_bytes'])} |")
    print(f"| worktree(~/.claude/worktrees) | {human(sum(x['size'] for x in w['all']))} | "
          f"{len(w['all'])}개 중 {r['days']}일 넘게 손 안 댄 것 {len(w['stale'])}개 |")
    print(f"| 옛 실행 파일(~/.local/share/claude/versions) | {human(r['versions_total'])} | "
          f"{v['count']}개 중 최신 {r['keep_versions']}개 남기면 {len(v['stale'])}개가 후보 |")
    print()
    print(f"되찾을 수 있는 후보: {human(rc['total'])} "
          f"(이미지 {human(rc['images'])} · 옛 버전 {human(rc['versions'])} · 오래된 worktree {human(rc['worktrees'])})")
    if t["broken_lines"]:
        print(f"주의: base64 표시는 있는데 JSON으로 읽히지 않는 줄이 {t['broken_lines']}개 있다(그대로 두고 세지 않았다).")
    print()
    if t["top"]:
        print(f"가장 큰 세션 {len(t['top'])}개:")
        print("| 크기 | 이미지 | 이미지 몫 | 파일 |")
        print("|------|--------|-----------|------|")
        for s in t["top"]:
            share = f"{100 * s['image_bytes'] // s['size']}%" if s["size"] else "0%"
            print(f"| {human(s['size'])} | {s['images']}장 | {share} | {os.path.relpath(s['path'], r['home'])} |")
        print()
    if w["stale"]:
        print(f"{r['days']}일 넘게 손 안 댄 worktree:")
        for x in w["stale"]:
            print(f"- {x['name']}: {human(x['size'])} · {x['idle_days']}일 전 · 파일 {x['files']}개")
        print()
    print(f"건드리지 않는 곳: {PROTECTED_HINT}")


def oneline(r):
    rc = r["reclaimable"]
    return (f"disk-diet: ~/.claude {human(r['claude_total'])} · 대화 기록 {human(r['transcripts']['total'])} · "
            f"되찾을 후보 {human(rc['total'])} (이미지 {human(rc['images'])}, 옛 버전 {human(rc['versions'])}, "
            f"worktree {human(rc['worktrees'])})")


def print_plan(r):
    print("# disk-diet plan — 출력만 한다. 훑어보고 필요한 줄만 직접 실행한다.")
    print(f"# 건드리지 않는 곳: {PROTECTED_HINT}")
    any_line = False
    for e in r["versions"]["stale"]:
        print(f"# 옛 실행 파일 {e['name']} ({human(e['size'])})")
        print(f"rm -rf -- {shlex.quote(e['path'])}")
        any_line = True
    for x in r["worktrees"]["stale"]:
        print(f"# worktree {x['name']} ({human(x['size'])}, {x['idle_days']}일 전). 안에 커밋 안 한 변경이 없는지 먼저 확인. 지운 뒤 원래 저장소에서 `git worktree prune`")
        print(f"rm -rf -- {shlex.quote(x['path'])}")
        any_line = True
    img_sessions = [s for s in r["transcripts"]["top"] if s["image_bytes"] > 0]
    for s in img_sessions:
        print(f"# 대화 기록 {os.path.basename(s['path'])}: 이미지 {human(s['image_bytes'])} → 가벼운 사본을 만든다(원본은 그대로. 공간은 사본을 확인한 뒤 원본과 바꿔야 확보된다)")
        print(f"python3 disk_diet.py slim {shlex.quote(s['path'])} -o ./{shlex.quote(os.path.basename(s['path']))}.slim")
        any_line = True
    if not any_line:
        print("# 정리할 후보가 없다.")


def slim(args):
    src = os.path.abspath(args.file)
    if not os.path.isfile(src):
        print(f"오류: 파일이 없다: {args.file}", file=sys.stderr)
        return 2
    out = os.path.abspath(args.output) if args.output else os.path.abspath(os.path.basename(src) + ".slim")
    if os.path.realpath(out) == os.path.realpath(src):
        print("오류: 출력이 원본과 같은 파일이다. 원본은 고치지 않는다.", file=sys.stderr)
        return 2
    if os.path.exists(out):
        print(f"오류: 출력 파일이 이미 있다: {out} (덮어쓰지 않는다)", file=sys.stderr)
        return 2
    removed, saved, changed_lines = 0, 0, 0
    with open(src, "rb") as fin, open(out, "wb") as fout:
        for raw in fin:
            if b'"base64"' not in raw:
                fout.write(raw)
                continue
            try:
                obj = json.loads(raw)
            except ValueError:
                fout.write(raw)  # 못 읽는 줄은 그대로 둔다
                continue
            found = []
            top_is_image = is_image(obj)
            if not top_is_image:
                walk_images(obj, found)
            if not found and not top_is_image:
                fout.write(raw)
                continue
            if top_is_image:
                found = [(None, None, obj)]
            for container, key, blk in found:
                n = len(blk["source"]["data"])
                mt = blk["source"].get("media_type", "image")
                repl = {"type": "text", "text": f"[disk-diet: 이미지 제거 {mt} base64 {n}자]"}
                if container is None:
                    obj = repl
                else:
                    container[key] = repl
                removed += 1
            line = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            end = b"\n" if raw.endswith(b"\n") else b""
            fout.write(line + end)
            saved += len(raw) - len(line + end)
            changed_lines += 1
    print(f"사본: {out}")
    print(f"이미지 {removed}장 제거 · 바뀐 줄 {changed_lines}개 · {human(saved)} 줄어듦 (원본은 그대로)")
    return 0


def add_audit_opts(p):
    p.add_argument("--home", default="~", help="홈 폴더(기본 ~). 시험용으로 가짜 홈을 줄 수 있다")
    p.add_argument("--days", type=int, default=21, help="이 일수 넘게 손 안 댄 worktree를 후보로 본다(기본 21)")
    p.add_argument("--keep-versions", type=int, default=2, help="남길 최신 실행 파일 수(기본 2)")
    p.add_argument("--top", type=int, default=5, help="큰 세션을 몇 개 보일지(기본 5)")
    p.add_argument("--json", action="store_true", help="표 대신 JSON")
    p.add_argument("--oneline", action="store_true", help="한 줄 요약만(로그용)")
    p.add_argument("--budget-mb", type=float, default=None,
                   help="~/.claude + 실행 파일 합계가 이 MB를 넘으면 exit 1")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="disk_diet.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    add_audit_opts(sub.add_parser("audit", help="크기와 정리 후보를 보여 준다(읽기 전용)"))
    add_audit_opts(sub.add_parser("plan", help="정리 명령을 출력만 한다"))
    sp = sub.add_parser("slim", help="이미지를 뺀 대화 기록 사본을 만든다")
    sp.add_argument("file")
    sp.add_argument("-o", "--output", default=None, help="출력 경로(기본: 현재 폴더의 <이름>.slim)")
    args = ap.parse_args(argv)
    if args.cmd is None:
        ap.print_help()
        return 2
    if args.cmd == "slim":
        return slim(args)
    r = audit(args)
    if args.cmd == "plan":
        print_plan(r)
    elif args.json:
        json.dump(r, sys.stdout, ensure_ascii=False, indent=2, default=str)
        print()
    elif args.oneline:
        print(oneline(r))
    else:
        print_report(r)
    if args.budget_mb is not None and r["tracked_total"] > args.budget_mb * 1024 * 1024:
        print(f"예산 초과: {human(r['tracked_total'])} > {args.budget_mb:g}MB", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

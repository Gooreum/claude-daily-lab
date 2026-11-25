#!/usr/bin/env python3
"""skill-shell-guard — Claude Code v2.1.332의 `PreSkillShellCommand` 훅 + 스킬 폴더 사전 점검.

스킬·명령 본문의 `!`명령`` 한 줄이나 ```! 블록은 스킬을 불러올 때 Claude Code가 먼저 실행한다.
이 도구는 그 명령을 실행 전에 판정한다 (표준 라이브러리만, 키·모델·네트워크 없음).

  hook       훅으로 쓴다. 표준입력의 훅 JSON을 읽어 allow / ask / deny 를 JSON으로 낸다.
  check      명령 한 줄을 판정해 본다.
  scan       스킬 폴더의 인라인 셸 명령을 모두 뽑아 같은 규칙으로 판정한다.
  settings   settings.json 에 넣을 훅 조각을 낸다.

입출력 규격은 문서가 아직 없어 Agent SDK 0.3.332 의 타입 정의(sdk.d.ts)를 근거로 했다:
  입력  hook_event_name, tool_name(Bash|PowerShell), tool_input.command, tool_use_id,
        command_name, command_source?, invoked_by(user|claude|other), cwd, session_id ...
  출력  hookSpecificOutput.{hookEventName, permissionDecision, permissionDecisionReason}
        allow 는 아무것도 더하지 않고, deny·ask·defer 는 모두 명령 실행을 막는다.
"""
import argparse
import datetime
import json
import os
import re
import sys

EVENT = "PreSkillShellCommand"
RANK = {"allow": 0, "ask": 1, "deny": 2}
MAX_SCRIPT_BYTES = 200_000

# ---------------------------------------------------------------- 파서 -----


class Segment:
    """`;` `&&` `||` `|` 줄바꿈으로 나뉜 명령 한 토막."""

    def __init__(self):
        self.words = []
        self.writes = []      # 파일로 쓰는 리다이렉트 대상
        self.parse_error = ""


def _match_paren(s, i):
    """s[i] == '(' 일 때 짝이 맞는 ')' 위치. 없으면 -1."""
    depth = 0
    q = None
    j = i
    while j < len(s):
        c = s[j]
        if q:
            if c == q:
                q = None
            elif c == "\\" and q == '"':
                j += 1
        elif c in "'\"":
            q = c
        elif c == "\\":
            j += 1
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


def parse(cmd):
    """명령 문자열을 (토막 목록, 명령 치환 문자열 목록)으로 나눈다. 따옴표를 존중한다."""
    segs, subs = [], []
    seg = Segment()
    cur = None
    q = None
    pending_write = False
    i, n = 0, len(cmd)

    def flush():
        nonlocal cur, pending_write
        if cur is None:
            return
        if pending_write:
            seg.writes.append(cur)
            pending_write = False
        else:
            seg.words.append(cur)
        cur = None

    def end_seg():
        nonlocal seg
        flush()
        if seg.words or seg.writes:
            segs.append(seg)
        seg = Segment()

    while i < n:
        c = cmd[i]
        nxt = cmd[i + 1] if i + 1 < n else ""
        if q == "'":
            if c == "'":
                q = None
            else:
                cur += c
        elif q == '"':
            if c == '"':
                q = None
            elif c == "\\" and nxt:
                cur += nxt
                i += 1
            elif c == "$" and nxt == "(" and cmd[i + 2:i + 3] != "(":
                j = _match_paren(cmd, i + 1)
                if j < 0:
                    seg.parse_error = "닫히지 않은 $("
                    cur += cmd[i:]
                    i = n
                    continue
                subs.append(cmd[i + 2:j])
                cur += "$(…)"
                i = j
            elif c == "`":
                j = cmd.find("`", i + 1)
                if j < 0:
                    seg.parse_error = "닫히지 않은 백틱"
                    cur += cmd[i:]
                    i = n
                    continue
                subs.append(cmd[i + 1:j])
                cur += "`…`"
                i = j
            else:
                cur += c
        else:
            if c in " \t":
                flush()
            elif c in "\n;":
                end_seg()
            elif c == "&":
                if nxt == "&":
                    i += 1
                end_seg()
            elif c == "|":
                if nxt == "|":
                    i += 1
                end_seg()
            elif c in "<>":
                if cur is not None and cur.isdigit():
                    cur = None  # 2>/dev/null 의 "2"
                else:
                    flush()
                if c == ">":
                    if nxt == ">":
                        i += 1
                        nxt = cmd[i + 1] if i + 1 < n else ""
                    if nxt == "&":      # >&2 같은 파일 기술자 복제는 쓰기가 아니다
                        i += 1
                        while i + 1 < n and cmd[i + 1].isdigit():
                            i += 1
                    else:
                        pending_write = True
                elif nxt == "<":        # 히어도큐먼트 표식은 건너뜀
                    i += 1
            elif c == "\\":
                if nxt:
                    cur = (cur or "") + nxt
                    i += 1
            elif c in "'\"":
                q = c
                if cur is None:
                    cur = ""
            elif c == "$" and nxt == "(" and cmd[i + 2:i + 3] != "(":
                j = _match_paren(cmd, i + 1)
                if j < 0:
                    seg.parse_error = "닫히지 않은 $("
                    cur = (cur or "") + cmd[i:]
                    i = n
                    continue
                subs.append(cmd[i + 2:j])
                cur = (cur or "") + "$(…)"
                i = j
            elif c == "`":
                j = cmd.find("`", i + 1)
                if j < 0:
                    seg.parse_error = "닫히지 않은 백틱"
                    cur = (cur or "") + cmd[i:]
                    i = n
                    continue
                subs.append(cmd[i + 1:j])
                cur = (cur or "") + "`…`"
                i = j
            elif c in "(){}":
                flush()
            else:
                cur = (cur or "") + c
        i += 1
    if q:
        seg.parse_error = "닫히지 않은 따옴표"
    end_seg()
    return segs, subs


# ---------------------------------------------------------------- 규칙 -----

PIPE_SHELL = re.compile(r"\|\s*(?:sudo\s+)?(?:\S*/)?(?:ba|z|da|k|c|fi)?sh\b")
PIPE_INTERP = re.compile(r"\|\s*(?:sudo\s+)?(?:python[0-9.]*|perl|ruby|node)\b\s*(?:-\s*)?(?:$|[;&|\n])")
PROC_SUBST = re.compile(r"<\(\s*(?:curl|wget)\b")
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
INTERPS = {"python", "python3", "node", "ruby", "perl", "deno", "bun"}
SECRET_PATH = re.compile(
    r"(?:^|/)(?:\.env(?:\.[\w.-]+)?|\.netrc|\.npmrc|\.pypirc|\.git-credentials|id_(?:rsa|dsa|ecdsa|ed25519)"
    r"|credentials(?:\.json)?|\.claude\.json)$"
    r"|(?:^|/)\.(?:ssh|aws|gnupg|kube|docker)(?:/|$)|\.(?:pem|key|p12|pfx)$|(?:^|/)config/gh/hosts\.yml$"
)
SECRET_VAR = re.compile(r"\$\{?[A-Za-z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)[A-Za-z0-9_]*", re.I)
SECRET_NAME = re.compile(r"(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)", re.I)
UPLOAD_FLAGS = {"-d", "-F", "-T", "--data", "--data-raw", "--data-binary", "--data-urlencode",
                "--form", "--upload-file", "--post-file", "--post-data", "--body-file", "--body-data", "--json"}
READONLY = {"ls", "pwd", "date", "whoami", "uname", "echo", "printf", "true", "false", "test", "[", "cat", "head",
            "tail", "wc", "sort", "uniq", "grep", "egrep", "fgrep", "rg", "diff", "cmp", "stat", "file", "basename",
            "dirname", "realpath", "tr", "cut", "nl", "tree", "which", "type", "jq", "id", "hostname", "nproc", "du",
            "df", "readlink", "seq", "sleep", "cd", "set", "export", "unset"}
GIT_READ = {"status", "diff", "log", "show", "rev-parse", "rev-list", "describe", "ls-files", "ls-tree",
            "blame", "shortlog", "branch", "tag", "remote", "stash", "config", "name-rev", "merge-base",
            "cat-file", "count-objects", "grep", "reflog"}
GH_READ = {("pr", "view"), ("pr", "list"), ("pr", "diff"), ("pr", "checks"), ("pr", "status"), ("issue", "view"),
           ("issue", "list"), ("run", "view"), ("run", "list"), ("repo", "view"), ("auth", "status")}
PUBLISH = {("npm", "publish"), ("yarn", "publish"), ("pnpm", "publish"), ("twine", "upload"), ("cargo", "publish"),
           ("docker", "push"), ("terraform", "apply"), ("terraform", "destroy"), ("kubectl", "apply"),
           ("kubectl", "delete"), ("helm", "install"), ("helm", "upgrade"), ("gh", "release")}
INSTALL = {("npm", "install"), ("npm", "i"), ("npm", "ci"), ("npm", "add"), ("pnpm", "install"), ("pnpm", "add"),
           ("pnpm", "i"), ("yarn", "install"), ("yarn", "add"), ("pip", "install"), ("pip3", "install"),
           ("brew", "install"), ("apt", "install"), ("apt-get", "install"), ("gem", "install"),
           ("cargo", "install"), ("go", "install"), ("pipx", "install"), ("uv", "pip")}
RUNNERS = {"npx", "uvx", "pipx", "bunx", "pnpx"}
WRAPPERS = {"time", "nohup", "command", "builtin", "nice", "exec", "stdbuf"}


GIT_SAFE_ONLY = {"branch", "tag", "remote", "stash", "config"}
_GIT_SAFE_FLAGS = {
    "branch": {"-a", "-r", "-v", "-vv", "--list", "-l", "--show-current", "--contains", "--merged", "--no-merged",
               "--all", "--remotes"},
    "tag": {"-l", "--list", "--contains", "-n"},
    "remote": {"-v"},
    "stash": set(),
    "config": {"--get", "--get-all", "--list", "-l", "--get-regexp", "--local", "--global"},
}


def _git_sub_safe(sub, rest):
    """branch·tag·remote·stash·config 는 읽기와 쓰기가 같은 이름이라 인자까지 본다."""
    flags = [a for a in rest if a.startswith("-")]
    pos = [a for a in rest if not a.startswith("-")]
    safe = _GIT_SAFE_FLAGS[sub]
    if any(f not in safe and not f.startswith(("--format", "--sort")) for f in flags):
        return False
    if sub == "stash":
        return bool(pos) and pos[0] in {"list", "show"}
    if sub == "remote":
        return not pos or pos[0] in {"show", "get-url"}
    if sub == "config":
        return any(f in {"--get", "--get-all", "--list", "-l", "--get-regexp"} for f in flags)
    if pos:  # branch·tag 에 위치 인자가 있으면 목록 필터일 때만 읽기
        return any(f in {"--list", "-l", "--contains", "--merged", "--no-merged"} for f in flags)
    return True


class V:
    """판정 한 건."""

    def __init__(self, decision, rule, reason, part=""):
        self.decision, self.rule, self.reason, self.part = decision, rule, reason, part

    def as_dict(self):
        return {"decision": self.decision, "rule": self.rule, "reason": self.reason}


def _worse(a, b):
    return b if RANK[b.decision] > RANK[a.decision] else a


def _env_prefix(words):
    k = 0
    while k < len(words) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[k]):
        k += 1
    return words[k:]


def _script_arg(words, rest_from):
    for w in words[rest_from:]:
        if not w.startswith("-"):
            return w
    return ""


def _scan_script(path, cwd, opts):
    """스크립트 본문에서 '확실히 위험한' 줄(deny 급)만 찾는다. (rule, 줄 번호) 또는 None."""
    full = path if os.path.isabs(path) else os.path.join(cwd or ".", path)
    try:
        if os.path.getsize(full) > MAX_SCRIPT_BYTES:
            return ("too-large", 0)
        with open(full, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return ("missing", 0)
    for no, line in enumerate(lines, 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        v = judge(s, cwd, opts, depth=1)
        if v.decision == "deny":
            return (v.rule, no)
    return None


def judge_segment(seg, cwd, opts, depth):
    words = _env_prefix(seg.words)
    if seg.parse_error:
        return V("ask", "unparsable", f"명령을 끝까지 읽지 못했다: {seg.parse_error}")
    if not words:
        return V("allow", "env-only", "환경변수 지정뿐")
    # 1) 비밀 경로·변수는 명령이 무엇이든 거절
    for w in words[1:] + seg.writes:
        base = w.split("=", 1)[-1] if w.startswith("-") else w
        if os.path.basename(base) in {".env.example", ".env.sample", ".env.template"}:
            continue
        if SECRET_PATH.search(base.replace("~", "")) or SECRET_PATH.search(base):
            return V("deny", "secret-path", f"비밀값이 든 경로를 건드린다: {os.path.basename(base) or base}")
    for w in words[1:]:
        if SECRET_VAR.search(w):
            return V("deny", "secret-var", "비밀값일 법한 환경변수($…KEY·TOKEN·SECRET)를 읽는다")
    head = words[0]
    name = os.path.basename(head)
    args = words[1:]
    # 2) 감싸는 명령은 벗겨서 다시 본다
    if name in WRAPPERS and args:
        inner = Segment()
        inner.words, inner.writes = args, seg.writes
        return judge_segment(inner, cwd, opts, depth)
    if name == "env":
        rest = [a for a in args if not a.startswith("-")]
        rest = _env_prefix(rest)
        if not rest:
            return V("deny", "env-dump", "`env` 만 쓰면 환경변수 전체(비밀값 포함)가 출력된다")
        inner = Segment()
        inner.words, inner.writes = rest, seg.writes
        return judge_segment(inner, cwd, opts, depth)
    # `set -u`·`set -e` 는 셸 옵션이다. 환경 전체를 찍는 것은 인자 없는 `set`, `export`/`export -p`, `printenv`
    dump = (name == "set" and not args) or (name == "export" and (not args or args == ["-p"])) \
        or (name == "printenv" and not [a for a in args if not a.startswith("-")])
    if dump:
        return V("deny", "env-dump", f"`{name}` 만 쓰면 환경변수 전체(비밀값 포함)가 출력된다")
    if name == "printenv" and any(SECRET_NAME.search(a) for a in args):
        return V("deny", "secret-var", "비밀값일 법한 환경변수를 출력한다")
    if name in {"sudo", "su", "doas"}:
        return V("ask", "privilege", "권한 상승(sudo·su)이 필요한 명령")
    if name == "xargs":
        return V("ask", "xargs", "xargs 는 임의 명령을 대신 실행한다")
    if name in {"nc", "ncat", "netcat", "socat", "telnet"}:
        return V("deny", "exfil", f"`{name}` 는 임의 서버로 데이터를 보낼 수 있다")
    if name == "eval":
        return V("deny", "eval", "`eval` 은 문자열을 명령으로 실행한다")
    if name.startswith("$") or name.startswith("`") or "$(…)" == name:
        return V("ask", "dynamic-command", "명령어 자리가 변수·치환이라 무엇이 실행될지 알 수 없다")
    # 3) 위험 명령
    if name == "rm":
        recursive = any((a.startswith("-") and not a.startswith("--") and re.search(r"[rR]", a))
                        or a == "--recursive" for a in args)
        targets = [a for a in args if not a.startswith("-")]
        if recursive:
            wide = [t for t in targets if t.startswith(("/", "~", "$HOME", "${HOME}")) or t in {"*", ".", "..", "./*", "../*", ".*"}]
            if wide:
                return V("deny", "destructive-rm", f"재귀 삭제 대상이 넓다: {wide[0]}")
            return V("ask", "rm-recursive", "재귀 삭제")
        return V("ask", "rm", "파일을 지운다")
    if name in {"curl", "wget"}:
        # wget 의 짧은 -T·-d·-F 는 타임아웃·디버그라 업로드가 아니다. 짧은 플래그는 curl 에만 적용한다
        long_up = [a for a in args if a.split("=", 1)[0] in UPLOAD_FLAGS and a.startswith("--")
                   or a.startswith(("--data", "--form", "--upload", "--post", "--body"))]
        short_up = [a for a in args if name == "curl" and re.match(r"^-[A-Za-z]*[dFT]$", a)]
        up = long_up + short_up
        method = [a for i, a in enumerate(args) if a in {"-X", "--request"} and i + 1 < len(args)
                  and args[i + 1].upper() in {"POST", "PUT", "PATCH", "DELETE"}]
        if up or method:
            return V("deny", "exfil", f"`{name}` 로 데이터를 보낸다({(up or method)[0]})")
        return V("ask", "network", f"`{name}` 로 외부에서 내려받는다")
    if name in {"scp", "sftp", "ftp", "rsync"}:
        return V("ask", "remote-copy", f"`{name}` 로 원격과 파일을 주고받는다")
    if name == "git":
        sub = next((a for a in args if not a.startswith("-")), "")
        flags = [a for a in args if a.startswith("-")]
        if sub == "push":
            if any(f in {"-f", "--force", "--force-with-lease", "--mirror", "--delete"} or f.startswith("--force") for f in flags):
                return V("deny", "git-force-push", "강제·삭제 푸시")
            return V("ask", "git-push", "원격에 푸시한다")
        if sub in {"reset", "clean", "checkout", "restore", "switch", "rebase", "merge", "commit", "add", "rm", "mv", "pull", "fetch", "clone", "apply", "am", "cherry-pick", "revert"}:
            if sub == "reset" and "--hard" in flags:
                return V("ask", "git-discard", "`git reset --hard` 는 작업 중인 변경을 버린다")
            if sub == "clean":
                return V("ask", "git-discard", "`git clean` 은 추적 안 되는 파일을 지운다")
            return V("ask", "git-write", f"`git {sub}` 는 저장소나 작업 트리를 바꾼다")
        if sub in GIT_READ:
            if sub in GIT_SAFE_ONLY and not _git_sub_safe(sub, [a for a in args if a != sub]):
                return V("ask", "git-write", f"`git {sub} …` 는 값을 바꿀 수 있다")
            if "--output" in flags or any(f.startswith("--output=") for f in flags):
                return V("ask", "git-write", "`--output` 으로 파일을 쓴다")
            return V("allow", "git-read", "읽기 전용 git")
        return V("ask", "git-other", f"분류하지 못한 git 하위 명령: {sub or '(없음)'}")
    if name == "gh":
        sub = tuple(a for a in args if not a.startswith("-"))[:2]
        if sub in GH_READ:
            return V("allow", "gh-read", "읽기 전용 gh")
        return V("ask", "gh-other", f"`gh {' '.join(sub)}` 는 GitHub 상태를 바꾸거나 분류하지 못했다")
    sub2 = tuple(a for a in args if not a.startswith("-"))[:1]
    if (name, sub2[0] if sub2 else "") in PUBLISH:
        return V("ask", "publish", f"`{name} {sub2[0]}` 는 바깥에 배포·적용한다")
    if (name, sub2[0] if sub2 else "") in INSTALL or name in RUNNERS:
        return V("ask", "install", f"`{name}` 는 외부 코드를 내려받아 실행·설치한다")
    if name in {"chmod", "chown", "chgrp"} and any(a in {"-R", "-r"} or re.fullmatch(r"[0-7]*7[0-7]7|a\+rwx|o\+w", a) for a in args):
        return V("ask", "permissions", "넓은 권한 변경")
    # 4) 셸·인터프리터 실행
    direct = "/" in head and not (head.startswith("/") and name in READONLY) and not head.startswith("$")
    if name in SHELLS or name in INTERPS or direct:
        script_runner = name in SHELLS or name in INTERPS
        if script_runner:
            if name in SHELLS and "-c" in args:
                k = args.index("-c")
                if k + 1 < len(args):
                    if depth >= 3:
                        return V("ask", "nested", "중첩이 깊다")
                    v = judge(args[k + 1], cwd, opts, depth + 1)
                    if v.decision == "allow":
                        return V("ask", "shell-c", "`-c` 문자열을 실행한다(안쪽은 안전해 보이나 문자열 실행은 되묻는다)")
                    return V(v.decision, v.rule, "`-c` 안쪽: " + v.reason)
            if "-c" in args or (name in INTERPS and ("-e" in args or "-p" in args)):
                return V("ask", "inline-code", f"`{name}` 로 코드 문자열을 직접 실행한다")
            if any(a in {"--version", "-V", "-v", "--help", "-h"} for a in args):
                return V("allow", "version-query", f"`{name}` 의 버전·도움말 조회")
            target = _script_arg(args, 0)
            if not target:
                return V("deny", "stdin-interpreter", f"`{name}` 가 표준입력을 코드로 읽는다")
        else:
            target = head
        if target.startswith(("/", "~", "$")) or ".." in target.split("/"):
            return V("ask", "script-outside", f"프로젝트 밖·동적 경로의 스크립트: {target}")
        hit = _scan_script(target, cwd, opts) if depth == 0 else None
        if hit and hit[0] == "missing":
            return V("ask", "script-missing", f"스크립트를 찾지 못해 내용을 못 본다: {target}")
        if hit and hit[0] == "too-large":
            return V("ask", "script-large", f"스크립트가 너무 커서 내용을 못 본다: {target}")
        if hit:
            return V("ask", "script-content", f"{target} {hit[1]}번째 줄이 위험 규칙({hit[0]})에 걸린다")
        return V("allow", "project-script", f"프로젝트 안 스크립트({target}), 본문에 deny급 줄 없음")
    # 5) 읽기 전용 허용
    if name == "sed":
        if any(a == "-i" or a.startswith("-i") or a == "--in-place" for a in args):
            return V("ask", "sed-inplace", "`sed -i` 는 파일을 고친다")
        return V("allow", "readonly", "sed (제자리 수정 없음)")
    if name == "find":
        bad = [a for a in args if a in {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprintf", "-fls"}]
        if bad:
            return V("ask", "find-exec", f"`find {bad[0]}` 는 명령을 실행하거나 지운다")
        return V("allow", "readonly", "find (실행·삭제 없음)")
    if name == "awk":
        if any("system(" in a or "getline" in a for a in args):
            return V("ask", "awk-system", "awk 안에서 명령을 실행할 수 있다")
        return V("allow", "readonly", "awk")
    if name in {"tee", "cp", "mv", "mkdir", "touch", "ln", "install", "dd", "truncate"}:
        return V("ask", "writes", f"`{name}` 는 파일을 만들거나 바꾼다")
    if name in READONLY:
        return V("allow", "readonly", f"읽기 전용 명령 `{name}`")
    if args in (["--version"], ["-V"], ["-version"], ["version"]) and name not in {"docker", "kubectl", "terraform"}:
        return V("allow", "version-query", f"`{name}` 의 버전 조회")
    return V(opts.get("default", "ask"), "unknown", f"허용 목록에 없는 명령 `{name}`")


def judge(cmd, cwd=".", opts=None, depth=0):
    """명령 문자열 전체를 판정한다. 토막 중 가장 엄격한 것이 이긴다."""
    opts = opts or {}
    cmd = cmd.strip()
    if not cmd:
        return V("allow", "empty", "빈 명령")
    for rx, rule, why in ((PIPE_SHELL, "pipe-to-shell", "출력을 셸에 바로 넘긴다(`… | sh`)"),
                          (PIPE_INTERP, "pipe-to-shell", "출력을 인터프리터에 바로 넘긴다(`… | python`)"),
                          (PROC_SUBST, "pipe-to-shell", "내려받은 내용을 `<(curl …)` 로 바로 실행한다")):
        if rx.search(cmd):
            return V("deny", rule, why)
    for rx in opts.get("deny_rx", []):
        if rx.search(cmd):
            return V("deny", "policy-deny", f"정책 파일의 deny 패턴: {rx.pattern}")
    segs, subs = parse(cmd)
    worst = V("allow", "empty", "빈 명령")
    for s in segs:
        v = judge_segment(s, cwd, opts, depth)
        worst = _worse(worst, v) if worst.rule != "empty" else v
        if s.writes and worst.decision == "allow":
            w = [t for t in s.writes if t != "/dev/null"]
            if w:
                worst = V("ask", "redirect-write", f"리다이렉트로 파일에 쓴다: {w[0]}")
    for sub in subs:
        if depth >= 3:
            worst = _worse(worst, V("ask", "nested", "명령 치환이 너무 깊다"))
            continue
        v = judge(sub, cwd, opts, depth + 1)
        if v.decision != "allow":
            worst = _worse(worst, V(v.decision, v.rule, "명령 치환 안쪽: " + v.reason))
    if worst.decision == "ask":
        for rx in opts.get("allow_rx", []):
            if rx.search(cmd) and worst.rule not in {"unparsable"}:
                return V("allow", "policy-allow", f"정책 파일의 allow 패턴: {rx.pattern}")
    if worst.decision == "allow" and worst.rule == "empty" and segs == []:
        return V("allow", "empty", "실행할 명령 없음")
    return worst


# ---------------------------------------------------------------- 정책 -----


def load_policy(path):
    """{"default": "ask", "allow": [정규식], "deny": [정규식]}"""
    opts = {"default": "ask", "allow_rx": [], "deny_rx": []}
    if not path:
        return opts
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("정책 파일은 JSON 객체여야 한다")
    unknown = set(data) - {"default", "allow", "deny"}
    if unknown:
        raise ValueError("모르는 키: " + ", ".join(sorted(unknown)))
    if data.get("default", "ask") not in RANK:
        raise ValueError("default 는 allow·ask·deny 중 하나")
    opts["default"] = data.get("default", "ask")
    for key, dest in (("allow", "allow_rx"), ("deny", "deny_rx")):
        for p in data.get(key, []):
            opts[dest].append(re.compile(p))
    return opts


# ---------------------------------------------------------------- 훅 -------


def hook_decision(payload, opts):
    """훅 입력(dict) → 출력(dict). 규격이 어긋난 입력은 닫는 쪽(deny)으로 처리한다."""
    if not isinstance(payload, dict):
        return _out("deny", "훅 입력이 JSON 객체가 아니다"), V("deny", "bad-input", "객체 아님")
    ev = payload.get("hook_event_name")
    if ev != EVENT:
        return None, V("allow", "other-event", f"{ev!r} 는 이 훅의 이벤트가 아니다")
    ti = payload.get("tool_input")
    cmd = ti.get("command") if isinstance(ti, dict) else None
    if not isinstance(cmd, str):
        return _out("deny", "tool_input.command 가 없어 판정할 수 없다"), V("deny", "bad-input", "command 없음")
    v = judge(cmd, payload.get("cwd") or ".", opts)
    by = payload.get("invoked_by")
    if v.decision == "ask" and opts.get("strict_unattended") and by in {"claude", "other"}:
        v = V("deny", v.rule, v.reason + f" (사람이 직접 부른 스킬이 아니어서 되묻지 않고 거절: invoked_by={by})")
    if v.decision == "allow":
        return _out("allow", f"skill-shell-guard: {v.reason}"), v
    who = payload.get("command_name") or "?"
    text = f"skill-shell-guard [{v.rule}] {v.reason} — 스킬 {who}"
    return _out(v.decision, text), v


def _out(decision, reason):
    return {"hookSpecificOutput": {"hookEventName": EVENT, "permissionDecision": decision,
                                   "permissionDecisionReason": reason}}


def write_log(path, payload, v):
    """명령 본문은 남기지 않는다(비밀값이 섞일 수 있다). 스킬 이름·판정·규칙·명령의 첫 단어만."""
    if not path:
        return
    cmd = ((payload or {}).get("tool_input") or {}).get("command", "") if isinstance(payload, dict) else ""
    first = cmd.strip().split(None, 1)[0][:40] if cmd.strip() else ""
    rec = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "command_name": (payload or {}).get("command_name") if isinstance(payload, dict) else None,
           "invoked_by": (payload or {}).get("invoked_by") if isinstance(payload, dict) else None,
           "decision": v.decision, "rule": v.rule, "first_word": first}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def cmd_hook(args):
    opts = _opts(args)
    payload = None
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
        out, v = hook_decision(payload, opts)
    except Exception as e:  # 훅이 죽으면 명령이 그냥 돌 수 있으니 닫는다
        out = _out("deny", f"skill-shell-guard 가 입력을 처리하지 못해 거절한다: {type(e).__name__}")
        v = V("deny", "internal-error", str(e)[:80])
    try:
        write_log(args.log, payload, v)
    except OSError as e:
        print(f"skill-shell-guard: 로그를 쓰지 못함: {e}", file=sys.stderr)
    if out is not None:
        print(json.dumps(out, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- 스캔 -----

FENCE = re.compile(r"^\s*(```+|~~~+)\s*(\S*)")
INLINE = re.compile(r"!`([^`\n]+)`")


def extract(text):
    """마크다운 본문에서 (줄 번호, 형태, 명령) 목록을 뽑는다. 문서가 정한 두 형태만:
    한 줄 `!`명령`` (코드 블록 밖), 그리고 ```! 로 여는 블록."""
    out = []
    lines = text.splitlines()
    i = 0
    fence = None
    while i < len(lines):
        ln = lines[i]
        m = FENCE.match(ln)
        if m and fence is None:
            fence = (m.group(1)[0], len(m.group(1)), m.group(2), i + 1)
            body = []
            i += 1
            while i < len(lines):
                c = FENCE.match(lines[i])
                if c and c.group(1)[0] == fence[0] and len(c.group(1)) >= fence[1] and not c.group(2):
                    break
                body.append(lines[i])
                i += 1
            if fence[2] == "!":
                out.append((fence[3], "block", "\n".join(body)))
            fence = None
        elif fence is None:
            for im in INLINE.finditer(ln):
                out.append((i + 1, "inline", im.group(1)))
        i += 1
    return out


def find_files(paths):
    found = []
    for p in paths:
        if os.path.isfile(p):
            found.append(p)
            continue
        for root, dirs, files in os.walk(p):
            dirs[:] = sorted(d for d in dirs if d not in {".git", "node_modules", "__pycache__"})
            in_commands = os.path.basename(root) == "commands"
            for f in sorted(files):
                if f == "SKILL.md" or (in_commands and f.endswith(".md")):
                    found.append(os.path.join(root, f))
    return found


def cmd_scan(args):
    opts = _opts(args)
    files = find_files(args.paths)
    if not files:
        print("점검할 SKILL.md·commands/*.md 가 없다", file=sys.stderr)
        return 2
    rows = []
    for fp in files:
        with open(fp, encoding="utf-8", errors="replace") as f:
            text = f.read()
        # 스크립트 상대 경로는 스킬 폴더가 아니라 프로젝트 루트 기준이므로 --cwd 로 받는다
        for ln, kind, cmd in extract(text):
            v = judge(cmd, args.cwd, opts)
            rows.append({"file": fp, "line": ln, "kind": kind, "command": cmd, **v.as_dict()})
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        if not rows:
            print(f"스킬 {len(files)}개에 인라인 셸 명령이 없다")
        for r in rows:
            show = " ⏎ ".join(r["command"].splitlines())[:70]
            print(f"{r['decision'].upper():5} {r['file']}:{r['line']}  [{r['rule']}] {show}")
            if r["decision"] != "allow":
                print(f"      → {r['reason']}")
        cnt = {k: sum(1 for r in rows if r["decision"] == k) for k in RANK}
        print(f"-- 파일 {len(files)}개, 인라인 명령 {len(rows)}개: allow {cnt['allow']} · ask {cnt['ask']} · deny {cnt['deny']}")
    bad = any(r["decision"] == "deny" for r in rows) or (args.strict and any(r["decision"] == "ask" for r in rows))
    return 1 if bad else 0


def cmd_check(args):
    v = judge(args.command, args.cwd, _opts(args))
    if args.json:
        print(json.dumps(v.as_dict(), ensure_ascii=False))
    else:
        print(f"{v.decision.upper()} [{v.rule}] {v.reason}")
    return 1 if v.decision == "deny" else 0


def cmd_settings(args):
    me = os.path.abspath(__file__)
    command = f"python3 {me} hook"
    if args.policy:
        command += f" --policy {os.path.abspath(args.policy)}"
    if args.log:
        command += f" --log {os.path.abspath(args.log)}"
    if args.strict_unattended:
        command += " --strict-unattended"
    print(json.dumps({"hooks": {EVENT: [{"hooks": [{"type": "command", "command": command}]}]}},
                     ensure_ascii=False, indent=2))
    print("# 주의: Claude Code 2.1.331 이하는 설정에 이 이벤트가 있으면 시작할 때 대화창이 뜬다 (2.1.332 부터 지원).",
          file=sys.stderr)
    return 0


def _opts(args):
    opts = load_policy(getattr(args, "policy", None))
    opts["strict_unattended"] = bool(getattr(args, "strict_unattended", False))
    return opts


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="skill_shell_guard.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, log=False):
        p.add_argument("--policy", help='정책 JSON: {"default":"ask","allow":[정규식],"deny":[정규식]}')
        p.add_argument("--strict-unattended", action="store_true",
                       help="invoked_by 가 claude·other 이면 ask 를 되묻지 않고 deny 로 바꾼다")
        if log:
            p.add_argument("--log", help="판정을 한 줄씩 JSON으로 남길 파일(명령 본문은 남기지 않음)")

    p = sub.add_parser("hook", help="PreSkillShellCommand 훅으로 쓴다(표준입력 JSON)")
    common(p, log=True)
    p.set_defaults(fn=cmd_hook)
    p = sub.add_parser("check", help="명령 한 줄을 판정")
    p.add_argument("command")
    p.add_argument("--cwd", default=".")
    p.add_argument("--json", action="store_true")
    common(p)
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("scan", help="스킬 폴더의 인라인 셸 명령을 판정")
    p.add_argument("paths", nargs="+")
    p.add_argument("--cwd", default=".", help="스크립트 상대 경로의 기준(프로젝트 루트). 기본 현재 폴더")
    p.add_argument("--strict", action="store_true", help="ask 도 실패(exit 1)로 센다")
    p.add_argument("--json", action="store_true")
    common(p)
    p.set_defaults(fn=cmd_scan)
    p = sub.add_parser("settings", help="settings.json 에 넣을 훅 조각을 출력")
    common(p, log=True)
    p.set_defaults(fn=cmd_settings)
    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except (OSError, ValueError, re.error, json.JSONDecodeError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

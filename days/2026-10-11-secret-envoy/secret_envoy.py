#!/usr/bin/env python3
"""secret-envoy — 비밀값을 이름으로만 부르게 하는 작은 MCP 서버 (stdio, 표준 라이브러리만).

모델은 `run_with_secrets(command, secrets=["DB_URL"])`처럼 이름만 넘긴다. 서버가 백엔드(환경변수·0600 파일·macOS 키체인)에서
값을 꺼내 그 명령의 자식 프로세스 환경에만 넣고, 출력에 값이 보이면(원문·base64·URL 인코딩) `[REDACTED:NAME]`으로 지운다.
값은 트랜스크립트·로그·응답 어디에도 나가지 않는다. 리댁션은 백스톱이고, 진짜 통제는 `--names` 허용 목록과 `--allow-command`다.

  python3 secret_envoy.py serve --backend env --names DEMO_TOKEN,DB_URL      # MCP 서버 (Claude Code .mcp.json / --mcp-config)
  python3 secret_envoy.py serve --backend file --file ~/.secret-envoy.json    # {"NAME": "value"}, 권한 0600 필수
  python3 secret_envoy.py serve --backend keychain --names DB_URL             # security find-generic-password -s secret-envoy -a NAME
  python3 secret_envoy.py run --backend env --names DEMO_TOKEN -- 'printf %s "$DEMO_TOKEN" | wc -c'   # 서버 없이 한 번
  python3 secret_envoy.py list --backend file --file secrets.json
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

SERVER_NAME = "secret-envoy"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSIONS = ("2026-07-28", "2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
MAX_OUTPUT = 20_000
DEFAULT_TIMEOUT = 60
NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
KEYCHAIN_SERVICE = "secret-envoy"


# ---------------------------------------------------------------- 백엔드

class SecretError(Exception):
    pass


@dataclass
class Backend:
    """이름 → 값. 값은 호출한 곳에서만 쓰고 절대 밖으로 내보내지 않는다."""
    kind: str
    names: list[str]
    getter: Callable[[str], str]

    def get(self, name: str) -> str:
        if name not in self.names:
            raise SecretError(f"unknown secret {name!r}; allowed: {', '.join(self.names) or '(none)'}")
        return self.getter(name)


def check_names(names: list[str]) -> list[str]:
    bad = [n for n in names if not NAME_RE.match(n)]
    if bad:
        raise SecretError(f"secret names must look like ENV_VARS (A-Z, 0-9, _): {bad}")
    return names


def env_backend(names: list[str]) -> Backend:
    def get(name: str) -> str:
        v = os.environ.get(name)
        if v is None or v == "":
            raise SecretError(f"secret {name} is not set in the server's environment")
        return v
    return Backend("env", check_names(names), get)


def file_backend(path: Path, names: list[str] | None = None) -> Backend:
    if not path.exists():
        raise SecretError(f"secrets file not found: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise SecretError(f"secrets file {path} must not be group/world readable (mode {mode:o}); chmod 600 it")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not all(isinstance(v, str) for v in data.values()):
        raise SecretError("secrets file must be a JSON object of string values")
    allowed = check_names(names or sorted(data.keys()))
    missing = [n for n in allowed if n not in data]
    if missing:
        raise SecretError(f"secrets file lacks: {missing}")

    def get(name: str) -> str:
        return data[name]
    return Backend("file", allowed, get)


def keychain_backend(names: list[str], service: str = KEYCHAIN_SERVICE) -> Backend:
    """macOS: `security add-generic-password -s secret-envoy -a NAME -w` 로 넣어 둔 값."""
    def get(name: str) -> str:
        try:
            run = subprocess.run(["security", "find-generic-password", "-s", service, "-a", name, "-w"],
                                 capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise SecretError(f"keychain lookup failed for {name}: {type(e).__name__}") from None
        if run.returncode != 0 or not run.stdout.strip():
            raise SecretError(f"keychain has no item service={service} account={name}")
        return run.stdout.rstrip("\n")
    return Backend("keychain", check_names(names), get)


def make_backend(kind: str, names: list[str], file: Path | None) -> Backend:
    if kind == "env":
        return env_backend(names)
    if kind == "file":
        if file is None:
            raise SecretError("--file is required for the file backend")
        return file_backend(file, names or None)
    if kind == "keychain":
        return keychain_backend(names)
    raise SecretError(f"unknown backend {kind!r}")


# ---------------------------------------------------------------- 리댁션

def variants(value: str) -> list[str]:
    """출력에서 지울 형태들: 원문, base64(패딩 유무), URL 인코딩, JSON 이스케이프."""
    out = {value}
    for raw in (value, value + "\n"):  # `echo "$X" | base64` 는 줄바꿈까지 인코딩한다
        b = base64.b64encode(raw.encode()).decode()
        out.add(b)
        out.add(b.rstrip("="))
    out.add(urllib.parse.quote(value, safe=""))
    out.add(json.dumps(value)[1:-1])
    return sorted((v for v in out if len(v) >= 4), key=len, reverse=True)


def redact(text: str, values: dict[str, str]) -> tuple[str, int]:
    """values = {NAME: value}. 긴 값부터 지워 부분 겹침을 막는다. (결과, 지운 횟수)"""
    n = 0
    for name, value in sorted(values.items(), key=lambda kv: len(kv[1]), reverse=True):
        for v in variants(value):
            if v in text:
                n += text.count(v)
                text = text.replace(v, f"[REDACTED:{name}]")
    return text, n


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


# ---------------------------------------------------------------- 실행

@dataclass
class RunResult:
    exit_code: int
    stdout: str
    stderr: str
    redactions: int
    duration_ms: int
    timed_out: bool = False


def run_with_secrets(backend: Backend, command: str, secrets: list[str], *, timeout: int = DEFAULT_TIMEOUT,
                     cwd: str | None = None, allow_command: re.Pattern[str] | None = None) -> RunResult:
    if not command.strip():
        raise SecretError("command is empty")
    if allow_command and not allow_command.search(command):
        raise SecretError("command is not allowed by --allow-command")
    values = {name: backend.get(name) for name in secrets}  # 모르는 이름이면 여기서 실패, 아무것도 실행 안 함
    env = {k: v for k, v in os.environ.items() if k not in values}
    env.update(values)
    t0 = time.time()
    timed_out = False
    try:
        run = subprocess.run(["bash", "-c", command], capture_output=True, text=True, env=env, cwd=cwd,
                             timeout=timeout, stdin=subprocess.DEVNULL)
        out, err, code = run.stdout, run.stderr, run.returncode
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        err = (e.stderr or b"").decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        code, timed_out = 124, True
    out, n1 = redact(out[:MAX_OUTPUT] + ("\n…[truncated]" if len(out) > MAX_OUTPUT else ""), values)
    err, n2 = redact(err[:MAX_OUTPUT] + ("\n…[truncated]" if len(err) > MAX_OUTPUT else ""), values)
    return RunResult(code, out, err, n1 + n2, int((time.time() - t0) * 1000), timed_out)


# ---------------------------------------------------------------- MCP

TOOLS = [
    {
        "name": "list_secrets",
        "description": "List the secret NAMES this server can inject (never values). Use a name with run_with_secrets.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "secret_fingerprint",
        "description": "Check that a secret exists without seeing it: returns its length and a sha256 prefix.",
        "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"], "additionalProperties": False},
    },
    {
        "name": "run_with_secrets",
        "description": ("Run a bash command with the named secrets set as environment variables in that child process only. "
                        "Refer to them as $NAME inside the command. Output is returned with any secret value (plain, base64, "
                        "url-encoded) replaced by [REDACTED:NAME]. The values never enter the conversation."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "bash -c command"},
                "secrets": {"type": "array", "items": {"type": "string"}, "description": "secret names to inject, e.g. [\"DB_URL\"]"},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 600},
                "cwd": {"type": "string"},
            },
            "required": ["command", "secrets"],
            "additionalProperties": False,
        },
    },
]


class Server:
    def __init__(self, backend: Backend, *, allow_command: re.Pattern[str] | None = None, audit: Path | None = None):
        self.backend = backend
        self.allow_command = allow_command
        self.audit = audit
        self.initialized = False

    # --- JSON-RPC ---
    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        """요청 하나 → 응답(알림이면 None)."""
        method = msg.get("method")
        mid = msg.get("id")
        params = msg.get("params") or {}
        if method == "initialize":
            want = str(params.get("protocolVersion") or PROTOCOL_VERSIONS[0])
            ver = want if want in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            return self._ok(mid, {"protocolVersion": ver, "capabilities": {"tools": {}},
                                  "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                                  "instructions": ("Secrets are referenced by NAME only. Call list_secrets, then run_with_secrets "
                                                   "with $NAME in the command. Never ask the user to paste secret values.")})
        if method == "notifications/initialized":
            self.initialized = True
            return None
        if method == "ping":
            return self._ok(mid, {})
        if method == "tools/list":
            return self._ok(mid, {"tools": TOOLS})
        if method == "tools/call":
            return self._call(mid, params)
        if mid is None:
            return None  # 모르는 알림은 무시
        return self._err(mid, -32601, f"method not found: {method}")

    def _call(self, mid: Any, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            if name == "list_secrets":
                text = json.dumps({"backend": self.backend.kind, "secrets": self.backend.names})
            elif name == "secret_fingerprint":
                v = self.backend.get(str(args.get("name", "")))
                text = json.dumps({"name": args.get("name"), "length": len(v), "sha256_12": fingerprint(v)})
            elif name == "run_with_secrets":
                secrets = [str(s) for s in (args.get("secrets") or [])]
                r = run_with_secrets(self.backend, str(args.get("command", "")), secrets,
                                     timeout=int(args.get("timeout_seconds") or DEFAULT_TIMEOUT),
                                     cwd=args.get("cwd"), allow_command=self.allow_command)
                self._audit(args.get("command", ""), secrets, r)
                text = json.dumps({"exit_code": r.exit_code, "stdout": r.stdout, "stderr": r.stderr,
                                   "redactions": r.redactions, "duration_ms": r.duration_ms, "timed_out": r.timed_out}, ensure_ascii=False)
            else:
                return self._err(mid, -32602, f"unknown tool: {name}")
        except SecretError as e:
            return self._ok(mid, {"content": [{"type": "text", "text": f"secret-envoy: {e}"}], "isError": True})
        return self._ok(mid, {"content": [{"type": "text", "text": text}], "isError": False})

    def _audit(self, command: str, secrets: list[str], r: RunResult) -> None:
        if not self.audit:
            return
        line = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "secrets": secrets, "command": command[:200],
                "exit_code": r.exit_code, "redactions": r.redactions, "duration_ms": r.duration_ms}
        with open(self.audit, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    @staticmethod
    def _ok(mid: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    @staticmethod
    def _err(mid: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    # --- stdio loop (newline-delimited JSON) ---
    def serve(self, inp=sys.stdin, out=sys.stdout) -> int:
        for line in inp:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                out.write(json.dumps(self._err(None, -32700, "parse error")) + "\n")
                out.flush()
                continue
            resp = self.handle(msg)
            if resp is not None:
                out.write(json.dumps(resp, ensure_ascii=False) + "\n")
                out.flush()
        return 0


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["serve", "run", "list"])
    ap.add_argument("--backend", default=os.environ.get("SECRET_ENVOY_BACKEND", "env"), choices=["env", "file", "keychain"])
    ap.add_argument("--names", default=os.environ.get("SECRET_ENVOY_NAMES", ""), help="허용할 비밀값 이름, 쉼표 구분 (file 백엔드는 생략 시 파일의 키 전부)")
    ap.add_argument("--file", type=Path, default=(Path(os.environ["SECRET_ENVOY_FILE"]) if os.environ.get("SECRET_ENVOY_FILE") else None))
    ap.add_argument("--allow-command", help="이 정규식에 맞는 명령만 실행 (예: '^(psql|curl) ')")
    ap.add_argument("--audit", type=Path, help="실행 기록(JSONL): 이름·명령·종료코드만, 값은 절대 안 적음")
    ap.add_argument("--secrets", default="", help="run 모드: 주입할 이름, 쉼표 구분 (생략 시 --names 전부)")
    ap.add_argument("command", nargs="*", help="run 모드: 실행할 명령 (-- 뒤)")
    a = ap.parse_args(argv)

    names = [n for n in a.names.split(",") if n]
    try:
        backend = make_backend(a.backend, names, a.file)
    except SecretError as e:
        print(f"secret-envoy: {e}", file=sys.stderr)
        return 2
    allow = re.compile(a.allow_command) if a.allow_command else None

    if a.mode == "list":
        print(json.dumps({"backend": backend.kind, "secrets": backend.names}))
        return 0
    if a.mode == "run":
        cmd = " ".join(a.command)
        secrets = [s for s in a.secrets.split(",") if s] or backend.names
        try:
            r = run_with_secrets(backend, cmd, secrets, allow_command=allow)
        except SecretError as e:
            print(f"secret-envoy: {e}", file=sys.stderr)
            return 2
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        print(f"secret-envoy: exit {r.exit_code}, {r.redactions} redaction(s), {r.duration_ms} ms", file=sys.stderr)
        return r.exit_code
    return Server(backend, allow_command=allow, audit=a.audit).serve()


if __name__ == "__main__":
    sys.exit(main())

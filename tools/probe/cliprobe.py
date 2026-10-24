#!/usr/bin/env python3
"""cliprobe - map a command-line tool's commands from its own help output.

Every call is ``<exe> [<subcommand path...>] <help flag>``, ``<exe> help <path...>``
or ``<exe> <version flag>``. Nothing is executed for real. Each call has a
timeout; on timeout the whole process tree is killed and the call is recorded
as ``timeout``. For a GUI program that usually means a window opened, and on
Windows ``window_seen`` confirms it.

    python cliprobe.py crawl --exe PATH [--interpreter EXE] [--out DIR]
                             [--max-depth 4] [--timeout 20] [--max-calls 300]
                             [--seed "terrain add" ...] [--allow NAME ...]
                             [--cwd DIR] [--dry-run]
    python cliprobe.py parse HELP.txt

Outputs: DIR/cli_tree.json, DIR/cli_tree.md, DIR/raw/NNNN.txt
Standard library only; psutil is used when installed for process-tree handling.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import platform
import re
import signal
import subprocess
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

try:  # optional
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - exercised only without psutil
    psutil = None

ROOT_HELP_ARGS: list[list[str]] = [["--help"], ["-h"], ["-?"], ["/?"], ["help"]]
SUB_HELP_FLAGS: list[str] = ["--help", "-h", "-?"]
VERSION_FLAGS: list[str] = ["--version", "-V", "version", "-v"]
RISKY = {
    "delete", "remove", "rm", "purge", "clean", "reset", "update", "upgrade",
    "install", "uninstall", "login", "logout", "auth", "signin", "signout",
    "self-update", "selfupdate", "format", "drop", "kill", "shutdown", "credits",
}
NO_RECURSE = {"help", "version"}
PROBE_ENV = {"NO_COLOR": "1", "TERM": "dumb", "CI": "1", "DOTNET_CLI_TELEMETRY_OPTOUT": "1"}

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)")
_BOX_RE = re.compile(r"[─-╿]")
_SECTION_KEYS = {
    "usage": "usage",
    "commands": "commands", "command": "commands", "subcommands": "commands",
    "sub-commands": "commands", "available commands": "commands", "verbs": "commands",
    "available verbs": "commands", "actions": "commands", "management commands": "commands",
    "options": "options", "global options": "options", "flags": "options",
    "optional arguments": "options", "general options": "options",
    "arguments": "arguments", "positional arguments": "arguments",
    "description": "description", "examples": "examples", "example": "examples",
}
_CMD_LINE_RE = re.compile(
    r"^\s+(?P<name>[A-Za-z0-9][\w.:-]*)"
    r"(?P<args>(?:\s+(?:<[^>]+>|\[[^\]]+\]|[A-Z][A-Z0-9_]+(?:\.\.\.)?))*)"
    r"(?:\s{2,}(?P<desc>\S.*))?$"
)
_VERB_LINE_RE = re.compile(r"^\s{1,8}(?P<name>[a-z][\w-]*)\s{2,}(?P<desc>\S.*)$")
_BRACES_RE = re.compile(r"\{([\w,.:-]+)\}")
_VERSION_RE = re.compile(r"\d+\.\d+")
_CLP_OPT_RE = re.compile(
    r"^  (?P<flags>(?:-[a-zA-Z0-9?],\s+)?--\S+)(?:\s{2,}(?P<desc>\S.*))?$"
)
_CLP_POS_RE = re.compile(
    r"^  (?P<name>[a-zA-Z0-9][\w.:-]*)\s+\(pos\.\s*(?P<index>\d+)\)(?:\s{2,}(?P<desc>\S.*))?$"
)


# --------------------------------------------------------------------------- running


@dataclasses.dataclass
class CallResult:
    argv: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool
    window_seen: bool | None  # None = not checked (non-Windows)


def _decode(data: bytes) -> str:
    if not data:
        return ""
    if data.count(b"\x00") > len(data) // 4:  # looks like UTF-16LE
        try:
            return data.decode("utf-16-le")
        except UnicodeDecodeError:
            pass
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252" if os.name == "nt" else "latin-1", errors="replace")


def _tree_pids(pid: int) -> set[int]:
    pids = {pid}
    if psutil is not None:
        try:
            pids |= {c.pid for c in psutil.Process(pid).children(recursive=True)}
        except psutil.Error:
            pass
    return pids


def _visible_window_pids() -> set[int]:
    """PIDs owning visible top-level windows (Windows only)."""
    if os.name != "nt":
        return set()
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    found: set[int] = set()
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd: int, _lparam: int) -> bool:
        if user32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            found.add(int(pid.value))
        return True

    user32.EnumWindows(proto(_cb), 0)
    return found


def kill_tree(proc: subprocess.Popen[bytes]) -> None:
    pid = proc.pid
    if psutil is not None:
        try:
            parent = psutil.Process(pid)
            for child in parent.children(recursive=True):
                try:
                    child.kill()
                except psutil.Error:
                    pass
        except psutil.Error:
            pass
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


def run(argv: list[str], timeout: float, cwd: str | os.PathLike[str] | None = None,
        env: dict[str, str] | None = None, watch_windows: bool = True) -> CallResult:
    """Run argv with stdin closed, a hard timeout and process-tree cleanup."""
    full_env = dict(os.environ)
    full_env.update(PROBE_ENV)
    if env:
        full_env.update(env)
    kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "stdin": subprocess.DEVNULL,
        "cwd": str(cwd) if cwd else None, "env": full_env,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    start = time.monotonic()
    try:
        proc = subprocess.Popen(argv, **kwargs)
    except OSError as exc:
        return CallResult(argv, None, "", f"<launch failed: {exc}>", 0.0, False, None)
    check_windows = watch_windows and os.name == "nt"
    window_seen: bool | None = False if check_windows else None
    timed_out = False
    out = err = b""
    while True:
        try:
            out, err = proc.communicate(timeout=0.5)
            break
        except subprocess.TimeoutExpired:
            if check_windows and not window_seen:
                if _tree_pids(proc.pid) & _visible_window_pids():
                    window_seen = True
            if time.monotonic() - start >= timeout:
                timed_out = True
                kill_tree(proc)
                try:
                    out, err = proc.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    out, err = b"", b"<output unavailable after kill>"
                break
    return CallResult(argv, None if timed_out else proc.returncode, _decode(out), _decode(err),
                      round(time.monotonic() - start, 3), timed_out, window_seen)


# --------------------------------------------------------------------------- parsing


def clean(text: str) -> str:
    text = _ANSI_RE.sub("", text)
    text = _BOX_RE.sub(" ", text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _section_of(line: str) -> tuple[str | None, str]:
    """Return (section, inline_rest) when the line is a section header."""
    stripped = line.strip()
    if not stripped:
        return None, ""
    m = re.match(r"^(?P<h>[A-Za-z][A-Za-z -]{0,40}?)\s*:\s*(?P<rest>.*)$", stripped)
    if m and m.group("h").lower() in _SECTION_KEYS:
        return _SECTION_KEYS[m.group("h").lower()], m.group("rest").strip()
    if stripped.lower() in _SECTION_KEYS and (stripped.isupper() or stripped[0].isupper()):
        return _SECTION_KEYS[stripped.lower()], ""
    return None, ""


def _parse_clp_leaf(lines: list[str]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    options: list[dict[str, str]] = []
    positionals: list[dict[str, Any]] = []
    curr: dict[str, Any] | None = None
    desc_col: int | None = None
    for line in lines:
        if not line.strip():
            curr = None
            desc_col = None
            continue
        m_opt = _CLP_OPT_RE.match(line)
        if m_opt:
            desc = (m_opt.group("desc") or "").strip()
            opt_entry = {"flags": m_opt.group("flags"), "description": desc}
            options.append(opt_entry)
            curr = opt_entry
            desc_col = m_opt.start("desc") if m_opt.group("desc") else None
            continue
        m_pos = _CLP_POS_RE.match(line)
        if m_pos:
            desc = (m_pos.group("desc") or "").strip()
            pos_entry = {
                "name": m_pos.group("name"),
                "index": int(m_pos.group("index")),
                "required": desc.startswith("Required."),
                "description": desc,
            }
            positionals.append(pos_entry)
            curr = pos_entry
            desc_col = m_pos.start("desc") if m_pos.group("desc") else None
            continue
        if curr is not None and desc_col is not None:
            indent = len(line) - len(line.lstrip())
            if indent >= desc_col:
                curr["description"] = (curr["description"] + " " + line.strip()).strip()
                continue
        curr = None
        desc_col = None
    return options, positionals


def parse_help(text: str) -> dict[str, Any]:
    """Parse help text from common CLI frameworks into usage/commands/options."""
    text = clean(text)
    lines = text.split("\n")
    usage: list[str] = []
    commands: list[dict[str, str]] = []
    options: list[dict[str, str]] = []
    sections: list[str] = []
    current: str | None = None
    last_cmd: dict[str, str] | None = None
    for line in lines:
        sec, rest = _section_of(line)
        if sec:
            current = sec
            sections.append(sec)
            last_cmd = None
            if sec == "usage" and rest:
                usage.append(rest)
            continue
        if not line.strip():
            if current == "usage" and usage:
                current = None
            continue
        if current == "usage":
            usage.append(line.strip())
        elif current == "commands":
            indent = len(line) - len(line.lstrip())
            m = _CMD_LINE_RE.match(line)
            # A deeper-indented line with no description column continues the previous entry.
            is_continuation = (last_cmd is not None and indent > int(last_cmd["_indent"]) + 4
                               and (m is None or m.group("desc") is None))
            if m and not is_continuation and not m.group("name").startswith("-"):
                last_cmd = {"name": m.group("name"), "args": (m.group("args") or "").strip(),
                            "description": (m.group("desc") or "").strip(), "_indent": str(indent)}
                commands.append(last_cmd)
            elif last_cmd is not None:
                last_cmd["description"] = (last_cmd["description"] + " " + line.strip()).strip()
        elif current == "options":
            stripped = line.strip()
            if stripped.startswith(("-", "/")):
                parts = re.split(r"\s{2,}", stripped, maxsplit=1)
                options.append({"flags": parts[0], "description": parts[1] if len(parts) > 1 else ""})
            elif options:
                options[-1]["description"] = (options[-1]["description"] + " " + stripped).strip()
    fmt = _guess_format(text)
    if not commands:
        for u in usage:
            for group in _BRACES_RE.findall(u):
                commands.extend({"name": n, "args": "", "description": "", "_indent": "0"}
                                for n in group.split(",") if n)
    if not commands:
        verbs = [m for m in (_VERB_LINE_RE.match(ln) for ln in lines) if m]
        names = {m.group("name") for m in verbs}
        if verbs and ({"help", "version"} & names):
            fmt = "commandlineparser"
            commands = [{"name": m.group("name"), "args": "", "description": m.group("desc").strip(),
                         "_indent": "2"} for m in verbs]
    positionals: list[dict[str, Any]] = []
    if not options:
        clp_opts, clp_pos = _parse_clp_leaf(lines)
        if clp_opts or clp_pos:
            fmt = "commandlineparser"
            options = clp_opts
            positionals = clp_pos
    seen: set[str] = set()
    uniq = []
    for c in commands:
        if c["name"] not in seen:
            seen.add(c["name"])
            uniq.append({k: v for k, v in c.items() if not k.startswith("_")})
    return {
        "format": fmt,
        "usage": usage,
        "commands": uniq,
        "options": options,
        "positionals": positionals,
        "sections": sections,
    }


def _guess_format(text: str) -> str:
    if "USAGE:" in text and ("COMMANDS:" in text or "OPTIONS:" in text):
        return "spectre"
    if "-?, -h, --help" in text:
        return "system.commandline"
    if "Show this message and exit" in text:
        return "click/typer"
    if "show this help message and exit" in text:
        return "argparse"
    return "generic"


def is_help(parsed: dict[str, Any], raw: str) -> bool:
    if parsed.get("commands") or parsed.get("options") or parsed.get("positionals"):
        return True
    return bool(parsed.get("usage")) and "usage" in raw.lower()


def looks_like_version(res: CallResult) -> bool:
    out = (res.stdout or res.stderr).strip()
    return (not res.timed_out and res.exit_code == 0 and 0 < len(out) < 400
            and bool(_VERSION_RE.search(out)))


# --------------------------------------------------------------------------- crawling


class Crawler:
    def __init__(self, exe: str, interpreter: str | None, out_dir: Path, max_depth: int,
                 timeout: float, max_calls: int, allow: set[str], cwd: str | None) -> None:
        self.base = ([interpreter] if interpreter else []) + [exe]
        self.out_dir = out_dir
        self.raw_dir = out_dir / "raw"
        self.max_depth = max_depth
        self.timeout = timeout
        self.max_calls = max_calls
        self.allow = {a.lower() for a in allow}
        self.cwd = cwd
        self.calls = 0
        self.nodes: dict[tuple[str, ...], dict[str, Any]] = {}
        self.skipped: list[dict[str, Any]] = []
        self.truncated = False

    def _call(self, args: list[str]) -> tuple[CallResult, str]:
        self.calls += 1
        res = run(self.base + args, self.timeout, cwd=self.cwd)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        raw_name = f"{self.calls:04d}.txt"
        header = (f"argv: {json.dumps(res.argv)}\nexit_code: {res.exit_code}\n"
                  f"timed_out: {res.timed_out}\nwindow_seen: {res.window_seen}\n"
                  f"duration_s: {res.duration_s}\n")
        (self.raw_dir / raw_name).write_text(
            header + "----- stdout -----\n" + res.stdout + "\n----- stderr -----\n" + res.stderr,
            encoding="utf-8")
        return res, raw_name

    def _attempts_for(self, path: tuple[str, ...]) -> list[list[str]]:
        if not path:
            return [list(a) for a in ROOT_HELP_ARGS]
        return [list(path) + [f] for f in SUB_HELP_FLAGS] + [["help", *path]]

    def probe(self, path: tuple[str, ...]) -> dict[str, Any]:
        attempts = []
        node: dict[str, Any] = {"path": list(path), "status": "no-help", "help": None}
        for args in self._attempts_for(path):
            if self.calls >= self.max_calls:
                self.truncated = True
                break
            res, raw = self._call(args)
            combined = res.stdout + ("\n" + res.stderr if res.stderr else "")
            parsed = parse_help(combined) if not res.timed_out else None
            status = ("timeout" if res.timed_out else
                      "help" if parsed and is_help(parsed, combined) else
                      "error" if res.exit_code not in (0, None) else
                      "no-output" if not combined.strip() else "other")
            attempts.append({"args": args, "status": status, "exit_code": res.exit_code,
                             "duration_s": res.duration_s, "window_seen": res.window_seen,
                             "raw": raw})
            if status == "help":
                node.update(status="help", help=parsed, help_args=args, exit_code=res.exit_code)
                break
        if node["status"] != "help" and attempts:
            node["status"] = ("timeout" if any(a["status"] == "timeout" for a in attempts)
                              else attempts[-1]["status"])
        node["attempts"] = attempts
        node["window_seen"] = any(a.get("window_seen") for a in attempts) if attempts else None
        return node

    def version(self) -> dict[str, Any] | None:
        for flag in VERSION_FLAGS:
            if self.calls >= self.max_calls:
                return None
            res, raw = self._call([flag])
            if looks_like_version(res):
                return {"args": [flag], "text": (res.stdout or res.stderr).strip(), "raw": raw}
            if res.timed_out:  # a GUI program opens a window for every flag; stop early
                return {"args": [flag], "text": None, "timed_out": True, "raw": raw}
        return None

    def _expand(self, path: tuple[str, ...], node: dict[str, Any],
                queue: deque[tuple[str, ...]], queued: set[tuple[str, ...]]) -> None:
        if node["status"] != "help" or len(path) >= self.max_depth:
            return
        for cmd in node["help"]["commands"]:
            child = path + (cmd["name"],)
            if child in queued:
                continue
            queued.add(child)
            low = cmd["name"].lower()
            if low in NO_RECURSE:
                self.skipped.append({"path": list(child), "reason": "help/version verb"})
            elif low in RISKY and low not in self.allow:
                self.skipped.append({"path": list(child), "reason": "risky name (use --allow)"})
            else:
                queue.append(child)

    def crawl(self, seeds: list[str]) -> dict[str, Any]:
        started = dt.datetime.now().isoformat(timespec="seconds")
        queue: deque[tuple[str, ...]] = deque()
        queued: set[tuple[str, ...]] = {()}
        self.nodes[()] = self.probe(())  # root help first: it matters most when calls are limited
        version = self.version()
        self._expand((), self.nodes[()], queue, queued)
        for seed in seeds:
            sp = tuple(seed.split())
            if sp and sp not in queued:
                queue.append(sp)
                queued.add(sp)
        while queue:
            if self.calls >= self.max_calls:
                self.truncated = True
                break
            path = queue.popleft()
            self.nodes[path] = self.probe(path)
            self._expand(path, self.nodes[path], queue, queued)
        return {
            "tool": "cliprobe", "schema": 1, "exe": self.base[-1], "argv_base": self.base,
            "platform": platform.platform(), "python": sys.version.split()[0],
            "started": started, "finished": dt.datetime.now().isoformat(timespec="seconds"),
            "calls": self.calls, "truncated": self.truncated, "version": version,
            "nodes": [self.nodes[k] for k in sorted(self.nodes)], "skipped": self.skipped,
        }


def render_markdown(tree: dict[str, Any]) -> str:
    name = Path(tree["exe"]).name
    lines = [f"# CLI tree: {name}", "",
             f"- exe: `{tree['exe']}`",
             f"- crawled: {tree['started']} → {tree['finished']} ({tree['calls']} calls"
             + (", TRUNCATED" if tree["truncated"] else "") + ")",
             f"- version: `{(tree['version'] or {}).get('text', 'unknown')}`", ""]
    nodes = {tuple(n["path"]): n for n in tree["nodes"]}
    lines += ["## Commands", ""]
    for path in sorted(nodes):
        node = nodes[path]
        depth = len(path)
        label = " ".join([name, *path])
        desc = ""
        if path and tuple(path[:-1]) in nodes and nodes[tuple(path[:-1])].get("help"):
            for c in nodes[tuple(path[:-1])]["help"]["commands"]:
                if c["name"] == path[-1]:
                    desc = c["description"]
                    break
        flag = " ⚠ window" if node.get("window_seen") else ""
        lines.append(f"{'  ' * depth}- `{label}` — {desc or '(no description)'} "
                     f"[{node['status']}]{flag}")
    if tree["skipped"]:
        lines += ["", "## Skipped", ""]
        lines += [f"- `{' '.join([name, *s['path']])}` — {s['reason']}" for s in tree["skipped"]]
    lines += ["", "## Options by command", ""]
    for path in sorted(nodes):
        node = nodes[path]
        help_data = node.get("help")
        if help_data and (help_data.get("options") or help_data.get("positionals")):
            lines.append(f"### `{' '.join([name, *path])}`")
            if help_data.get("usage"):
                lines.append("Usage: `" + " ".join(help_data["usage"]) + "`")
            lines += [f"- `{o['flags']}` {o['description']}" for o in help_data.get("options", [])]
            for p in help_data.get("positionals", []):
                req = " required" if p.get("required") else ""
                desc = p.get("description", "")
                name_idx = f"{p['name']} (pos. {p['index']})"
                suffix = f" — {desc}" if desc else ""
                lines.append(f"- `{name_idx}`{req}{suffix}")
            lines.append("")
    no_help = [n for n in tree["nodes"] if n["status"] != "help"]
    if no_help:
        lines += ["## Nodes without parseable help", ""]
        lines += [f"- `{' '.join([name, *n['path']])}` → {n['status']}" for n in no_help]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("crawl", help="discover the command tree")
    c.add_argument("--exe", required=True)
    c.add_argument("--interpreter", help="prefix, e.g. a Python executable for .py fakes")
    c.add_argument("--out", default="cli_probe_out")
    c.add_argument("--max-depth", type=int, default=4)
    c.add_argument("--timeout", type=float, default=20.0)
    c.add_argument("--max-calls", type=int, default=300)
    c.add_argument("--seed", action="append", default=[], help='extra path, e.g. "terrain add"')
    c.add_argument("--allow", action="append", default=[], help="risky name to permit")
    c.add_argument("--cwd", help="working directory for every call (use a scratch dir)")
    c.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("parse", help="parse a saved help text")
    p.add_argument("file")
    args = ap.parse_args(argv)

    if args.cmd == "parse":
        text = Path(args.file).read_text(encoding="utf-8", errors="replace")
        print(json.dumps(parse_help(text), indent=2))
        return 0

    out = Path(args.out)
    if args.dry_run:
        base = ([args.interpreter] if args.interpreter else []) + [args.exe]
        print("version attempts:", [base + [f] for f in VERSION_FLAGS])
        print("root help attempts:", [base + a for a in ROOT_HELP_ARGS])
        print("subcommands are then probed only as: <path> --help | -h | -?  and  help <path>")
        return 0
    if args.cwd:
        Path(args.cwd).mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    crawler = Crawler(args.exe, args.interpreter, out, args.max_depth, args.timeout,
                      args.max_calls, set(args.allow), args.cwd)
    tree = crawler.crawl(args.seed)
    (out / "cli_tree.json").write_text(json.dumps(tree, indent=2), encoding="utf-8")
    (out / "cli_tree.md").write_text(render_markdown(tree), encoding="utf-8")
    helped = sum(1 for n in tree["nodes"] if n["status"] == "help")
    print(f"{helped}/{len(tree['nodes'])} paths returned help; {tree['calls']} calls; "
          f"{len(tree['skipped'])} skipped -> {out / 'cli_tree.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

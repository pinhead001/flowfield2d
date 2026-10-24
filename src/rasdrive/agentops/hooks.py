"""Claude Code hook handlers (SessionStart, PreToolUse, TaskCompleted).

PreToolUse denies, via `permissionDecision: deny`:
  - Bash commands matching any `hooks.deny_bash` regex (push, firewall, registry ...)
  - any tool input containing a `hooks.deny_substrings` entry (case-insensitive)
  - teammate spawns (`hooks.teammate_tools`) unless the governor mode is `normal`
Malformed input fails open (no output) so a hook bug never wedges a session;
the permission deny rules in settings.json are the second line.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from rasdrive.agentops import governor
from rasdrive.agentops.config import AgentOpsConfig


def _read(stdin: TextIO) -> dict[str, Any]:
    try:
        d = json.loads(stdin.read() or "{}")
        return d if isinstance(d, dict) else {}
    except json.JSONDecodeError:
        return {}


def _deny(stdout: TextIO, reason: str) -> None:
    stdout.write(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": reason}}))


def check(cfg: AgentOpsConfig, tool: str, tool_input: Any,
          now: datetime | None = None) -> str | None:
    """Return a denial reason, or None to defer to the normal permission flow."""
    blob = json.dumps(tool_input, default=str).lower()
    for s in cfg.hooks.deny_substrings:
        if s.lower() in blob:
            return f"agentops: tool input touches '{s}', which is never allowed"
    if tool == "Bash" and isinstance(tool_input, dict):
        cmd = str(tool_input.get("command", ""))
        for pat in cfg.hooks.deny_bash:
            if re.search(pat, cmd, re.IGNORECASE):
                return f"agentops: command matches blocked pattern {pat!r}"
    if tool in cfg.hooks.teammate_tools:
        mode = governor.status(cfg, now=now).mode
        if mode != "normal":
            return f"agentops: teammate spawns need governor mode 'normal' (now '{mode}')"
    return None


def pre_tool_use(cfg: AgentOpsConfig, stdin: TextIO, stdout: TextIO,
                 now: datetime | None = None) -> None:
    d = _read(stdin)
    tool = d.get("tool_name")
    if not isinstance(tool, str):
        return
    reason = check(cfg, tool, d.get("tool_input", {}), now=now)
    if reason:
        _deny(stdout, reason)


def session_start(cfg: AgentOpsConfig, stdin: TextIO, stdout: TextIO,
                  now: datetime | None = None) -> None:
    _read(stdin)
    try:
        text = governor.render(governor.status(cfg, now=now))
    except Exception as e:  # noqa: BLE001 - never block session start
        text = f"governor: unavailable ({e})"
    stdout.write(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart", "additionalContext": text}}))


def task_completed(cfg: AgentOpsConfig, stdin: TextIO, stderr: TextIO) -> int:
    """Run the acceptance command; exit code 2 blocks completion with the output tail."""
    d = _read(stdin)
    cmd = cfg.hooks.task_acceptance
    if not cmd:
        return 0
    cwd = Path(str(d.get("cwd") or "."))
    p = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode == 0:
        return 0
    stderr.write(f"acceptance failed ({cmd}, exit {p.returncode}):\n"
                 f"{(p.stdout + p.stderr)[-3000:]}\n")
    return 2

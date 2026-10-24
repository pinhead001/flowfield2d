"""Claude Code status-line command: records the rate-limit meter, prints one line.

Reads the status-line JSON on stdin and writes `claude_usage.json` with
`rate_limits.five_hour` and `seven_day` (`used_percentage`, `resets_at` in
epoch seconds). Fields Claude Code leaves out are recorded as "unknown".
Never raises: a broken status line must not break the session.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, TextIO

from rasdrive.agentops.config import AgentOpsConfig
from rasdrive.agentops.ledger import write_json_atomic

UNKNOWN = "unknown"


def _window(rl: Any, name: str) -> dict[str, Any]:
    w = rl.get(name) if isinstance(rl, dict) else None
    w = w if isinstance(w, dict) else {}
    out: dict[str, Any] = {}
    for key in ("used_percentage", "resets_at"):
        v = w.get(key)
        out[key] = v if isinstance(v, int | float) and not isinstance(v, bool) else UNKNOWN
    return out


def run(cfg: AgentOpsConfig, stdin: TextIO, stdout: TextIO, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    try:
        payload = json.loads(stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    rl = payload.get("rate_limits") if isinstance(payload, dict) else None
    usage: dict[str, Any] = {"updated_at": now.isoformat(),
                             "five_hour": _window(rl, "five_hour"),
                             "seven_day": _window(rl, "seven_day")}
    try:
        write_json_atomic(cfg.claude_usage_path, usage)
    except OSError:
        pass
    parts = []
    for label, key in (("5h", "five_hour"), ("7d", "seven_day")):
        v = usage[key]["used_percentage"]
        parts.append(f"{label} {v:.0f}%" if v != UNKNOWN else f"{label} ?")
    try:
        from rasdrive.agentops import governor

        parts.append(f"gov {governor.status(cfg, now=now).mode}")
    except Exception:  # noqa: BLE001 - status line must not fail
        parts.append("gov ?")
    stdout.write(" | ".join(parts) + "\n")

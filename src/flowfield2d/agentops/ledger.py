"""Append-only JSONL ledger of delegate calls and other agent-ops events."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from filelock import FileLock


def append(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".lock"):
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")


def read(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def since(records: list[dict[str, Any]], t: datetime) -> list[dict[str, Any]]:
    out = []
    for r in records:
        try:
            if datetime.fromisoformat(str(r["ts"])) >= t:
                out.append(r)
        except (KeyError, ValueError):
            continue
    return out


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)

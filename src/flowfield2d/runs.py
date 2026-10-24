"""Run registry (JSON plus file lock), scheduler, resume, parallel caps."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import filelock


class RunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass
class RunRecord:
    run_id: str
    domain: str
    scenario: str
    plan: str
    state: RunState
    seq: int
    pid: int | None = None
    started: str | None = None
    finished: str | None = None
    attempts: int = 0
    detail: str = ""


class DuplicateRun(ValueError):
    """Raised when adding a run_id that already exists in the registry."""


class BadTransition(ValueError):
    """Raised when a state transition is not allowed from the current state."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _record_from_dict(d: dict[str, Any]) -> RunRecord:
    return RunRecord(
        run_id=str(d["run_id"]),
        domain=str(d["domain"]),
        scenario=str(d["scenario"]),
        plan=str(d["plan"]),
        state=RunState(str(d["state"])),
        seq=int(d["seq"]),
        pid=int(d["pid"]) if d.get("pid") is not None else None,
        started=str(d["started"]) if d.get("started") is not None else None,
        finished=str(d["finished"]) if d.get("finished") is not None else None,
        attempts=int(d.get("attempts", 0)),
        detail=str(d.get("detail", "")),
    )


def _load(path: Path) -> dict[str, RunRecord]:
    if not path.exists():
        return {}
    raw: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    records: dict[str, RunRecord] = {}
    for r in raw:
        rec = _record_from_dict(r)
        records[rec.run_id] = rec
    return records


def _save(path: Path, records: dict[str, RunRecord]) -> None:
    rows = sorted(records.values(), key=lambda r: r.seq)
    payload = json.dumps([asdict(r) for r in rows], indent=2)
    dir_ = path.parent
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class Registry:
    """Persistent run registry backed by a single JSON file with file locking."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = filelock.FileLock(str(path) + ".lock")

    # ------------------------------------------------------------------
    # Public API – every method acquires the lock, re-reads, mutates, writes
    # ------------------------------------------------------------------

    def add(self, run_id: str, domain: str, scenario: str, plan: str) -> RunRecord:
        """Register a new run in QUEUED state. Raises DuplicateRun if id exists."""
        with self._lock:
            records = _load(self._path)
            if run_id in records:
                raise DuplicateRun(f"run_id already exists: {run_id!r}")
            seq = len(records)
            rec = RunRecord(
                run_id=run_id,
                domain=domain,
                scenario=scenario,
                plan=plan,
                state=RunState.QUEUED,
                seq=seq,
            )
            records[run_id] = rec
            _save(self._path, records)
            return rec

    def start(self, run_id: str, pid: int) -> RunRecord:
        """Transition to RUNNING. Allowed from QUEUED or INTERRUPTED."""
        with self._lock:
            records = _load(self._path)
            rec = records[run_id]
            if rec.state not in (RunState.QUEUED, RunState.INTERRUPTED):
                raise BadTransition(
                    f"Cannot start from state {rec.state!r} for run {run_id!r}"
                )
            rec.state = RunState.RUNNING
            rec.pid = pid
            rec.started = _utc_now()
            rec.attempts += 1
            _save(self._path, records)
            return rec

    def finish(self, run_id: str, ok: bool, detail: str = "") -> RunRecord:
        """Transition to DONE or FAILED. Only allowed from RUNNING."""
        with self._lock:
            records = _load(self._path)
            rec = records[run_id]
            if rec.state is not RunState.RUNNING:
                raise BadTransition(
                    f"Cannot finish from state {rec.state!r} for run {run_id!r}"
                )
            rec.state = RunState.DONE if ok else RunState.FAILED
            rec.finished = _utc_now()
            rec.detail = detail
            rec.pid = None
            _save(self._path, records)
            return rec

    def requeue(self, run_id: str) -> RunRecord:
        """Return a FAILED or INTERRUPTED run to QUEUED."""
        with self._lock:
            records = _load(self._path)
            rec = records[run_id]
            if rec.state not in (RunState.FAILED, RunState.INTERRUPTED):
                raise BadTransition(
                    f"Cannot requeue from state {rec.state!r} for run {run_id!r}"
                )
            rec.state = RunState.QUEUED
            _save(self._path, records)
            return rec

    def reconcile(self, is_alive: Callable[[int], bool]) -> list[str]:
        """Mark RUNNING records with dead PIDs as INTERRUPTED. Returns affected ids."""
        with self._lock:
            records = _load(self._path)
            affected: list[str] = []
            for rec in sorted(records.values(), key=lambda r: r.seq):
                if rec.state is RunState.RUNNING:
                    if rec.pid is None or not is_alive(rec.pid):
                        rec.state = RunState.INTERRUPTED
                        rec.pid = None
                        affected.append(rec.run_id)
            _save(self._path, records)
            return affected

    def next_runnable(self, max_parallel: int) -> list[RunRecord]:
        """Return up to (max_parallel - running_count) runnable records.

        INTERRUPTED records come before QUEUED, each group ordered by seq.
        """
        with self._lock:
            records = _load(self._path)
            running_count = sum(
                1 for r in records.values() if r.state is RunState.RUNNING
            )
            slots = max(0, max_parallel - running_count)
            if slots == 0:
                return []
            interrupted = sorted(
                (r for r in records.values() if r.state is RunState.INTERRUPTED),
                key=lambda r: r.seq,
            )
            queued = sorted(
                (r for r in records.values() if r.state is RunState.QUEUED),
                key=lambda r: r.seq,
            )
            candidates = interrupted + queued
            return candidates[:slots]

    def get(self, run_id: str) -> RunRecord:
        """Return a record by id. Raises KeyError if absent."""
        with self._lock:
            records = _load(self._path)
            if run_id not in records:
                raise KeyError(run_id)
            return records[run_id]

    def all(self) -> list[RunRecord]:
        """Return all records in insertion (seq) order."""
        with self._lock:
            records = _load(self._path)
            return sorted(records.values(), key=lambda r: r.seq)

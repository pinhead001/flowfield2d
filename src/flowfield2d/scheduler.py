"""Background, resumable run scheduler over the run registry (REQUIREMENTS 4.3 persistence).

`tick` is idempotent and safe to call repeatedly (e.g. `run.bat run tick`):
1. runs marked RUNNING whose worker process is gone become INTERRUPTED (sandbox closed, crash);
2. up to `max_parallel` runs start (INTERRUPTED first, then QUEUED), each in a detached worker.
A worker runs one plan through the engine and records the outcome in the registry. Each worker
writes `<registry dir>/logs/<run_id>.log`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from collections.abc import Callable, Sequence
from pathlib import Path

import psutil

from flowfield2d.engines import Engine
from flowfield2d.runs import Registry, RunRecord, RunState

START_WAIT_S = 30.0


def pid_alive(pid: int) -> bool:
    try:
        return bool(psutil.Process(pid).status() != psutil.STATUS_ZOMBIE)
    except psutil.NoSuchProcess:
        return False


def tick(registry: Registry, max_parallel: int, launch: Callable[[RunRecord], int],
         is_alive: Callable[[int], bool] = pid_alive) -> list[str]:
    """Reconcile dead workers, then start runnable runs; returns the run ids started."""
    registry.reconcile(is_alive)
    started = []
    for rec in registry.next_runnable(max_parallel):
        pid = launch(rec)
        registry.start(rec.run_id, pid)
        started.append(rec.run_id)
    return started


def launch_worker(registry: Registry, rec: RunRecord, ras_cmd: Sequence[str],
                  core_count: int | None = None) -> int:
    """Start a detached worker process for one run; returns its pid."""
    logs = registry.path.parent / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, "-m", "flowfield2d.cli", "runs", "worker",
            "--registry", str(registry.path), "--run-id", rec.run_id]
    for c in ras_cmd:
        argv += ["--ras", str(c)]
    if core_count:
        argv += ["--core-count", str(core_count)]
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    with (logs / f"{rec.run_id}.log").open("ab") as log:
        proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, creationflags=flags)
    return proc.pid


def run_worker(registry: Registry, run_id: str, engine: Engine) -> None:
    """Run one registered plan and record DONE/FAILED with a JSON detail."""
    deadline = time.monotonic() + START_WAIT_S
    while registry.get(run_id).state is not RunState.RUNNING:   # tick records start after spawn
        if time.monotonic() > deadline:
            raise RuntimeError(f"run {run_id} never marked RUNNING")
        time.sleep(0.2)
    rec = registry.get(run_id)
    try:
        out = engine.run(Path(rec.plan))
        detail = {"result_path": str(out.result_path) if out.result_path else None,
                  "exit_code": out.exit_code, "engine_success": out.engine_success,
                  "duration_s": out.duration_s, "log_tail": out.log_tail[-800:]}
        registry.finish(run_id, out.ok, json.dumps(detail))
    except Exception:  # noqa: BLE001 - every failure must land in the registry
        registry.finish(run_id, False, json.dumps({"error": traceback.format_exc()[-1500:]}))

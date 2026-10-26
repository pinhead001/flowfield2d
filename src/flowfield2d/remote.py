"""Queue backend: registered runs solved by remote workers through a shared folder.

The host prepares each run as a standalone ready-to-run file (`ras plan prepare`), which carries
mesh, property tables, BCs and plan settings, so a worker needs only the pinned RAS build
(`tools/worker/worker.ps1`).

Queue layout, `<job>` = run id + registry tag (`job_name`): `pending/<job>.r2r.h5` plus a
`<job>.r2r.h5.ready` marker written last, holding the processor the run needs ("CPU" or "GPU";
workers take only matching jobs, an empty marker fits any worker, and GPU results differ from
CPU); workers claim a job by moving it to `running/<host>/<job>/` and finish in `done/<job>/`
(`result.h5`, `status.json`) or `failed/<job>/`. `jobs/<job>.json` keeps the host-side record
(run id, registry, plan, synthetic pid), so a restarted host can resume.

With the scheduler: `launch` and `is_alive` fit `scheduler.tick`; `collect(registry)` must run
before each tick to move finished results into the project's `Results/` folder and record
DONE/FAILED in the registry.
"""

from __future__ import annotations

import json
import os
import shutil
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from flowfield2d.engines.ras2025.cli import RasCli
from flowfield2d.runs import Registry, RunRecord, RunState

_PID_BASE = 2_000_000_000          # synthetic pids, above real Windows pids


class QueueBackend:
    def __init__(self, queue: Path, cli: RasCli, processor: str = "CPU",
                 prepare_hook: Callable[[RunRecord, Path], None] | None = None) -> None:
        if processor not in ("CPU", "GPU"):
            raise ValueError(f"processor must be 'CPU' or 'GPU', not {processor!r}")
        self.queue = Path(queue)
        self.cli = cli
        self.processor = processor
        self.prepare_hook = prepare_hook    # edits a job (e.g. initial state) before ready
        for d in ("pending", "running", "done", "failed", "jobs"):
            (self.queue / d).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def pid_for(run_id: str) -> int:
        return _PID_BASE + zlib.crc32(run_id.encode()) % 100_000_000

    @staticmethod
    def job_name(registry: Registry, run_id: str) -> str:
        """Queue name of a run: its id plus a tag of its registry, so the same run id from two run
        roots (e.g. study variants sharing a coarse run) never shares a job."""
        return f"{run_id}__{zlib.crc32(str(registry.path).encode()):08x}"

    def _job(self, name: str) -> Path:
        return self.queue / "jobs" / f"{name}.json"

    def launch(self, registry: Registry, rec: RunRecord) -> int:
        """Prepare the run's plan into `pending/` and record the job; returns a synthetic pid."""
        name = self.job_name(registry, rec.run_id)
        out = self.queue / "pending" / f"{name}.r2r.h5"
        res = self.cli.run(["plan", "prepare", rec.plan, str(out), "--if-exists", "force"],
                           check=False)
        if res.exit_code != 0 or not out.exists():
            out.unlink(missing_ok=True)
            raise RuntimeError(f"plan prepare failed for {rec.run_id}: {res.stderr[-400:]}")
        if self.prepare_hook is not None:
            self.prepare_hook(rec, out)
        pid = self.pid_for(name)
        self._job(name).write_text(json.dumps(
            {"run_id": rec.run_id, "registry": str(registry.path), "plan": rec.plan, "pid": pid}))
        ready = self.queue / "pending" / f"{out.name}.ready"
        ready.write_text(self.processor, encoding="utf-8")                # visible to workers last
        return pid

    def _job_for_pid(self, pid: int) -> str | None:
        for j in (self.queue / "jobs").glob("*.json"):
            data = json.loads(j.read_text(encoding="utf-8"))
            if int(data["pid"]) == pid:
                return j.stem
        return None

    def is_alive(self, pid: int) -> bool:
        """A queued job is alive until its result is collected (pending, running or finished but
        not yet collected all count)."""
        name = self._job_for_pid(pid)
        return name is not None and self._job(name).exists()

    def collect(self, registry: Registry) -> list[str]:
        """Record finished jobs of this registry; returns the run ids collected."""
        collected: list[str] = []
        for state in ("done", "failed"):
            for d in sorted((self.queue / state).iterdir()):
                job = self._job(d.name)
                if not job.exists():
                    continue
                data = json.loads(job.read_text(encoding="utf-8"))
                if Path(data["registry"]) != registry.path:
                    continue
                status: dict[str, Any] = {}
                if (d / "status.json").exists():
                    status = json.loads((d / "status.json").read_text(encoding="utf-8"))
                ok = state == "done" and (d / "result.h5").exists()
                detail: dict[str, Any] = {"host": status.get("host"), "queue_state": state}
                if ok:
                    plan = Path(data["plan"])
                    dest = plan.parent.parent / "Results" / f"{plan.stem} (Result).h5"
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(d / "result.h5"), dest)
                    detail["result_path"] = str(dest)
                else:
                    detail["error"] = status.get("error", f"worker reported {state}")
                if registry.get(data["run_id"]).state is RunState.RUNNING:
                    registry.finish(data["run_id"], ok, json.dumps(detail))
                os.remove(job)
                collected.append(str(data["run_id"]))
        return collected

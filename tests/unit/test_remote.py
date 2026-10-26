"""Queue backend: runs prepared as ready-to-run jobs in a shared folder, solved remotely."""

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from flowfield2d.engines.ras2025.cli import RasCli
from flowfield2d.remote import QueueBackend
from flowfield2d.runs import Registry, RunState
from flowfield2d.scheduler import tick

from .test_ras_engine import FAKE, _project


def _setup(tmp_path: Path) -> tuple[Registry, QueueBackend, Path]:
    proj = _project(tmp_path)
    reg = Registry(tmp_path / "runs" / "registry.json")
    reg.add("r1", "d1", "s1", str(proj / "Plans" / "p01.h5"))
    q = tmp_path / "queue"
    return reg, QueueBackend(q, RasCli([sys.executable, str(FAKE)], timeout_s=60)), q


def _fake_worker(q: Path, ok: bool = True) -> None:
    """What worker.ps1 does: claim each pending job, 'solve' it, move it to done/failed."""
    for job in (q / "pending").glob("*.r2r.h5"):
        name = job.name[: -len(".r2r.h5")]
        assert (q / "pending" / f"{job.name}.ready").exists()
        d = q / ("done" if ok else "failed") / name
        d.mkdir(parents=True)
        shutil.move(str(job), d / "job.r2r.h5")
        os.remove(q / "pending" / f"{job.name}.ready")
        if ok:
            (d / "result.h5").write_bytes(b"result")
        (d / "status.json").write_text(json.dumps({"ok": ok, "host": "LAPTOP1"}))


def test_launch_prepares_a_job_and_collect_finishes_the_run(tmp_path: Path) -> None:
    reg, backend, q = _setup(tmp_path)
    started = tick(reg, 2, lambda rec: backend.launch(reg, rec), backend.is_alive)
    assert started == ["r1"]
    assert (q / "pending" / "r1.r2r.h5").exists()
    assert (q / "pending" / "r1.r2r.h5.ready").read_text(encoding="utf-8") == "CPU"   # default
    assert backend.is_alive(reg.get("r1").pid) is True               # pending counts as alive
    backend.collect(reg)
    assert reg.get("r1").state is RunState.RUNNING                    # nothing finished yet
    _fake_worker(q)
    backend.collect(reg)
    rec = reg.get("r1")
    assert rec.state is RunState.DONE
    detail = json.loads(rec.detail)
    assert Path(detail["result_path"]).read_bytes() == b"result"
    assert detail["host"] == "LAPTOP1"
    assert Path(detail["result_path"]).parent.name == "Results"     # back in the project
    tick(reg, 2, lambda rec: backend.launch(reg, rec), backend.is_alive)
    assert reg.get("r1").state is RunState.DONE                       # not relaunched


def test_failed_job_and_restart_safety(tmp_path: Path) -> None:
    reg, backend, q = _setup(tmp_path)
    tick(reg, 2, lambda rec: backend.launch(reg, rec), backend.is_alive)
    fresh = QueueBackend(q, RasCli([sys.executable, str(FAKE)], timeout_s=60))   # host restarted
    assert fresh.is_alive(reg.get("r1").pid) is True                 # mapping kept in the queue
    _fake_worker(q, ok=False)
    fresh.collect(reg)
    rec = reg.get("r1")
    assert rec.state is RunState.FAILED and "LAPTOP1" in rec.detail


def test_prepare_failure_is_raised(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reg, backend, q = _setup(tmp_path)
    monkeypatch.setenv("FAKE_RAS_FAIL_PREPARE", "1")
    with pytest.raises(RuntimeError, match="prepare"):
        backend.launch(reg, reg.get("r1"))
    assert not list((q / "pending").glob("*.ready"))


def test_ready_marker_names_the_processor(tmp_path: Path) -> None:
    proj = _project(tmp_path)
    reg = Registry(tmp_path / "runs" / "registry.json")
    reg.add("r1", "d1", "s1", str(proj / "Plans" / "p01.h5"))
    q = tmp_path / "queue"
    gpu = QueueBackend(q, RasCli([sys.executable, str(FAKE)], timeout_s=60), processor="GPU")
    tick(reg, 2, lambda rec: gpu.launch(reg, rec), gpu.is_alive)
    assert (q / "pending" / "r1.r2r.h5.ready").read_text(encoding="utf-8") == "GPU"
    with pytest.raises(ValueError, match="processor"):
        QueueBackend(q, RasCli([sys.executable, str(FAKE)], timeout_s=60), processor="TPU")


def test_prepare_hook_edits_the_job_before_it_is_ready(tmp_path: Path) -> None:
    proj = _project(tmp_path)
    reg = Registry(tmp_path / "runs" / "registry.json")
    reg.add("r1", "d1", "s1", str(proj / "Plans" / "p01.h5"))
    q = tmp_path / "queue"
    seen: list[tuple[str, bool]] = []

    def hook(run_id: str, r2r: Path) -> None:
        seen.append((run_id, (q / "pending" / f"{r2r.name}.ready").exists()))
        r2r.write_bytes(r2r.read_bytes() + b" warm")

    b = QueueBackend(q, RasCli([sys.executable, str(FAKE)], timeout_s=60), prepare_hook=hook)
    tick(reg, 2, lambda rec: b.launch(reg, rec), b.is_alive)
    assert seen == [("r1", False)]                      # called before the ready marker exists
    assert (q / "pending" / "r1.r2r.h5").read_bytes().endswith(b" warm")
    assert (q / "pending" / "r1.r2r.h5.ready").exists()

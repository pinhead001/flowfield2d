"""Queue backend: runs prepared as ready-to-run jobs in a shared folder, solved remotely."""

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from flowfield2d.engines.ras2025.cli import RasCli
from flowfield2d.remote import QueueBackend
from flowfield2d.runs import Registry, RunRecord, RunState
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
    job = backend.job_name(reg, "r1")
    assert (q / "pending" / f"{job}.r2r.h5").exists()
    assert (q / "pending" / f"{job}.r2r.h5.ready").read_text(encoding="utf-8") == "CPU"  # default
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


def test_collect_leaves_jobs_of_an_earlier_registry_at_the_same_path(tmp_path: Path) -> None:
    reg, backend, q = _setup(tmp_path)
    tick(reg, 2, lambda rec: backend.launch(reg, rec), backend.is_alive)
    _fake_worker(q)
    reg.path.unlink()                                  # run root archived and rebuilt in place
    fresh = Registry(reg.path)
    assert backend.collect(fresh) == []                # unknown run id: not ours, no KeyError
    job = backend.job_name(reg, "r1")
    assert (q / "done" / job / "result.h5").exists()   # result not moved into the new root
    assert (q / "jobs" / f"{job}.json").exists()


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
    job = gpu.job_name(reg, "r1")
    assert (q / "pending" / f"{job}.r2r.h5.ready").read_text(encoding="utf-8") == "GPU"
    with pytest.raises(ValueError, match="processor"):
        QueueBackend(q, RasCli([sys.executable, str(FAKE)], timeout_s=60), processor="TPU")


def test_prepare_hook_edits_the_job_before_it_is_ready(tmp_path: Path) -> None:
    proj = _project(tmp_path)
    reg = Registry(tmp_path / "runs" / "registry.json")
    reg.add("r1", "d1", "s1", str(proj / "Plans" / "p01.h5"))
    q = tmp_path / "queue"
    seen: list[tuple[str, bool]] = []

    def hook(rec: RunRecord, r2r: Path) -> None:
        seen.append((rec.run_id, (q / "pending" / f"{r2r.name}.ready").exists()))
        assert rec.plan.endswith("p01.h5")
        r2r.write_bytes(r2r.read_bytes() + b" warm")

    b = QueueBackend(q, RasCli([sys.executable, str(FAKE)], timeout_s=60), prepare_hook=hook)
    tick(reg, 2, lambda rec: b.launch(reg, rec), b.is_alive)
    assert seen == [("r1", False)]                      # called before the ready marker exists
    job = b.job_name(reg, "r1")
    assert (q / "pending" / f"{job}.r2r.h5").read_bytes().endswith(b" warm")
    assert (q / "pending" / f"{job}.r2r.h5.ready").exists()


def test_same_run_id_from_two_registries_gets_two_jobs(tmp_path: Path) -> None:
    proj_a, proj_b = _project(tmp_path / "a"), _project(tmp_path / "b")
    reg_a = Registry(tmp_path / "a" / "runs" / "registry.json")
    reg_b = Registry(tmp_path / "b" / "runs" / "registry.json")
    reg_a.add("r1", "d1", "s1", str(proj_a / "Plans" / "p01.h5"))
    reg_b.add("r1", "d1", "s1", str(proj_b / "Plans" / "p01.h5"))
    q = tmp_path / "queue"
    b = QueueBackend(q, RasCli([sys.executable, str(FAKE)], timeout_s=60))
    tick(reg_a, 2, lambda rec: b.launch(reg_a, rec), b.is_alive)
    tick(reg_b, 2, lambda rec: b.launch(reg_b, rec), b.is_alive)
    jobs = sorted(p.name for p in (q / "pending").glob("*.r2r.h5"))
    assert len(jobs) == 2 and all(j.startswith("r1") for j in jobs)
    assert reg_a.get("r1").pid != reg_b.get("r1").pid
    _fake_worker(q)
    assert b.collect(reg_a) == ["r1"] and b.collect(reg_b) == ["r1"]
    assert reg_a.get("r1").state is RunState.DONE and reg_b.get("r1").state is RunState.DONE

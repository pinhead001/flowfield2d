"""Background scheduler over the run registry (fake engine / fake RAS; no real RAS)."""

import json
import os
import sys
import time
from pathlib import Path

import pytest

from flowfield2d.engines.ras2025.cli import RasCli
from flowfield2d.engines.ras2025.engine import RasEngine
from flowfield2d.engines.ras2025.templates import clone_project
from flowfield2d.runs import Registry, RunState
from flowfield2d.scheduler import launch_worker, run_worker, tick

from .test_ras_engine import FAKE, _project


def _registry(tmp_path: Path, n: int = 3) -> Registry:
    r = Registry(tmp_path / "runs" / "registry.json")
    for i in range(n):
        r.add(f"r{i}", "d1", f"s{i}", f"plan{i}.h5")
    return r


def test_tick_respects_cap_and_resumes_interrupted_first(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    launched: list[str] = []

    def launch(rec):  # type: ignore[no-untyped-def]
        launched.append(rec.run_id)
        return 1000 + len(launched)

    assert tick(reg, max_parallel=2, launch=launch, is_alive=lambda pid: True) == ["r0", "r1"]
    assert [x.state for x in reg.all()] == [RunState.RUNNING, RunState.RUNNING, RunState.QUEUED]
    assert tick(reg, max_parallel=2, launch=launch, is_alive=lambda pid: True) == []
    # r0's worker died (sandbox closed): it becomes interrupted and is relaunched before r2
    started = tick(reg, max_parallel=2, launch=launch, is_alive=lambda pid: pid != 1001)
    assert started == ["r0"] and reg.get("r0").attempts == 2


def test_run_worker_records_engine_outcome(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FAKE_RAS_FAIL", raising=False)
    monkeypatch.delenv("FAKE_RAS_SUCCESS", raising=False)
    run = clone_project(_project(tmp_path), tmp_path / "run1")
    reg = Registry(tmp_path / "registry.json")
    reg.add("ok1", "d1", "s1", str(run / "Plans" / "p01.h5"))
    reg.start("ok1", os.getpid())
    run_worker(reg, "ok1", RasEngine(RasCli([sys.executable, str(FAKE)], timeout_s=60)))
    rec = reg.get("ok1")
    assert rec.state is RunState.DONE
    detail = json.loads(rec.detail)
    assert detail["engine_success"] is True and detail["result_path"].endswith("(Result).h5")

    monkeypatch.setenv("FAKE_RAS_SUCCESS", "0")
    reg.add("bad1", "d1", "s2", str(run / "Plans" / "p01.h5"))
    reg.start("bad1", os.getpid())
    run_worker(reg, "bad1", RasEngine(RasCli([sys.executable, str(FAKE)], timeout_s=60)))
    assert reg.get("bad1").state is RunState.FAILED


def test_detached_worker_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FAKE_RAS_FAIL", raising=False)
    monkeypatch.delenv("FAKE_RAS_SUCCESS", raising=False)
    run = clone_project(_project(tmp_path), tmp_path / "run1")
    reg = Registry(tmp_path / "registry.json")
    reg.add("e2e", "d1", "s1", str(run / "Plans" / "p01.h5"))
    ras_cmd = [sys.executable, str(FAKE)]
    started = tick(reg, max_parallel=1, launch=lambda rec: launch_worker(reg, rec, ras_cmd))
    assert started == ["e2e"]
    deadline = time.monotonic() + 90
    while reg.get("e2e").state is RunState.RUNNING and time.monotonic() < deadline:
        time.sleep(0.5)
    assert reg.get("e2e").state is RunState.DONE, (reg.path.parent / "logs" / "e2e.log").read_text()

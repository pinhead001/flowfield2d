import json
from pathlib import Path

import pytest

from flowfield2d.runs import BadTransition, DuplicateRun, Registry, RunState


def _reg(tmp_path: Path) -> Registry:
    r = Registry(tmp_path / "runs.json")
    for i, (d, s) in enumerate([("d1", "q1"), ("d1", "q2"), ("d2", "q1")]):
        r.add(f"r{i}", d, s, f"plan{i}")
    return r


def test_add_and_persist(tmp_path: Path) -> None:
    r = _reg(tmp_path)
    with pytest.raises(DuplicateRun):
        r.add("r0", "d", "s", "p")
    again = Registry(tmp_path / "runs.json")
    assert [x.run_id for x in again.all()] == ["r0", "r1", "r2"]
    assert again.get("r1").state is RunState.QUEUED
    assert json.loads((tmp_path / "runs.json").read_text())  # plain JSON on disk


def test_lifecycle_and_bad_transitions(tmp_path: Path) -> None:
    r = _reg(tmp_path)
    rec = r.start("r0", pid=111)
    assert rec.state is RunState.RUNNING and rec.pid == 111 and rec.attempts == 1 and rec.started
    with pytest.raises(BadTransition):
        r.start("r0", pid=112)
    with pytest.raises(BadTransition):
        r.finish("r1", ok=True)
    done = r.finish("r0", ok=False, detail="diverged")
    assert done.state is RunState.FAILED and done.pid is None and done.detail == "diverged"
    assert r.requeue("r0").state is RunState.QUEUED
    with pytest.raises(KeyError):
        r.get("nope")


def test_reconcile_marks_dead_runs_interrupted_and_resumes_first(tmp_path: Path) -> None:
    r = _reg(tmp_path)
    r.start("r1", pid=10)
    r.start("r2", pid=20)
    assert r.reconcile(lambda pid: pid == 20) == ["r1"]
    assert r.get("r1").state is RunState.INTERRUPTED and r.get("r1").pid is None
    assert r.get("r2").state is RunState.RUNNING
    nxt = r.next_runnable(max_parallel=3)
    assert [x.run_id for x in nxt] == ["r1", "r0"]
    assert r.next_runnable(max_parallel=1) == []
    resumed = r.start("r1", pid=30)
    assert resumed.attempts == 2


def test_parallel_cap_never_negative(tmp_path: Path) -> None:
    r = _reg(tmp_path)
    r.start("r0", pid=1)
    r.start("r1", pid=2)
    assert r.next_runnable(max_parallel=1) == []
    assert [x.run_id for x in r.next_runnable(max_parallel=4)] == ["r2"]

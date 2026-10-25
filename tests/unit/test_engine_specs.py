"""Engine-neutral specs and a worker run through any `Engine`, not only RAS."""

import dataclasses
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from shapely.geometry import LineString, box

from flowfield2d.engines import BcSpec, Capabilities, ModelSpec, PlanSpec, RunOutcome
from flowfield2d.runs import Registry, RunState
from flowfield2d.scheduler import run_worker


def test_specs_are_frozen_with_fields(tmp_path: Path) -> None:
    m = ModelSpec(template=tmp_path / "t", dest=tmp_path / "d", keep=box(0, 0, 1, 1),
                  cuts={"Outflow": LineString([(0, 0), (1, 0)])}, cell_size=9.0)
    b = BcSpec(start=datetime(2000, 1, 1), offsets_s=[0.0, 3600.0],
               flows={"Inflow": [10.0, 20.0]}, slopes={"Outflow": 0.002})
    p = PlanSpec(compute_timestep="3s", output_interval="15min", time_stepping="Explicit")
    full = ModelSpec(template=m.template, dest=m.dest, keep=None, cuts={}, cell_size=9.0)
    assert full.keep is None
    for spec, field in ((m, "cell_size"), (b, "slopes"), (p, "compute_timestep")):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(spec, field, None)
    names = [f.name for f in dataclasses.fields(BcSpec)]
    assert names == ["start", "offsets_s", "flows", "slopes"]


class _NeutralEngine:
    capabilities = Capabilities("fake", "0", "A", True, True, True, True, True, True, True,
                                False, True, True)

    def __init__(self, result: Path) -> None:
        self.result = result

    def build_or_verify_model(self, domain: Any) -> Any: ...
    def write_bcs(self, model: Any, hydrograph: Any) -> Any: ...
    def create_plan(self, model: Any, spec: Any) -> Any: ...

    def run(self, plan: Any) -> RunOutcome:
        return RunOutcome(True, 0, True, self.result, 1.0)

    def results(self, run: Any) -> Any: ...
    def export(self, run: Any, plateau: Any, fields: Any, out_dir: Path) -> Any: ...


def test_run_worker_accepts_any_engine(tmp_path: Path) -> None:
    reg = Registry(tmp_path / "registry.json")
    reg.add("n1", "d1", "s1", str(tmp_path / "plan.json"))
    reg.start("n1", os.getpid())
    run_worker(reg, "n1", _NeutralEngine(tmp_path / "result.npz"))
    rec = reg.get("n1")
    assert rec.state is RunState.DONE
    assert json.loads(rec.detail)["result_path"].endswith("result.npz")

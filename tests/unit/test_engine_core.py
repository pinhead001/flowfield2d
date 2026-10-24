"""Neutral engine layer; RAS 2025 capability flags, BC validation, results reader (synthetic)."""

from pathlib import Path

import h5py
import numpy as np
import pytest

from flowfield2d.engines import Capabilities, Engine
from flowfield2d.engines.ras2025 import CAPABILITIES
from flowfield2d.engines.ras2025.results import ResultsReader
from flowfield2d.engines.ras2025.validate import BcProblem, validate_bc

from .test_ras_bc import _bc


def test_ras2025_capabilities_reflect_probe() -> None:
    c = CAPABILITIES
    assert isinstance(c, Capabilities)
    assert c.tier == "B"
    assert c.headless_compute and c.headless_terrain and c.headless_mesh_regen
    assert c.bc_by_template_edit and not c.geometry_authoring_headless
    assert not c.gpu and not c.validates_bc_values and not c.exit_code_reliable


def test_engine_protocol_is_runtime_checkable() -> None:
    class Dummy:
        capabilities = CAPABILITIES

        def build_or_verify_model(self, domain): ...  # type: ignore[no-untyped-def]
        def write_bcs(self, model, hydrograph): ...  # type: ignore[no-untyped-def]
        def create_plan(self, model, spec): ...  # type: ignore[no-untyped-def]
        def run(self, plan): ...  # type: ignore[no-untyped-def]
        def results(self, run): ...  # type: ignore[no-untyped-def]
        def export(self, run, plateau, fields, out_dir): ...  # type: ignore[no-untyped-def]

    assert isinstance(Dummy(), Engine)
    assert not isinstance(object(), Engine)


def test_validate_bc(tmp_path: Path) -> None:
    p = _bc(tmp_path)
    assert validate_bc(p) == []
    with h5py.File(p, "r+") as f:
        g = f["/Boundary Conditions/BC Lines/Payloads"]
        arr = g["Payloads"][:]
        arr[0]["Constant"] = 0.0
        del g["Payloads"]
        g.create_dataset("Payloads", data=arr)
        v = g["Values"][:]
        v[2] = -1.0
        del g["Values"]
        g.create_dataset("Values", data=v)
        t = g["Times"][:]
        t[3] = t[1]
        del g["Times"]
        g.create_dataset("Times", data=t)
    probs = validate_bc(p)
    kinds = sorted(pr.kind for pr in probs)
    assert kinds == ["flow_negative", "slope_not_positive", "times_not_increasing"]
    assert all(isinstance(pr, BcProblem) and pr.message for pr in probs)


def _result(tmp_path: Path, success: int = 1) -> Path:
    p = tmp_path / "r.h5"
    b = "/Results/Output Blocks/Base Output"
    with h5py.File(p, "w") as f:
        f.create_dataset(b + "/Time", data=np.array([0.0, 0.5, 1.0]))
        f.create_dataset(b + "/2D Flow Areas/Mesh/Cell Depth",
                         data=np.array([[0, 0, 0], [1, 2, 0], [2, 3, 0.5]], dtype="f4"))
        f.create_dataset(b + "/2D Flow Areas/Mesh/Face Velocity",
                         data=np.ones((3, 4), dtype="f4"))
        f.create_dataset("/Geometry/2D Flow Areas/Mesh/Property Tables/Cell Minimum Elevation",
                         data=np.array([100.0, 101.0, 102.0], dtype="f4"))
        f.create_dataset("/Geometry/2D Flow Areas/Mesh/Cell Coordinates",
                         data=np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]]))
        cs = f.create_group("/Results/Compute Summary")
        cs.attrs["Success"] = np.uint8(success)
        cs.attrs["Solver"] = np.bytes_("CPU_Explicit")
        cs.attrs["Compute Log"] = np.bytes_("ok")
    return p


def test_results_reader(tmp_path: Path) -> None:
    r = ResultsReader(_result(tmp_path))
    assert r.areas() == ["Mesh"]
    assert r.time_days().tolist() == [0.0, 0.5, 1.0]
    assert r.cell_depth("Mesh", -1).tolist() == [2.0, 3.0, 0.5]
    wse = r.cell_wse("Mesh", -1, min_depth=0.0)
    assert wse[:2].tolist() == [102.0, 104.0] and wse[2] == pytest.approx(102.5)
    dry = r.cell_wse("Mesh", 0)
    assert np.isnan(dry).all()                         # dry cells have no WSE
    assert r.face_velocity("Mesh", 1).shape == (4,)
    s = r.compute_summary()
    assert s.success and s.solver == "CPU_Explicit" and s.log == "ok"
    failed = tmp_path / "failed"
    failed.mkdir()
    assert not ResultsReader(_result(failed, success=0)).compute_summary().success

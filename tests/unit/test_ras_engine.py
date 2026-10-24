"""Template cloning and the Tier B run step, with the fake RAS CLI (synthetic project tree)."""

import shutil
import sys
from pathlib import Path

import h5py
import numpy as np
import pytest

from flowfield2d.engines import Engine
from flowfield2d.engines.ras2025.cli import RasCli
from flowfield2d.engines.ras2025.engine import RasEngine
from flowfield2d.engines.ras2025.h5schema import SchemaMismatch
from flowfield2d.engines.ras2025.templates import clone_project, fingerprints, verify_template

from .test_ras_bc import _bc

FAKE = Path(__file__).resolve().parents[1] / "fixtures" / "fake_ras.py"


def _project(root: Path) -> Path:
    p = root / "Proj"
    for d in ("Plans", "Geometries", "Boundary Conditions", "Results", "Plans/p01 Backups"):
        (p / d).mkdir(parents=True)
    (p / "Proj.ras").write_text("project")
    shutil.move(str(_bc(root)), p / "Boundary Conditions" / "bc01.h5")
    with h5py.File(p / "Plans" / "p01.h5", "w") as f:
        f.create_group("Plan Data").attrs["Compute Core Count"] = np.int32(4)
    with h5py.File(p / "Geometries" / "g01.h5", "w") as f:
        f.create_dataset("Geometry/x", data=np.zeros(3))
    (p / "Results" / "old.h5").write_bytes(b"stale")
    (p / "Plans" / "p01 Backups" / "b.h5").write_bytes(b"backup")
    return p


def test_clone_skips_results_and_backups(tmp_path: Path) -> None:
    src = _project(tmp_path)
    dst = clone_project(src, tmp_path / "run1")
    assert (dst / "Proj.ras").exists() and (dst / "Plans" / "p01.h5").exists()
    assert not (dst / "Results" / "old.h5").exists() and (dst / "Results").is_dir()
    assert not (dst / "Plans" / "p01 Backups").exists()
    with pytest.raises(FileExistsError):
        clone_project(src, dst)
    with pytest.raises(FileNotFoundError):
        clone_project(tmp_path / "Proj" / "Plans", tmp_path / "run2")   # no .ras project file


def test_verify_template_against_baseline(tmp_path: Path) -> None:
    src = _project(tmp_path)
    base = fingerprints(src)
    assert set(base) == {"Boundary Conditions/bc01.h5", "Geometries/g01.h5", "Plans/p01.h5"}
    run = clone_project(src, tmp_path / "run1")
    verify_template(run, base)
    with h5py.File(run / "Geometries" / "g01.h5", "a") as f:
        f.create_dataset("Geometry/new", data=np.zeros(1))
    with pytest.raises(SchemaMismatch, match="g01"):
        verify_template(run, base)


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> RasEngine:
    monkeypatch.delenv("FAKE_RAS_FAIL", raising=False)
    monkeypatch.delenv("FAKE_RAS_LOG", raising=False)
    monkeypatch.delenv("FAKE_RAS_SUCCESS", raising=False)
    return RasEngine(RasCli([sys.executable, str(FAKE)], timeout_s=60))


def test_engine_conforms_and_runs(tmp_path: Path, engine: RasEngine) -> None:
    assert isinstance(engine, Engine) and engine.capabilities.tier == "B"
    run = clone_project(_project(tmp_path), tmp_path / "run1")
    out = engine.run(run / "Plans" / "p01.h5")
    assert out.ok and out.exit_code == 0 and out.engine_success is True
    assert out.result_path == run / "Results" / "p01 (Result).h5"


def test_engine_success_flag_overrides_exit_code(tmp_path: Path, engine: RasEngine,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_RAS_SUCCESS", "0")
    run = clone_project(_project(tmp_path), tmp_path / "run1")
    out = engine.run(run / "Plans" / "p01.h5")
    assert out.exit_code == 0 and out.engine_success is False and not out.ok


def test_invalid_bc_blocks_compute(tmp_path: Path, engine: RasEngine) -> None:
    from flowfield2d.engines.ras2025.bc import set_normal_depth_slope

    run = clone_project(_project(tmp_path), tmp_path / "run1")
    set_normal_depth_slope(run / "Boundary Conditions" / "bc01.h5", 0.0, allow_invalid=True)
    out = engine.run(run / "Plans" / "p01.h5")
    assert not out.ok and out.exit_code is None and "slope" in out.log_tail
    assert not (run / "Results" / "p01 (Result).h5").exists()


def test_nonzero_exit_is_a_failed_run(tmp_path: Path, engine: RasEngine,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_RAS_FAIL", "1")
    run = clone_project(_project(tmp_path), tmp_path / "run1")
    out = engine.run(run / "Plans" / "p01.h5")
    assert not out.ok and out.exit_code == 3 and "boundary condition" in out.log_tail

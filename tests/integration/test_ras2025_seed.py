"""End to end on the pinned RAS build (marker `ras`; deselected by default).

Needs FLOWFIELD2D_RAS_EXE (ras.exe) and FLOWFIELD2D_RAS_SEED (a computed RAS 2025 project folder
with one plan and one BC layer with a valid normal-depth BC). The seed is cloned to a temp dir.
"""

import os
from pathlib import Path

import numpy as np
import pytest

from flowfield2d.engines.ras2025.bc import scale_flow_series, set_normal_depth_slope
from flowfield2d.engines.ras2025.cli import RasCli
from flowfield2d.engines.ras2025.engine import RasEngine
from flowfield2d.engines.ras2025.templates import clone_project, fingerprints, verify_template

pytestmark = pytest.mark.ras

EXE = os.environ.get("FLOWFIELD2D_RAS_EXE", "")
SEED = os.environ.get("FLOWFIELD2D_RAS_SEED", "")
if not (EXE and SEED and Path(EXE).is_file() and Path(SEED).is_dir()):
    pytest.skip("FLOWFIELD2D_RAS_EXE / FLOWFIELD2D_RAS_SEED not set", allow_module_level=True)


def _plan_and_bc(run: Path) -> tuple[Path, Path]:
    plans = sorted((run / "Plans").glob("*.h5"))
    bcs = sorted((run / "Boundary Conditions").glob("*.h5"))
    assert len(plans) == 1 and len(bcs) == 1, "seed must have one plan and one BC layer"
    return plans[0], bcs[0]


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    run = clone_project(Path(SEED), tmp_path / "run")
    verify_template(run, fingerprints(Path(SEED)))
    return run


def test_solve_reads_success_and_depths(run_dir: Path) -> None:
    plan, _ = _plan_and_bc(run_dir)
    eng = RasEngine(RasCli(Path(EXE), timeout_s=1800))
    out = eng.run(plan)
    assert out.ok, out.log_tail
    r = eng.results(out)
    area = r.areas()[0]
    depth = r.cell_depth(area, -1)
    assert np.isfinite(depth).all() and (depth > 0).any()
    assert r.time_days()[-1] > 0


def test_template_bc_edit_changes_results(run_dir: Path, tmp_path: Path) -> None:
    eng = RasEngine(RasCli(Path(EXE), timeout_s=1800))
    base = eng.run(_plan_and_bc(run_dir)[0])
    assert base.ok, base.log_tail
    run2 = clone_project(Path(SEED), tmp_path / "run2")
    plan2, bc2 = _plan_and_bc(run2)
    scale_flow_series(bc2, 1.5)
    more = eng.run(plan2)
    assert more.ok, more.log_tail
    a = eng.results(base).areas()[0]
    d0 = eng.results(base).cell_depth(a, -1)
    d1 = eng.results(more).cell_depth(a, -1)
    assert np.nanmax(d1) > np.nanmax(d0)            # 1.5x flow -> deeper somewhere


def test_invalid_slope_is_blocked_before_ras(run_dir: Path) -> None:
    plan, bc = _plan_and_bc(run_dir)
    set_normal_depth_slope(bc, 0.0, allow_invalid=True)
    out = RasEngine(RasCli(Path(EXE), timeout_s=600)).run(plan)
    assert not out.ok and out.exit_code is None and "slope" in out.log_tail

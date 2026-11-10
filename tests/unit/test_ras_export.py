"""RAS results -> engine-neutral flow state for exports."""

import math
from pathlib import Path

import h5py
import numpy as np
import pytest

from flowfield2d.engines.ras2025.export import flow_state
from flowfield2d.engines.ras2025.results import ResultsReader

from .test_results_series import _result

FT = 0.3048


def _reader(tmp_path: Path) -> ResultsReader:
    p = _result(tmp_path)
    with h5py.File(p, "a") as f:        # RAS always writes face velocity; the fixture omits it
        f.create_dataset("/Results/Output Blocks/Base Output/2D Flow Areas/Mesh/Face Velocity",
                         data=np.full((3, 8), 0.5, dtype="f4"))
    return ResultsReader(p)


def test_flow_state_in_si(tmp_path: Path) -> None:
    r = _reader(tmp_path)
    s = flow_state(r, "Mesh", 1, FT, inflow_lines=["Inflow"], tol=0.01)
    assert math.isclose(s.discharge, 5.0 * FT**3)            # inflow is -5 through the left face
    assert s.cell_xy[:2].tolist() == [[0.5, 0.5], [1.5, 0.5]]  # coordinates stay in CRS units
    assert np.allclose(s.wse[:2], np.array([101.0, 103.0]) * FT)
    assert s.depth is not None and np.allclose(s.depth[:2], np.array([1.0, 2.0]) * FT)
    assert s.speed is not None and np.allclose(s.speed[:2], 0.5 * FT)
    assert np.isnan(s.wse[2])                                 # dry cell


def test_flow_state_last_output_and_given_discharge(tmp_path: Path) -> None:
    r = _reader(tmp_path)
    s = flow_state(r, "Mesh", -1, 1.0, discharge=12.5)
    assert s.discharge == 12.5 and np.allclose(s.wse[:2], [102.0, 104.0])
    both = flow_state(r, "Mesh", -1, 1.0, inflow_lines=["Inflow", "Outflow"], tol=0.01)
    assert math.isclose(both.discharge, 5.0 + 4.0)


def test_flow_state_refuses_bad_requests(tmp_path: Path) -> None:
    r = _reader(tmp_path)
    with pytest.raises(ValueError):
        flow_state(r, "Mesh", 0, 1.0)
    with pytest.raises(IndexError):
        flow_state(r, "Mesh", 7, 1.0, discharge=1.0)
    with pytest.raises(KeyError):
        flow_state(r, "Mesh", 0, 1.0, inflow_lines=["Nope"], tol=0.01)

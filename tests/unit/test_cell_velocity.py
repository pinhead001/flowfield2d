"""Cell velocity vectors reconstructed from RAS 2025 face-normal velocities."""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest

from flowfield2d.engines.ras2025.results import ResultsReader, cell_velocity_vectors
from flowfield2d.results import cell_table_from_results

# Two unit squares side by side: cell 0 = [0,1]x[0,1], cell 1 = [1,2]x[0,1].
NODES = np.array([[0, 0], [1, 0], [2, 0], [0, 1], [1, 1], [2, 1]], dtype=np.float64)
# (cell_a, cell_b, node_i, node_j); the normal is the tangent i->j turned clockwise and a
# positive velocity flows from cell_a to cell_b along it.
FACES = np.array([
    [0, -1, 0, 1],    # cell 0 bottom, normal (0, -1)
    [0, 1, 1, 4],     # shared face, normal (1, 0): cell 0 -> cell 1
    [0, -1, 4, 3],    # cell 0 top, normal (0, 1)
    [0, -1, 3, 0],    # cell 0 left, normal (-1, 0)
    [1, -1, 1, 2],    # cell 1 bottom, normal (0, -1)
    [1, -1, 2, 5],    # cell 1 right, normal (1, 0)
    [1, -1, 5, 4],    # cell 1 top, normal (0, 1)
], dtype=np.int64)
NORMALS = np.array([[0, -1], [1, 0], [0, 1], [-1, 0], [0, -1], [1, 0], [0, 1]], dtype=np.float64)


def _face_velocity(u: np.ndarray) -> np.ndarray:
    return NORMALS @ np.asarray(u, dtype=np.float64)


def test_uniform_flow_is_recovered_in_both_cells() -> None:
    u = np.array([0.6, -0.8])
    uv = cell_velocity_vectors(FACES, NODES, _face_velocity(u), 2)
    assert uv.shape == (2, 2)
    np.testing.assert_allclose(uv, [u, u], atol=1e-12)


def test_dry_cells_and_cells_without_two_independent_normals_are_nan() -> None:
    u = np.array([1.0, 2.0])
    depth = np.array([0.5, 0.0])
    uv = cell_velocity_vectors(FACES, NODES, _face_velocity(u), 2, depth=depth, min_depth=0.01)
    np.testing.assert_allclose(uv[0], u, atol=1e-12)
    assert np.isnan(uv[1]).all()
    # a cell whose faces all share one normal direction cannot resolve the tangential part
    one_dir = FACES[[0, 2]]                         # cell 0 with only its top and bottom faces
    uv = cell_velocity_vectors(one_dir, NODES, _face_velocity(u)[[0, 2]], 1)
    assert np.isnan(uv[0]).all()


def test_face_length_weights_the_fit() -> None:
    # a tall cell: the long shared face carries more weight than the short ends, but an exact
    # field is still recovered exactly whatever the weights
    nodes = NODES * np.array([1.0, 5.0])
    u = np.array([-0.3, 0.4])
    normals = NORMALS
    uv = cell_velocity_vectors(FACES, nodes, normals @ u, 2)
    np.testing.assert_allclose(uv, [u, u], atol=1e-12)


def _result(tmp_path: Path) -> Path:
    p = tmp_path / "r.h5"
    b = "/Results/Output Blocks/Base Output"
    g = "/Geometry/2D Flow Areas/Mesh"
    u = np.array([2.0, 1.0])
    with h5py.File(p, "w") as f:
        f.create_dataset(b + "/Time", data=np.array([0.0, 0.25]))
        f.create_dataset(b + "/2D Flow Areas/Mesh/Cell Depth",
                         data=np.array([[0, 0], [1.0, 0.0]], dtype="f4"))
        f.create_dataset(b + "/2D Flow Areas/Mesh/Face Velocity",
                         data=np.vstack([np.zeros(7), _face_velocity(u)]).astype("f4"))
        f.create_dataset(g + "/Property Tables/Cell Minimum Elevation",
                         data=np.array([100.0, 101.0], dtype="f4"))
        f.create_dataset(g + "/Cell Coordinates", data=np.array([[0.5, 0.5], [1.5, 0.5]]))
        f.create_dataset(g + "/Face Data", data=FACES.astype("i4"))
        f.create_dataset(g + "/Node Coordinates", data=NODES)
        cs = f.create_group("/Results/Compute Summary")
        cs.attrs["Success"] = np.uint8(1)
        cs.attrs["Solver"] = np.bytes_("CPU_Explicit")
        cs.attrs["Compute Log"] = np.bytes_("ok")
    return p


def test_reader_cell_velocity_and_table_columns(tmp_path: Path) -> None:
    r = ResultsReader(_result(tmp_path))
    uv = r.cell_velocity("Mesh", 1, min_depth=0.01)
    np.testing.assert_allclose(uv[0], [2.0, 1.0], atol=1e-6)
    assert np.isnan(uv[1]).all()                    # dry cell
    t = cell_table_from_results(r, "Mesh", 1, unit_m=0.3048, min_depth=0.01)
    assert t["vx_mps"][0] == pytest.approx(2.0 * 0.3048)
    assert t["vy_mps"][0] == pytest.approx(1.0 * 0.3048)
    assert t["direction_deg"][0] == pytest.approx(90.0 - np.degrees(np.arctan2(1.0, 2.0)))
    assert np.isnan(t["vx_mps"][1]) and np.isnan(t["direction_deg"][1])

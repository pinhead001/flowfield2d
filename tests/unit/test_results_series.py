"""Results readers for pipeline QA: WSE series at cells, cell coordinates, BC-line flow."""

from pathlib import Path

import h5py
import numpy as np
import pytest

from flowfield2d.engines import Results
from flowfield2d.engines.ras2025.results import ResultsReader

B = "/Results/Output Blocks/Base Output"
G = "/Geometry/2D Flow Areas/Mesh"

# Two cells side by side on [0, 2] x [0, 1]; face points (x, y):
FP = np.array([[0, 0], [1, 0], [2, 0], [2, 1], [1, 1], [0, 1], [2, 0.5]], dtype=float)
# Face Data columns [CellA, CellB, FpA, FpB]; CellB = -1 on the perimeter.
# The right side is two faces.
FACES = np.array([
    [0, 1, 1, 4],     # 0 interior
    [0, -1, 0, 1],    # 1 bottom, cell 0
    [1, -1, 1, 2],    # 2 bottom, cell 1
    [1, -1, 2, 6],    # 3 right, lower half
    [1, -1, 6, 3],    # 4 right, upper half
    [1, -1, 3, 4],    # 5 top, cell 1
    [0, -1, 4, 5],    # 6 top, cell 0
    [0, -1, 5, 0],    # 7 left
], dtype="i4")
# Face flow, positive from CellA to CellB (outward on the perimeter).
FLOW = np.array([np.zeros(8), [5, 0, 0, 1.5, 2.5, 0, 0, -5]], dtype="f4")


def _result(tmp_path: Path, outlet_x: float = 2.0) -> Path:
    p = tmp_path / "r.h5"
    with h5py.File(p, "w") as f:
        f.create_dataset(B + "/Time", data=np.array([0.0, 0.5, 1.0]))
        f.create_dataset(B + "/2D Flow Areas/Mesh/Cell Depth",
                         data=np.array([[0, 0, 0], [1, 2, 0], [2, 3, 0.5]], dtype="f4"))
        f.create_dataset(G + "/Property Tables/Cell Minimum Elevation",
                         data=np.array([100.0, 101.0, 102.0], dtype="f4"))
        f.create_dataset(G + "/Cell Coordinates",
                         data=np.array([[0.5, 0.5], [1.5, 0.5], [9.0, 9.0]]))
        f.create_dataset(G + "/Face Data", data=FACES)
        f.create_dataset(G + "/Node Coordinates", data=FP)
        f.create_dataset(B + "/2D Flow Areas/Mesh/DEBUG/FaceFlow",
                         data=np.vstack([FLOW, FLOW[1:]]))
        dt = [("Name", "S32"), ("Enabled", "u1"), ("Start", "i4"), ("Count", "i4")]
        attrs = np.array([(b"Inflow", 1, 0, 1), (b"Outflow", 1, 1, 1)], dtype=dt)
        f.create_dataset("/Boundary Conditions/BC Lines/Attributes", data=attrs)
        xy = [[0, -0.5], [0, 1.5], [outlet_x, -0.5], [outlet_x, 1.5]]
        pl = f.create_dataset("/Boundary Conditions/BC Lines/Polyline", data=np.array(xy))
        pl.attrs["Count"] = np.array([2, 2], dtype="i4")
        pl.attrs["Start"] = np.array([0, 2], dtype="i4")
    return p


def test_cell_coordinates(tmp_path: Path) -> None:
    xy = ResultsReader(_result(tmp_path)).cell_coordinates("Mesh")
    assert xy.shape == (3, 2) and xy[1].tolist() == [1.5, 0.5]


def test_cell_wse_series_nan_where_dry(tmp_path: Path) -> None:
    s = ResultsReader(_result(tmp_path)).cell_wse_series("Mesh", [0, 2])
    assert s.shape == (3, 2)
    assert np.isnan(s[0]).all()
    assert s[1, 0] == pytest.approx(101.0) and np.isnan(s[1, 1])
    assert s[2].tolist() == pytest.approx([102.0, 102.5])
    deeper = ResultsReader(_result(tmp_path)).cell_wse_series("Mesh", [2], min_depth=1.0)
    assert np.isnan(deeper).all()


def test_boundary_faces_and_flow(tmp_path: Path) -> None:
    r = ResultsReader(_result(tmp_path))
    assert r.boundary_faces("Mesh", "Outflow", tol=0.01).tolist() == [3, 4]
    assert r.boundary_faces("Mesh", "Inflow", tol=0.01).tolist() == [7]
    q_out = r.boundary_flow("Mesh", "Outflow", tol=0.01)
    assert q_out.shape == (3,) and q_out.tolist() == pytest.approx([0.0, 4.0, 4.0])
    assert r.boundary_flow("Mesh", "Inflow", tol=0.01).tolist() == pytest.approx([0.0, -5.0, -5.0])


def test_boundary_tolerance_and_unknown_line(tmp_path: Path) -> None:
    r = ResultsReader(_result(tmp_path, outlet_x=2.3))       # line drawn 0.3 off the perimeter
    assert r.boundary_faces("Mesh", "Outflow", tol=0.5).tolist() == [3, 4]
    with pytest.raises(ValueError, match="Outflow"):
        r.boundary_faces("Mesh", "Outflow", tol=0.1)
    with pytest.raises(KeyError):
        r.boundary_flow("Mesh", "Nope", tol=0.5)


def test_reader_satisfies_results_protocol(tmp_path: Path) -> None:
    assert isinstance(ResultsReader(_result(tmp_path)), Results)


def test_boundary_lines(tmp_path: Path) -> None:
    lines = ResultsReader(_result(tmp_path)).boundary_lines()
    assert set(lines) == {"Inflow", "Outflow"}
    assert lines["Outflow"].coords[:] == [(2.0, -0.5), (2.0, 1.5)]


def test_face_flows_from_velocity_and_face_tables() -> None:
    """Flow = face velocity x face area, the area from the face's elevation-area table at the
    higher adjacent water surface, extrapolated linearly above the table top."""
    from flowfield2d.engines.ras2025.results import face_flows

    face_data = np.array([[0, 1, 0, 0], [1, -1, 0, 0]])           # face 1 on the perimeter
    zmin = np.array([10.0, 9.0])
    depth = np.array([2.0, 2.5])                                   # WSE 12.0, 11.5
    vel = np.array([2.0, -1.0])
    # tables: face 0 rows z 10, 11, 13 (area 0, 5, 25); face 1 rows z 9, 10 (area 0, 4)
    tables = np.array([[10.0, 0.0, 0, 0], [11.0, 5.0, 0, 0], [13.0, 25.0, 0, 0],
                       [9.0, 0.0, 0, 0], [10.0, 4.0, 0, 0]])
    start = np.array([0, 3])
    q = face_flows(face_data, zmin, depth, vel, tables, start, np.array([0, 1]))
    # face 0: WSE max(12, 11.5) = 12 -> area 15 -> 30; face 1: WSE 11.5 (one cell), above the
    # table top 10 by 1.5 at slope 4 per unit -> area 10 -> -10
    assert q.tolist() == pytest.approx([30.0, -10.0])
    dry = face_flows(face_data, zmin, np.zeros(2), vel, tables, start, np.array([0, 1]))
    assert dry.tolist() == [0.0, 0.0]

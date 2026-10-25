"""Mesh graph and plateau snapshots for surrogate models (cells -> nodes, faces -> edges)."""

from pathlib import Path

import numpy as np
import pytest

from flowfield2d.engines.ras2025.results import ResultsReader
from flowfield2d.ml.graph import MeshGraph, interpolate_wse, load_dataset, save_dataset

from .test_results_series import _result


def test_mesh_graph_from_results(tmp_path: Path) -> None:
    g = ResultsReader(_result(tmp_path)).mesh_graph("Mesh")
    assert isinstance(g, MeshGraph)
    assert g.xy.shape == (3, 2) and g.bed.tolist() == [100.0, 101.0, 102.0]
    assert g.edges.tolist() == [[0], [1]]                          # one interior face 0-1
    assert g.face_length.tolist() == pytest.approx([1.0])
    assert g.boundary.tolist() == [True, True, False]              # cells on perimeter faces


def test_dataset_roundtrip_and_logq_interpolation(tmp_path: Path) -> None:
    g = MeshGraph(xy=np.zeros((2, 2)), bed=np.array([0.0, 1.0]), edges=np.array([[0], [1]]),
                  face_length=np.array([1.0]), boundary=np.array([True, False]))
    flows = np.array([10.0, 100.0, 1000.0])
    wse = np.array([[1.0, np.nan], [2.0, 2.5], [3.0, 3.5]])        # cell 1 dry at the low flow
    path = tmp_path / "ds.npz"
    save_dataset(path, g, flows, wse)
    g2, f2, w2 = load_dataset(path)
    assert np.array_equal(g2.edges, g.edges) and f2.tolist() == flows.tolist()
    assert np.allclose(w2, wse, equal_nan=True)
    est = interpolate_wse(f2, w2, np.array([np.sqrt(10 * 100.0), 1000.0]))
    assert est[0, 0] == pytest.approx(1.5) and est[1, 1] == pytest.approx(3.5)   # linear in log q
    assert np.isnan(est[0, 1])                                     # dry neighbour -> unknown
    with pytest.raises(ValueError, match="range"):
        interpolate_wse(f2, w2, np.array([5000.0]))                # no extrapolation (range guard)

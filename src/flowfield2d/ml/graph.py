"""Mesh graphs and plateau snapshots for surrogate models.

A 2D mesh becomes a graph: cells are nodes (centre, bed elevation, perimeter flag) and interior
faces are edges (with face length), the structure graph networks exchange messages over, much like
finite-volume fluxes. A run with ascending flow plateaus yields one quasi-steady WSE snapshot per
plateau, so one run gives several training samples. `interpolate_wse` is the baseline a learned
surrogate must beat: per-cell linear interpolation in log Q between plateaus, no extrapolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

F = NDArray[np.float64]


@dataclass(frozen=True)
class MeshGraph:
    xy: F                      # (n, 2) cell centres
    bed: F                     # (n,) cell minimum elevation
    edges: NDArray[np.int64]   # (2, m) interior faces as cell index pairs
    face_length: F             # (m,)
    boundary: NDArray[np.bool_]  # (n,) cells with a perimeter face


def save_dataset(path: Path, graph: MeshGraph, flows: F, wse: F) -> None:
    """Graph plus snapshots: `wse` is (n_flows, n_cells), NaN where dry."""
    flows = np.asarray(flows, dtype=np.float64)
    wse = np.asarray(wse, dtype=np.float64)
    if wse.shape != (flows.size, graph.xy.shape[0]):
        raise ValueError(f"wse must be (n_flows, n_cells) = ({flows.size}, {graph.xy.shape[0]})")
    np.savez_compressed(path, xy=graph.xy, bed=graph.bed, edges=graph.edges,
                        face_length=graph.face_length, boundary=graph.boundary,
                        flows=flows, wse=wse)


def load_dataset(path: Path) -> tuple[MeshGraph, F, F]:
    d = np.load(path)
    g = MeshGraph(xy=d["xy"], bed=d["bed"], edges=d["edges"].astype(np.int64),
                  face_length=d["face_length"], boundary=d["boundary"].astype(bool))
    return g, np.asarray(d["flows"], dtype=np.float64), np.asarray(d["wse"], dtype=np.float64)


def interpolate_wse(flows: F, wse: F, q: F) -> F:
    """Per-cell WSE at flows `q` by linear interpolation in log Q between the two bracketing
    plateaus; NaN where either bracketing snapshot is dry. Flows outside the known range raise
    (a surrogate must not extrapolate)."""
    flows = np.asarray(flows, dtype=np.float64)
    q = np.asarray(q, dtype=np.float64)
    order = np.argsort(flows)
    flows, wse = flows[order], np.asarray(wse, dtype=np.float64)[order]
    if np.any(q < flows[0]) or np.any(q > flows[-1]):
        raise ValueError(f"flows {q.tolist()} outside the known range [{flows[0]}, {flows[-1]}]")
    lf, lq = np.log(flows), np.log(q)
    hi = np.clip(np.searchsorted(lf, lq, side="left"), 1, len(lf) - 1)
    lo = hi - 1
    w = ((lq - lf[lo]) / (lf[hi] - lf[lo]))[:, None]
    return np.asarray(wse[lo] * (1.0 - w) + wse[hi] * w, dtype=np.float64)

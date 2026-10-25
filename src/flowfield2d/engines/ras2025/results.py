"""Results reader for RAS 2025 output HDF5 (layout: probe step D; values checked in the GUI at E8).

- Depth: `/Results/Output Blocks/Base Output/2D Flow Areas/<area>/Cell Depth` [time, cell] (f4)
- Velocity: `.../Face Velocity` [time, face] (f4, face-normal scalar)
- Face flow: `.../DEBUG/FaceFlow` [time, face] (f4)
- Coordinates: `/Geometry/2D Flow Areas/<area>/Cell Coordinates` [cell, 2] (f8)
- Perimeter faces and nodes: `/Geometry/2D Flow Areas/<area>/Face Data` [face, 4],
  `.../Node Coordinates` [node, 2]
- BC lines: `/Boundary Conditions/BC Lines/Polyline` with attrs `Count`, `Start`
- WSE is not stored; WSE = depth + `/Geometry/2D Flow Areas/<area>/Property Tables/Cell Minimum
  Elevation`; dry cells (depth <= min_depth) give NaN
- Time: `/Results/Output Blocks/Base Output/Time` in days from the plan start
- Run status: `/Results/Compute Summary` attrs `Success`, `Solver`, `Compute Log`
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import shapely
from numpy.typing import NDArray
from shapely.geometry import LineString

from flowfield2d.engines.ras2025.split import bc_polylines

BASE = "/Results/Output Blocks/Base Output"
GEOM = "/Geometry/2D Flow Areas"


@dataclass(frozen=True)
class ComputeSummary:
    success: bool
    solver: str
    log: str


def _text(v: Any) -> str:
    return v.decode("utf-8", "replace").rstrip("\x00") if isinstance(v, bytes) else str(v)


class ResultsReader:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _read(self, dataset: str) -> NDArray[Any]:
        with h5py.File(self.path, "r", locking=False) as f:
            return np.asarray(f[dataset][()])

    def areas(self) -> list[str]:
        with h5py.File(self.path, "r", locking=False) as f:
            return sorted(f[BASE + "/2D Flow Areas"].keys())

    def time_days(self) -> NDArray[np.float64]:
        return self._read(BASE + "/Time").astype(np.float64)

    def cell_coordinates(self, area: str) -> NDArray[np.float64]:
        path = f"{GEOM}/{area}/Cell Coordinates"
        return self._read(path).astype(np.float64)

    def cell_depth(self, area: str, t: int) -> NDArray[np.float64]:
        with h5py.File(self.path, "r", locking=False) as f:
            return np.asarray(f[f"{BASE}/2D Flow Areas/{area}/Cell Depth"][t], dtype=np.float64)

    def face_velocity(self, area: str, t: int) -> NDArray[np.float64]:
        with h5py.File(self.path, "r", locking=False) as f:
            return np.asarray(f[f"{BASE}/2D Flow Areas/{area}/Face Velocity"][t], dtype=np.float64)

    def face_flow(self, area: str, t: int) -> NDArray[np.float64]:
        with h5py.File(self.path, "r", locking=False) as f:
            return np.asarray(f[f"{BASE}/2D Flow Areas/{area}/DEBUG/FaceFlow"][t], dtype=np.float64)

    def cell_min_elevation(self, area: str) -> NDArray[np.float64]:
        path = f"{GEOM}/{area}/Property Tables/Cell Minimum Elevation"
        return self._read(path).astype(np.float64)

    def cell_wse(self, area: str, t: int, min_depth: float = 0.0) -> NDArray[np.float64]:
        d = self.cell_depth(area, t)
        wse = d + self.cell_min_elevation(area)
        return np.where(d > min_depth, wse, np.nan)

    def cell_wse_series(
        self, area: str, cells: Sequence[int], min_depth: float = 0.0
    ) -> NDArray[np.float64]:
        idx = np.asarray(cells, dtype=np.int64)
        depth = self._read(f"{BASE}/2D Flow Areas/{area}/Cell Depth").astype(np.float64)[:, idx]
        wse = depth + self.cell_min_elevation(area)[idx]
        return np.where(depth > min_depth, wse, np.nan)

    def boundary_faces(self, area: str, line: str, tol: float) -> NDArray[np.int64]:
        bcs = bc_polylines(self.path)
        if line not in bcs:
            raise KeyError(f"unknown BC line: {line}")
        poly = bcs[line]

        with h5py.File(self.path, "r", locking=False) as f:
            face_data = np.asarray(f[f"{GEOM}/{area}/Face Data"][()])
            nodes = np.asarray(f[f"{GEOM}/{area}/Node Coordinates"][()], dtype=np.float64)

        perim = np.flatnonzero(face_data[:, 1] == -1)
        near_a = shapely.distance(poly, shapely.points(nodes[face_data[perim, 2]])) <= tol
        near_b = shapely.distance(poly, shapely.points(nodes[face_data[perim, 3]])) <= tol
        keep = np.asarray(near_a & near_b, dtype=bool)
        matching: NDArray[np.int64] = perim[keep].astype(np.int64)
        if matching.size == 0:
            raise ValueError(f"no faces qualify for boundary line {line!r} within tolerance {tol}")
        return matching

    def boundary_flow(self, area: str, line: str, tol: float) -> NDArray[np.float64]:
        faces = self.boundary_faces(area, line, tol)
        flows = self._read(f"{BASE}/2D Flow Areas/{area}/DEBUG/FaceFlow").astype(np.float64)
        return np.asarray(flows[:, faces].sum(axis=1), dtype=np.float64)

    def boundary_lines(self) -> dict[str, LineString]:
        """BC lines as run (the result file carries the BC layer)."""
        return bc_polylines(self.path)

    def compute_summary(self) -> ComputeSummary:
        with h5py.File(self.path, "r", locking=False) as f:
            a = f["/Results/Compute Summary"].attrs
            return ComputeSummary(bool(a.get("Success", 0)), _text(a.get("Solver", "")),
                                  _text(a.get("Compute Log", "")))

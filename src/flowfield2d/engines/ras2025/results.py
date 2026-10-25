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
from numpy.typing import NDArray
from shapely.geometry import Point

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
        cell_idx = [int(c) for c in cells]
        with h5py.File(self.path, "r", locking=False) as f:
            ds = f[f"{BASE}/2D Flow Areas/{area}/Cell Depth"]
            try:
                depth = np.asarray(ds[:, cell_idx], dtype=np.float64)
            except (IndexError, TypeError):
                depth = np.asarray(ds[()], dtype=np.float64)[:, cell_idx]
        elev = self.cell_min_elevation(area)[cell_idx]
        wse = depth + elev
        return np.where(depth > min_depth, wse, np.nan)

    def boundary_faces(self, area: str, line: str, tol: float) -> NDArray[np.int64]:
        bcs = bc_polylines(self.path)
        if line not in bcs:
            raise KeyError(f"unknown BC line: {line}")
        poly = bcs[line]

        with h5py.File(self.path, "r", locking=False) as f:
            face_data = np.asarray(f[f"{GEOM}/{area}/Face Data"][()])
            nodes = np.asarray(f[f"{GEOM}/{area}/Node Coordinates"][()], dtype=np.float64)

        matching: list[int] = []
        for face_idx in range(len(face_data)):
            cell_b = int(face_data[face_idx, 1])
            if cell_b != -1:
                continue
            fp_a = int(face_data[face_idx, 2])
            fp_b = int(face_data[face_idx, 3])
            pt_a = Point(float(nodes[fp_a, 0]), float(nodes[fp_a, 1]))
            pt_b = Point(float(nodes[fp_b, 0]), float(nodes[fp_b, 1]))
            if poly.distance(pt_a) <= tol and poly.distance(pt_b) <= tol:
                matching.append(face_idx)

        if not matching:
            raise ValueError(f"no faces qualify for boundary line {line!r} within tolerance {tol}")
        return np.array(matching, dtype=np.int64)

    def boundary_flow(self, area: str, line: str, tol: float) -> NDArray[np.float64]:
        faces = self.boundary_faces(area, line, tol)
        face_idx = [int(i) for i in faces]
        with h5py.File(self.path, "r", locking=False) as f:
            ds = f[f"{BASE}/2D Flow Areas/{area}/DEBUG/FaceFlow"]
            try:
                flows = np.asarray(ds[:, face_idx], dtype=np.float64)
            except (IndexError, TypeError):
                flows = np.asarray(ds[()], dtype=np.float64)[:, face_idx]
        return np.asarray(flows.sum(axis=1), dtype=np.float64)

    def compute_summary(self) -> ComputeSummary:
        with h5py.File(self.path, "r", locking=False) as f:
            a = f["/Results/Compute Summary"].attrs
            return ComputeSummary(bool(a.get("Success", 0)), _text(a.get("Solver", "")),
                                  _text(a.get("Compute Log", "")))

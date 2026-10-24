"""Results reader for RAS 2025 output HDF5 (layout: probe step D; values checked in the GUI at E8).

- Depth: `/Results/Output Blocks/Base Output/2D Flow Areas/<area>/Cell Depth` [time, cell] (f4)
- Velocity: `.../Face Velocity` [time, face] (f4, face-normal scalar)
- WSE is not stored; WSE = depth + `/Geometry/2D Flow Areas/<area>/Property Tables/Cell Minimum
  Elevation`; dry cells (depth <= min_depth) give NaN
- Time: `/Results/Output Blocks/Base Output/Time` in days from the plan start
- Run status: `/Results/Compute Summary` attrs `Success`, `Solver`, `Compute Log`
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import h5py
import numpy as np
from numpy.typing import NDArray

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

    def cell_depth(self, area: str, t: int) -> NDArray[np.float64]:
        with h5py.File(self.path, "r", locking=False) as f:
            return np.asarray(f[f"{BASE}/2D Flow Areas/{area}/Cell Depth"][t], dtype=np.float64)

    def face_velocity(self, area: str, t: int) -> NDArray[np.float64]:
        with h5py.File(self.path, "r", locking=False) as f:
            return np.asarray(f[f"{BASE}/2D Flow Areas/{area}/Face Velocity"][t], dtype=np.float64)

    def cell_min_elevation(self, area: str) -> NDArray[np.float64]:
        path = f"{GEOM}/{area}/Property Tables/Cell Minimum Elevation"
        return self._read(path).astype(np.float64)

    def cell_wse(self, area: str, t: int, min_depth: float = 0.0) -> NDArray[np.float64]:
        d = self.cell_depth(area, t)
        wse = d + self.cell_min_elevation(area)
        return np.where(d > min_depth, wse, np.nan)

    def compute_summary(self) -> ComputeSummary:
        with h5py.File(self.path, "r", locking=False) as f:
            a = f["/Results/Compute Summary"].attrs
            return ComputeSummary(bool(a.get("Success", 0)), _text(a.get("Solver", "")),
                                  _text(a.get("Compute Log", "")))

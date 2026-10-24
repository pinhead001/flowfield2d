"""Boundary-condition layer edits for RAS 2025 BC files (template edits under REQUIREMENTS 3.3).

Layout observed at probe step D (`/Boundary Conditions/BC Lines/Payloads`): a compound `Payloads`
table, one row per BC payload (`Variable` e.g. "Flow" or "Normal Depth"; `Mode` "TimeSeries" or
"Constant"; `Constant`; `Row` indexing `Time Series Definitions`), plus `Times` (i8, 100-ns ticks
offset from the BC `Start Time`) and `Values` (f8). Edits go through `h5edit.recreate_dataset`,
which keeps dtype, chunking, filters and attributes and never resizes. Callers run the schema guard
first (`h5edit.guarded`); these functions edit a file path directly for scratch copies and tests.

Only single-series files are handled so far (one flow series); multi-line BCs come with the writer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np

from flowfield2d.engines.ras2025.h5edit import recreate_dataset

PAYLOADS = "/Boundary Conditions/BC Lines/Payloads"


@dataclass(frozen=True)
class BcPayload:
    index: int
    variable: str
    mode: str
    enabled: bool
    constant: float
    row: int


def _s(x: bytes | str) -> str:
    return x.decode("ascii", "replace").rstrip("\x00") if isinstance(x, bytes) else str(x)


def payloads(path: Path) -> list[BcPayload]:
    with h5py.File(path, "r", locking=False) as f:
        arr = f[PAYLOADS]["Payloads"][:]
    return [BcPayload(i, _s(r["Variable"]), _s(r["Mode"]), bool(r["Enabled"]),
                      float(r["Constant"]), int(r["Row"])) for i, r in enumerate(arr)]


def _only(rows: list[BcPayload], variable: str, mode: str, what: str) -> BcPayload:
    hits = [r for r in rows if r.variable == variable and r.mode == mode]
    if len(hits) != 1:
        raise ValueError(f"expected exactly one {what} payload, found {len(hits)} {what}")
    return hits[0]


def scale_flow_series(path: Path, factor: float) -> None:
    """Multiply the single flow time series by `factor` (> 0)."""
    if not factor > 0:
        raise ValueError("factor must be positive")
    _only(payloads(path), "Flow", "TimeSeries", "flow")
    with h5py.File(path, "r+", locking=False) as f:
        g = f[PAYLOADS]
        recreate_dataset(g, "Values", g["Values"][:] * factor)


def set_normal_depth_slope(path: Path, slope: float, allow_invalid: bool = False) -> None:
    """Set the single normal-depth BC's friction slope; `allow_invalid` permits 0 (probe E6b)."""
    if slope < 0 or (slope == 0 and not allow_invalid):
        raise ValueError("normal-depth slope must be positive")
    target = _only(payloads(path), "Normal Depth", "Constant", "normal-depth")
    with h5py.File(path, "r+", locking=False) as f:
        g = f[PAYLOADS]
        arr = np.array(g["Payloads"][:])
        arr["Constant"][target.index] = slope
        recreate_dataset(g, "Payloads", arr)

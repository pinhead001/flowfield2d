"""Pre-compute BC validation.

Probe E6b showed RAS 2025 accepts a zero normal-depth slope and reports success, so every compute
is preceded by these checks (ADR-0001).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np

from flowfield2d.engines.ras2025.bc import BC, PAYLOADS, TSD, payloads


@dataclass(frozen=True)
class BcProblem:
    kind: str
    message: str


def validate_bc(path: Path) -> list[BcProblem]:
    """Problems found in a BC file; empty means it may be computed."""
    probs: list[BcProblem] = []
    for p in payloads(path):
        is_slope = p.enabled and p.variable == "Normal Depth" and p.mode == "Constant"
        if is_slope and not p.constant > 0:
            msg = f"payload {p.index}: normal-depth slope {p.constant} must be > 0"
            probs.append(BcProblem("slope_not_positive", msg))
    with h5py.File(path, "r", locking=False) as f:
        g = f[PAYLOADS]
        times = g["Times"][:] if "Times" in g else np.array([], dtype="i8")
        values = g["Values"][:] if "Values" in g else np.array([])
        defs = g[TSD][:] if TSD in g else None
        b = f[BC].attrs
        window = int(b["End Time"]) - int(b["Start Time"]) \
            if "End Time" in b and "Start Time" in b else None
    if values.size and not np.all(np.isfinite(values)):
        probs.append(BcProblem("flow_not_finite", "time series contains NaN or infinite values"))
    if values.size and np.nanmin(values) < 0:
        probs.append(BcProblem("flow_negative",
                               f"time series minimum {float(np.nanmin(values))} is negative"))
    if times.size and values.size and times.size != values.size:
        probs.append(BcProblem("length_mismatch",
                               f"{times.size} times but {values.size} values"))
    # Each series is a slice of the shared Times array; check them one at a time.
    series = [(i, times[int(d["Start (Time)"]):int(d["Start (Time)"]) + int(d["Count"])])
              for i, d in enumerate(defs)] if defs is not None else [(0, times)]
    for i, t in series:
        if t.size > 1 and not np.all(np.diff(t) > 0):
            probs.append(BcProblem("times_not_increasing",
                                   f"series {i}: times must be strictly increasing"))
        if window is not None and t.size and int(t[-1]) < window:
            probs.append(BcProblem("series_short",
                                   f"series {i} ends before the BC window ends"))
    return probs

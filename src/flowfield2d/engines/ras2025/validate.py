"""Pre-compute BC validation.

Probe E6b showed RAS 2025 accepts a zero normal-depth slope and reports success, so every compute
is preceded by these checks (ADR-0001).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np

from flowfield2d.engines.ras2025.bc import PAYLOADS, payloads


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
    if values.size and not np.all(np.isfinite(values)):
        probs.append(BcProblem("flow_not_finite", "time series contains NaN or infinite values"))
    if values.size and np.nanmin(values) < 0:
        probs.append(BcProblem("flow_negative",
                               f"time series minimum {float(np.nanmin(values))} is negative"))
    if times.size > 1 and not np.all(np.diff(times) > 0):
        probs.append(BcProblem("times_not_increasing", "series times must be strictly increasing"))
    if times.size and values.size and times.size != values.size:
        probs.append(BcProblem("length_mismatch",
                               f"{times.size} times but {values.size} values"))
    return probs

"""Modeled WSE against observed stage at matched discharge (REQUIREMENTS 4, Calibration).

Observed WSE = stage + datum offset (both in the model's vertical units). Modeled WSE at a gage
comes from the model's stage-discharge relation there (one point per steady plateau), interpolated
linearly at the observed discharge; extrapolation is refused.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import ArrayLike


@dataclass(frozen=True)
class Observation:
    gage_id: str
    q: float
    stage: float
    datum_offset: float


@dataclass
class CalibrationResult:
    mean_abs: float
    tol: float
    ok: bool
    n_used: int
    deltas: list[float]                       # modeled - observed, in observation order
    by_gage: dict[str, float] = field(default_factory=dict)   # mean |delta| per gage
    skipped: list[str] = field(default_factory=list)          # gage ids without a rating


def modeled_wse_at(q: ArrayLike, wse: ArrayLike, q_obs: float) -> float:
    qa = np.asarray(q, dtype=np.float64)
    wa = np.asarray(wse, dtype=np.float64)
    order = np.argsort(qa)
    qa, wa = qa[order], wa[order]
    if not qa[0] <= q_obs <= qa[-1]:
        raise ValueError(f"discharge {q_obs} outside modeled range {qa[0]}..{qa[-1]}")
    return float(np.interp(q_obs, qa, wa))


def compare(ratings: Mapping[str, tuple[ArrayLike, ArrayLike]], observations: Iterable[Observation],
            tol: float = 0.15) -> CalibrationResult:
    """Mean |modeled - observed WSE| over observations whose gage has a modeled rating."""
    deltas: list[float] = []
    per_gage: dict[str, list[float]] = {}
    skipped: list[str] = []
    for o in observations:
        if o.gage_id not in ratings:
            skipped.append(o.gage_id)
            continue
        q, w = ratings[o.gage_id]
        d = modeled_wse_at(q, w, o.q) - (o.stage + o.datum_offset)
        deltas.append(d)
        per_gage.setdefault(o.gage_id, []).append(abs(d))
    if not deltas:
        raise ValueError("no observation matched a modeled rating")
    mean_abs = float(np.mean(np.abs(deltas)))
    return CalibrationResult(mean_abs, tol, mean_abs <= tol, len(deltas), deltas,
                             {g: float(np.mean(v)) for g, v in per_gage.items()}, skipped)


def best_n(sweep: Mapping[float, float], n_min: float, n_max: float) -> tuple[float, float]:
    """Channel n with the lowest error among sweep values within [n_min, n_max]."""
    inside = {n: e for n, e in sweep.items() if n_min <= n <= n_max}
    if not inside:
        raise ValueError(f"no sweep value within [{n_min}, {n_max}]")
    n = min(inside, key=lambda k: inside[k])
    return n, inside[n]

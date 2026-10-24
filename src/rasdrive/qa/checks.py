"""QA checks on model results (REQUIREMENTS 4, QA row).

Each check is a pure function over arrays and returns a `CheckResult`. Tolerances are
parameters; the defaults are the generic starting points from REQUIREMENTS 4, and projects
pass their own.
NaN marks dry or missing cells and is ignored where noted.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

F = NDArray[np.float64]


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    value: float
    tolerance: float
    detail: str = ""


def _f(x: ArrayLike) -> F:
    return np.asarray(x, dtype=np.float64)


def _same_shape(a: F, b: F, what: str) -> None:
    if a.shape != b.shape:
        raise ValueError(f"{what}: shapes differ {a.shape} vs {b.shape}")


def _max_abs_diff(a: F, b: F) -> float:
    d = np.abs(a - b)
    d = d[np.isfinite(d)]
    return float(d.max()) if d.size else 0.0


def volume_balance(q_in: ArrayLike, q_out: ArrayLike, tol: float = 0.01) -> CheckResult:
    """|mean(Q_out) - mean(Q_in)| / mean(Q_in) over the samples given (e.g. a hold)."""
    qi, qo = _f(q_in), _f(q_out)
    mean_in = float(np.mean(qi))
    if mean_in <= 0:
        raise ValueError("mean inflow must be positive")
    v = abs(float(np.mean(qo)) - mean_in) / mean_in
    return CheckResult("volume_balance", v <= tol, v, tol, f"mean in {mean_in:.6g}")


def convergence(t_s: ArrayLike, q_in: ArrayLike, q_out: ArrayLike, wse: ArrayLike,
                hold_end_s: float, window_s: float = 1800.0, q_tol: float = 0.01,
                wse_tol: float = 0.005) -> CheckResult:
    """Converged at the end of a hold: flow imbalance at `hold_end_s` within `q_tol` (relative) and
    WSE change over the last `window_s` within `wse_tol` at every monitored point.

    `wse` is (n_t,) or (n_t, n_points). The value reported is the worst WSE change.
    """
    t, qi, qo, w = _f(t_s), _f(q_in), _f(q_out), _f(wse)
    if w.ndim == 1:
        w = w[:, None]
    if not (t.shape[0] == qi.shape[0] == qo.shape[0] == w.shape[0]):
        raise ValueError("time, flow and WSE series must have the same length")
    sel = (t >= hold_end_s - window_s - 1e-9) & (t <= hold_end_s + 1e-9)
    if sel.sum() < 2:
        raise ValueError("fewer than two samples in the convergence window")
    end = int(np.flatnonzero(sel)[-1])
    q_err = abs(qo[end] - qi[end]) / qi[end]
    span = np.nanmax(w[sel], axis=0) - np.nanmin(w[sel], axis=0)
    dw = float(np.nanmax(span))
    ok = bool(q_err <= q_tol and dw <= wse_tol)
    return CheckResult("convergence", ok, dw, wse_tol,
                       f"flow imbalance {q_err:.4f} (tol {q_tol}); WSE change {dw:.4f} m")


def wse_monotonic(station: ArrayLike, wse: ArrayLike, exceptions: Iterable[float] = (),
                  tol: float = 0.0) -> CheckResult:
    """WSE must not rise going downstream (station increasing downstream) by more than `tol`.

    `exceptions` lists stations whose rise is accepted (e.g. a known hydraulic jump)."""
    s, w = _f(station), _f(wse)
    _same_shape(s, w, "wse_monotonic")
    order = np.argsort(s, kind="stable")
    s, w = s[order], w[order]
    rise = np.diff(w)
    skip = {float(x) for x in exceptions}
    bad = [(float(s[i + 1]), float(rise[i])) for i in range(rise.size)
           if rise[i] > tol and float(s[i + 1]) not in skip]
    worst = max((r for _, r in bad), default=0.0)
    detail = "; ".join(f"rise {r:.3f} at station {st:g}" for st, r in bad)
    return CheckResult("wse_monotonic", not bad, worst, tol, detail)


def bc_sensitivity(wse_base: ArrayLike, wse_low: ArrayLike, wse_high: ArrayLike,
                   tol: float = 0.03) -> CheckResult:
    """Max |ΔWSE| at the analysis boundary when the downstream BC slope is scaled 0.5x and 2x."""
    b, lo, hi = _f(wse_base), _f(wse_low), _f(wse_high)
    _same_shape(b, lo, "bc_sensitivity")
    _same_shape(b, hi, "bc_sensitivity")
    v = max(_max_abs_diff(b, lo), _max_abs_diff(b, hi))
    return CheckResult("bc_sensitivity", v <= tol, v, tol)


def overlap(wse_a: ArrayLike, wse_b: ArrayLike, tol: float = 0.05) -> CheckResult:
    """Max |ΔWSE| between neighbouring domains at shared points (NaN = not shared or dry)."""
    a, b = _f(wse_a), _f(wse_b)
    _same_shape(a, b, "overlap")
    v = _max_abs_diff(a, b)
    return CheckResult("overlap", v <= tol, v, tol)


def determinism(a: ArrayLike, b: ArrayLike, tol: float = 0.0) -> CheckResult:
    """Max |Δ| between two runs of the same inputs; detail says whether they are bit-identical."""
    x, y = _f(a), _f(b)
    _same_shape(x, y, "determinism")
    identical = bool(np.array_equal(x, y, equal_nan=True))
    v = 0.0 if identical else _max_abs_diff(x, y)
    return CheckResult("determinism", v <= tol, v, tol, "identical" if identical else "differs")


def wet_dry(depth: ArrayLike, allow_nan: bool = True) -> CheckResult:
    """Depths must be non-negative; NaN (dry) is allowed unless `allow_nan` is False."""
    d = _f(depth)
    problems = []
    n_neg = int(np.sum(d < 0))
    if n_neg:
        problems.append(f"{n_neg} negative depth(s), min {float(np.nanmin(d)):.4f}")
    n_nan = int(np.sum(np.isnan(d)))
    if n_nan and not allow_nan:
        problems.append(f"{n_nan} NaN depth(s)")
    return CheckResult("wet_dry", not problems, float(n_neg), 0.0, "; ".join(problems))

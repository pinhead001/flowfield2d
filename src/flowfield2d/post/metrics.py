"""Per-feature hydraulic statistics with generic column names (REQUIREMENTS 4, Metrics/Outputs).

A feature is any polygon or centerline buffer rasterized to a boolean mask on the result grid.
Projects map these columns to their own vocabulary. All values are SI unless `units="US"` is used
for shear; depths and velocities are taken as given.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

RHO_G_SI = 1000.0 * 9.81      # N/m^3
GAMMA_US = 62.4               # lb/ft^3
MANNING_K_US = 1.486

METRIC_COLUMNS = (
    "feature_id", "scenario_id", "wetted_area", "mean_width", "depth_mean", "depth_max",
    "velocity_mean", "velocity_max", "area_outside_reference", "excluded_area",
    "void_fraction", "converged",
)


def shear_stress(n: ArrayLike, velocity: ArrayLike, depth: ArrayLike,
                 units: str = "SI") -> Any:
    """Bed shear tau = rho g n^2 V^2 / h^(1/3) (SI, Pa); in US units gamma n^2 V^2 /
    (1.486^2 h^(1/3)) (lb/ft^2). Cells with h <= 0 or NaN give NaN. Scalars in, scalar out."""
    if units == "SI":
        coef = RHO_G_SI
    elif units == "US":
        coef = GAMMA_US / MANNING_K_US**2
    else:
        raise ValueError(f"units must be 'SI' or 'US', not {units!r}")
    nn, v, h = (np.asarray(x, dtype=np.float64) for x in (n, velocity, depth))
    with np.errstate(divide="ignore", invalid="ignore"):
        tau = np.where(h > 0, coef * nn**2 * v**2 / np.cbrt(np.where(h > 0, h, 1.0)), np.nan)
    return float(tau) if tau.ndim == 0 else tau


def _stats(values: NDArray[np.float64], prefix: str,
           percentiles: Sequence[float]) -> dict[str, float]:
    finite = values[np.isfinite(values)]
    out: dict[str, float] = {}
    if prefix != "shear":
        out[f"{prefix}_mean"] = float(finite.mean()) if finite.size else float("nan")
        out[f"{prefix}_max"] = float(finite.max()) if finite.size else float("nan")
    for p in percentiles:
        key = f"{prefix}_p{p:g}"
        out[key] = float(np.percentile(finite, p)) if finite.size else float("nan")
    return out


def feature_metrics(feature_id: str, scenario_id: str, depth: ArrayLike, velocity: ArrayLike,
                    mask: ArrayLike, cell_area: float, length: float, *,
                    min_depth: float = 0.0, roughness: ArrayLike | None = None,
                    reference_extent: ArrayLike | None = None,
                    exclude_mask: ArrayLike | None = None,
                    void_mask: ArrayLike | None = None, converged: bool | None = None,
                    percentiles: Sequence[float] = (10, 50, 90)) -> dict[str, Any]:
    """Statistics over the wet cells (finite depth > `min_depth`) of one feature.

    - `wetted_area` = wet cells x `cell_area`; `mean_width` = wetted_area / `length`
    - depth and velocity mean, max and percentiles; shear percentiles when `roughness` is given
      (cells flagged in `exclude_mask` are omitted from these statistics)
    - `area_outside_reference`: wet area outside `reference_extent` (e.g. a mapped channel)
    - `excluded_area`: wet area flagged in `exclude_mask` (NaN when `exclude_mask` is None)
    - `void_fraction`: wet cells flagged in `void_mask` / wet cells (0 when nothing is wet)
    """
    d = np.asarray(depth, dtype=np.float64)
    v = np.asarray(velocity, dtype=np.float64)
    m = np.asarray(mask, dtype=bool)
    arrays = [v, m]
    extra = {
        "roughness": roughness,
        "reference_extent": reference_extent,
        "exclude_mask": exclude_mask,
        "void_mask": void_mask,
    }
    arrays += [np.asarray(a) for a in extra.values() if a is not None]
    if any(a.shape != d.shape for a in arrays):
        raise ValueError("all grids must share the depth grid's shape")
    if cell_area <= 0 or length <= 0:
        raise ValueError("cell_area and length must be positive")

    with np.errstate(invalid="ignore"):
        wet = m & np.isfinite(d) & (d > min_depth)
    n_wet = int(wet.sum())
    area = n_wet * float(cell_area)
    out: dict[str, Any] = {
        "feature_id": feature_id, "scenario_id": scenario_id,
        "wetted_area": area, "mean_width": area / float(length),
    }
    if exclude_mask is not None:
        stat_mask = wet & ~np.asarray(exclude_mask, dtype=bool)
    else:
        stat_mask = wet
    out.update(_stats(d[stat_mask], "depth", percentiles))
    out.update(_stats(v[stat_mask], "velocity", percentiles))
    if roughness is not None:
        tau = np.asarray(shear_stress(np.asarray(roughness)[stat_mask], v[stat_mask], d[stat_mask]))
    else:
        tau = np.full(int(stat_mask.sum()), np.nan)
    out.update(_stats(tau, "shear", percentiles))
    if reference_extent is not None:
        outside = wet & ~np.asarray(reference_extent, dtype=bool)
        out["area_outside_reference"] = int(outside.sum()) * float(cell_area)
    else:
        out["area_outside_reference"] = float("nan")
    if exclude_mask is not None:
        excluded = wet & np.asarray(exclude_mask, dtype=bool)
        out["excluded_area"] = int(excluded.sum()) * float(cell_area)
    else:
        out["excluded_area"] = float("nan")
    if n_wet == 0:
        out["void_fraction"] = 0.0
    elif void_mask is None:
        out["void_fraction"] = float("nan")  # unknown, not zero
    else:
        out["void_fraction"] = float((wet & np.asarray(void_mask, dtype=bool)).sum()) / n_wet
    out["converged"] = converged
    return out

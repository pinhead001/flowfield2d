"""Land-cover class raster plus a Manning's n table to a roughness raster (REQUIREMENTS 4).

The n table is the project's; every class present in the raster must be in it (a missing class
fails loudly rather than defaulting). Output keeps the class raster's grid exactly.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from numpy.typing import ArrayLike, NDArray


def map_classes(classes: ArrayLike, n_table: Mapping[int, float],
                nodata: int | None = None) -> NDArray[np.float32]:
    """Map class codes to n; nodata cells become NaN."""
    c = np.asarray(classes)
    bad_n = {k: v for k, v in n_table.items() if not v > 0}
    if bad_n:
        raise ValueError(f"n must be positive: {bad_n}")
    valid = np.ones(c.shape, bool) if nodata is None else c != nodata
    present = {int(x) for x in np.unique(c[valid])}
    missing = sorted(present - {int(k) for k in n_table})
    if missing:
        raise ValueError(f"classes without an n value: {missing}")
    out = np.full(c.shape, np.nan, dtype=np.float32)
    for k, v in n_table.items():
        out[valid & (c == int(k))] = v
    return out


def roughness_from_classes(class_raster: Path, n_table: Mapping[int, float], out: Path) -> Path:
    """Write a float32 n raster on the class raster's grid (nodata NaN)."""
    with rasterio.open(class_raster) as src:
        classes = src.read(1)
        nodata = None if src.nodata is None else int(src.nodata)
        profile: dict[str, Any] = src.profile.copy()
    n = map_classes(classes, n_table, nodata)
    profile.update(driver="GTiff", dtype="float32", nodata=float("nan"), count=1)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out, "w", **profile) as dst:
        dst.write(n, 1)
    return Path(out)

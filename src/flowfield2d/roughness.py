"""Land-cover class raster plus a Manning's n table to a roughness raster (REQUIREMENTS 4).

The n table is the project's; every class present in the raster must be in it (a missing class
fails loudly rather than defaulting). Output keeps the class raster's grid exactly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import rasterio.features
import rasterio.transform
from numpy.typing import ArrayLike, NDArray
from shapely.geometry import Polygon


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


def rasterize_n(polygons: Sequence[tuple[Polygon, float]], default: float,
                bounds: tuple[float, float, float, float], res: float, out: Path,
                crs: str | None = None) -> Path:
    """Manning's n raster (float32 GeoTIFF) over `bounds` (minx, miny, maxx, maxy) at cell size
    `res`: `default` everywhere, then each polygon's n burned in order, so a later polygon
    covers an earlier one. A cell takes a polygon's n when its centre is inside."""
    if not res > 0:
        raise ValueError("res must be positive")
    minx, miny, maxx, maxy = bounds
    width = int(np.ceil((maxx - minx) / res))
    height = int(np.ceil((maxy - miny) / res))
    if width < 1 or height < 1:
        raise ValueError(f"empty bounds {bounds}")
    transform = rasterio.transform.from_origin(minx, maxy, res, res)
    a = np.full((height, width), float(default), dtype="float32")
    for poly, n in polygons:
        if not poly.is_empty:
            rasterio.features.rasterize([(poly, float(n))], out=a, transform=transform)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out, "w", driver="GTiff", height=height, width=width, count=1,
                       dtype="float32", transform=transform, crs=crs, compress="deflate") as ds:
        ds.write(a, 1)
    return Path(out)

"""Clip and mosaic DEM tiles per domain; void-mask summaries (REQUIREMENTS 4, Terrain).

No reprojection or resampling: tiles must share CRS and resolution, otherwise this refuses.
CRS, units and vertical datum come from each DEM delivery's sidecar JSON.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
import rasterio.merge
from numpy.typing import ArrayLike

SIDECAR_KEYS = ("crs", "horizontal_units", "vertical_units", "vertical_datum")


@dataclass(frozen=True)
class TerrainMeta:
    crs: str
    horizontal_units: str
    vertical_units: str
    vertical_datum: str


def read_sidecar(path: Path) -> TerrainMeta:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [k for k in SIDECAR_KEYS if not str(raw.get(k, "")).strip()]
    if missing:
        raise ValueError(f"{path}: sidecar missing {', '.join(missing)}")
    return TerrainMeta(*(str(raw[k]) for k in SIDECAR_KEYS))


def clip_mosaic(tiles: Sequence[Path], bounds: tuple[float, float, float, float],
                out: Path) -> Path:
    """Mosaic `tiles` clipped to `bounds` (minx, miny, maxx, maxy) into a GeoTIFF at `out`."""
    if not tiles:
        raise ValueError("no tiles given")
    srcs = [rasterio.open(t) for t in tiles]
    try:
        crs = {s.crs.to_string() if s.crs else None for s in srcs}
        if len(crs) != 1:
            raise ValueError(f"tiles have different CRS {sorted(map(str, crs))}; no reprojection")
        res = {tuple(round(r, 9) for r in s.res) for s in srcs}
        if len(res) != 1:
            raise ValueError(f"tiles have different resolution {sorted(res)}; no resampling")
        data, transform = rasterio.merge.merge(srcs, bounds=bounds)
        profile = srcs[0].profile.copy()
        profile.update(driver="GTiff", height=data.shape[1], width=data.shape[2],
                       transform=transform, count=data.shape[0])
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(out, "w", **profile) as dst:
            dst.write(data)
    finally:
        for s in srcs:
            s.close()
    return Path(out)


def void_fraction(void_mask: ArrayLike, wet: ArrayLike) -> float:
    """Void cells within the wetted area divided by wetted cells (0 when nothing is wet)."""
    w = np.asarray(wet, dtype=bool)
    n = int(w.sum())
    return float((np.asarray(void_mask, dtype=bool) & w).sum()) / n if n else 0.0

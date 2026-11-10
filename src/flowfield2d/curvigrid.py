"""Structured curvilinear (i, j) grid along a line, for solvers that need one.

`build_grid` lays `ni` cross-sections normal to a centerline at equal chainage steps and `nj`
nodes across each. i runs along the line (give the line in the downstream direction); j runs from
the right bank to the left bank looking along i, so (i, j) is right-handed and cell areas are
positive. A grid whose sections cross (bend radius under the half width) is refused, not repaired.

`sample_raster` puts raster values on grid nodes or cell centres. Everything stays in the CRS
units of the inputs; no unit conversion happens here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import rasterio
from numpy.typing import ArrayLike, NDArray
from scipy.ndimage import map_coordinates
from shapely.geometry import LineString

F = NDArray[np.float64]


@dataclass(frozen=True)
class CurviGrid:
    """Node coordinates `xy` (ni, nj, 2) and the chainage `s` (ni,) of each cross-section."""

    xy: F
    s: F

    @property
    def ni(self) -> int:
        return int(self.xy.shape[0])

    @property
    def nj(self) -> int:
        return int(self.xy.shape[1])

    def cell_centres(self) -> F:
        """(ni-1, nj-1, 2): mean of each cell's four nodes."""
        a = self.xy
        return np.asarray((a[:-1, :-1] + a[1:, :-1] + a[1:, 1:] + a[:-1, 1:]) / 4.0)

    def cell_areas(self) -> F:
        """(ni-1, nj-1) signed areas (shoelace, node order i then j): positive when valid."""
        a = self.xy
        d1 = a[1:, 1:] - a[:-1, :-1]
        d2 = a[:-1, 1:] - a[1:, :-1]
        return np.asarray(0.5 * (d1[..., 0] * d2[..., 1] - d1[..., 1] * d2[..., 0]))


def smooth_line(line: LineString, window: float, step: float | None = None) -> LineString:
    """`line` resampled every `step` (default window / 10) and averaged over a moving window of
    length `window` along it, so bends tighter than the window are rounded. The line is extended
    straight past each end by half a window first, so an end point stays where it is unless the
    line bends within half a window of it. Use it when `build_grid` refuses a line because
    sections cross at sharp vertices, with `step` no larger than the grid's section spacing:
    the result is still a polyline, and a grid finer than its vertices sees them as corners."""
    if not window > 0:
        raise ValueError("window must be positive")
    length = float(line.length)
    if length <= 0:
        raise ValueError("line is empty")
    ds = float(step) if step is not None else window / 10.0
    if not ds > 0:
        raise ValueError("step must be positive")
    n = max(int(np.ceil(length / ds)), 1) + 1
    ds = length / (n - 1)
    half = max(int(round(0.5 * window / ds)), 1)
    inner = np.array([(q.x, q.y) for q in
                      (line.interpolate(float(v)) for v in np.linspace(0.0, length, n))])
    steps = np.arange(1, half + 1)[:, None]
    head = inner[0] - steps[::-1] * (inner[1] - inner[0])
    tail = inner[-1] + steps * (inner[-1] - inner[-2])
    pts = np.vstack([head, inner, tail])
    csum = np.vstack([np.zeros((1, 2)), np.cumsum(pts, axis=0)])
    out = (csum[2 * half + 1:] - csum[:-(2 * half + 1)]) / (2 * half + 1)
    return LineString(out)


def build_grid(centerline: LineString, width: float | ArrayLike, ni: int, nj: int) -> CurviGrid:
    """Grid of `ni` sections by `nj` nodes along `centerline`, centred on it.

    `width` is the full section width, one value or one per section (ni,). The tangent at a
    section is the chord between the points half a step up and down the line, which rounds
    vertices at the scale of the section spacing. ValueError if any cell has non-positive area
    (sections cross: narrow the grid, smooth the line with `smooth_line` or use fewer
    sections through the bend).
    """
    if ni < 2 or nj < 2:
        raise ValueError(f"ni and nj must be at least 2 (got {ni}, {nj})")
    if centerline.is_empty or centerline.length <= 0:
        raise ValueError("centerline is empty")
    w = np.asarray(width, dtype=np.float64)
    if w.ndim == 0:
        w = np.full(ni, float(w))
    if w.shape != (ni,):
        raise ValueError(f"width must be one value or {ni} values (got shape {w.shape})")
    if not (np.isfinite(w).all() and (w > 0).all()):
        raise ValueError("width must be positive")

    length = float(centerline.length)
    s = np.linspace(0.0, length, ni)
    half = 0.5 * length / (ni - 1)

    def at(d: F) -> F:
        pts = [centerline.interpolate(float(v)) for v in np.clip(d, 0.0, length)]
        return np.array([(p.x, p.y) for p in pts], dtype=np.float64)

    centre = at(s)
    t = at(s + half) - at(s - half)
    norm = np.hypot(t[:, 0], t[:, 1])
    if (norm <= 0).any():
        raise ValueError("centerline doubles back on itself at the section spacing")
    t /= norm[:, None]
    left = np.column_stack([-t[:, 1], t[:, 0]])
    frac = np.linspace(-0.5, 0.5, nj)
    xy = centre[:, None, :] + (w[:, None] * frac[None, :])[:, :, None] * left[:, None, :]
    grid = CurviGrid(xy=xy, s=s)
    bad = np.argwhere(grid.cell_areas() <= 0)
    if bad.size:
        i = int(bad[0, 0])
        raise ValueError(
            f"grid folds: {len(bad)} cells with non-positive area, first between sections "
            f"{i} and {i + 1} (chainage {s[i]:.1f}-{s[i + 1]:.1f}); sections cross")
    return grid


def sample_raster(raster: Path | Sequence[Path], x: ArrayLike, y: ArrayLike, *,
                  method: Literal["bilinear", "nearest"] = "bilinear", band: int = 1) -> F:
    """Raster values at points (any shape; CRS coordinates of the raster). NaN outside the
    raster and where a nodata cell is involved. Bilinear interpolates between cell centres and
    holds the edge value within the outer half cell. A sequence of rasters is a stack: each
    point takes the value of the last raster that has one (no resampling of the rasters)."""
    xa = np.asarray(x, dtype=np.float64)
    ya = np.asarray(y, dtype=np.float64)
    if method not in ("bilinear", "nearest"):
        raise ValueError(f"unknown method {method!r}")
    stack = [raster] if isinstance(raster, (str, Path)) else list(raster)
    if not stack:
        raise ValueError("no raster given")
    out = np.full(xa.size, np.nan)
    for one in stack:
        v = _sample_one(Path(one), xa.ravel(), ya.ravel(), method, band)
        out = np.where(np.isfinite(v), v, out)
    return out.reshape(xa.shape)


def _sample_one(raster: Path, xr: F, yr: F, method: str, band: int) -> F:
    with rasterio.open(raster) as ds:
        a = np.asarray(ds.read(band, masked=True).astype("f8").filled(np.nan), dtype=np.float64)
        inv = ~ds.transform
        h, w = ds.height, ds.width
    col = inv.a * xr + inv.b * yr + inv.c
    row = inv.d * xr + inv.e * yr + inv.f
    inside = (col >= 0) & (col <= w) & (row >= 0) & (row <= h)
    out = np.full(col.shape, np.nan)
    if method == "nearest":
        r = np.clip(np.floor(row[inside]).astype(np.int64), 0, h - 1)
        c = np.clip(np.floor(col[inside]).astype(np.int64), 0, w - 1)
        out[inside] = a[r, c]
    else:
        coords = np.vstack([np.clip(row[inside] - 0.5, 0, h - 1),
                            np.clip(col[inside] - 0.5, 0, w - 1)])
        out[inside] = map_coordinates(a, coords, order=1, mode="nearest")
    return out

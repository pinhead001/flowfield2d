"""Velocity vector helpers: compass directions and nearest-vector sampling on raster grids.

Vectors arrive as (x, y) components in CRS axis order (x east, y north for a projected CRS).
`direction_deg` is the compass bearing of the flow (0 = +y, clockwise, degrees), the usual
arrow-rotation field for GIS symbology. `NearestVectors` assigns each pixel the unit direction
of the nearest cell centre so a scalar speed raster can be split into components without
re-rasterising the mesh.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import rasterio.transform
from numpy.typing import NDArray
from rasterio import Affine
from scipy.spatial import cKDTree


def direction_deg(vx: NDArray[Any], vy: NDArray[Any]) -> NDArray[np.float64]:
    """Compass bearing of (vx, vy) in degrees, 0 at +y and 90 at +x, in [0, 360); NaN where the
    vector is NaN or zero."""
    x = np.asarray(vx, dtype=np.float64)
    y = np.asarray(vy, dtype=np.float64)
    with np.errstate(invalid="ignore"):
        bearing = np.mod(90.0 - np.degrees(np.arctan2(y, x)), 360.0)
        still = ~(np.isfinite(x) & np.isfinite(y)) | ((x == 0.0) & (y == 0.0))
    return np.asarray(np.where(still, np.nan, bearing), dtype=np.float64)


class NearestVectors:
    """Unit directions of a point vector field, sampled at the nearest point. Rows with a
    non-finite or zero vector are dropped."""

    def __init__(self, xy: NDArray[Any], uv: NDArray[Any]) -> None:
        p = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
        v = np.asarray(uv, dtype=np.float64).reshape(-1, 2)
        if len(p) != len(v):
            raise ValueError(f"{len(p)} points for {len(v)} vectors")
        speed = np.hypot(v[:, 0], v[:, 1])
        with np.errstate(invalid="ignore"):
            keep = np.isfinite(speed) & (speed > 0) & np.isfinite(p).all(axis=1)
        self.xy = p[keep]
        self.unit = v[keep] / speed[keep, None]
        self._tree = cKDTree(self.xy) if len(self.xy) else None

    @property
    def n(self) -> int:
        return len(self.xy)

    def unit_at(self, x: NDArray[Any], y: NDArray[Any]
                ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Unit direction of the nearest point for each (x, y); NaN without points."""
        xs = np.asarray(x, dtype=np.float64).ravel()
        ys = np.asarray(y, dtype=np.float64).ravel()
        if self._tree is None or xs.size == 0:
            nan = np.full(xs.shape, np.nan)
            return nan, nan.copy()
        _, idx = self._tree.query(np.column_stack([xs, ys]), k=1, workers=-1)
        u = self.unit[idx]
        return u[:, 0].copy(), u[:, 1].copy()

    def window(self, transform: Affine, shape: tuple[int, int], mask: NDArray[Any]
               ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Unit direction per pixel of a (rows, cols) window with `transform`, at the pixels
        where `mask` is True; NaN elsewhere."""
        m = np.asarray(mask, dtype=bool)
        if m.shape != tuple(shape):
            raise ValueError(f"mask shape {m.shape} differs from window shape {tuple(shape)}")
        ux = np.full(m.shape, np.nan)
        uy = np.full(m.shape, np.nan)
        rows, cols = np.nonzero(m)
        if rows.size:
            xs, ys = rasterio.transform.xy(transform, rows, cols, offset="center")
            ux[rows, cols], uy[rows, cols] = self.unit_at(np.asarray(xs), np.asarray(ys))
        return ux, uy

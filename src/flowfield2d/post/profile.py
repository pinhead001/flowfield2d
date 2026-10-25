"""Banded deepest-cell profiles, monitored cells and centerline tracing from 2D results."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray
from shapely.geometry import LineString, Point


@dataclass(frozen=True)
class BandPoint:
    chainage: float
    x: float
    y: float
    depth: float
    wse: float


def band_cells(
    xy: ArrayLike,
    depth: ArrayLike,
    band: float,
    axis: int = 1,
    min_depth: float = 0.5,
) -> NDArray[np.int64]:
    """Index of the deepest cell per band, sorted by band coordinate.

    Cells are binned by coordinate `axis` into bands of width `band`; a band needs at least 2 cells
    deeper than `min_depth`. NaN (dry) depths never count. These are the monitored cells for
    convergence checks and the points of `band_profile`.
    """
    xy_arr = np.asarray(xy, dtype=np.float64)
    depth_arr = np.asarray(depth, dtype=np.float64).ravel()
    if band <= 0:
        raise ValueError("band must be positive")
    if axis not in (0, 1):
        raise ValueError("axis must be 0 or 1")
    if len(xy_arr) == 0:
        return np.empty(0, dtype=np.int64)
    if xy_arr.ndim != 2 or xy_arr.shape[1] < 2:
        raise ValueError("xy must be a 2D array with at least 2 columns")
    if len(xy_arr) != len(depth_arr):
        raise ValueError("xy and depth must have the same length")

    coords = xy_arr[:, axis]
    band_indices = np.floor((coords - float(np.min(coords))) / band).astype(np.int64)
    picked: list[int] = []
    for b in np.unique(band_indices):
        in_band = np.flatnonzero((band_indices == b) & (depth_arr > min_depth))
        if in_band.size >= 2:
            picked.append(int(in_band[np.argmax(depth_arr[in_band])]))
    out = np.array(picked, dtype=np.int64)
    return out[np.argsort(coords[out], kind="stable")]


def band_profile(
    xy: ArrayLike,
    depth: ArrayLike,
    wse: ArrayLike,
    band: float,
    axis: int = 1,
    min_depth: float = 0.5,
) -> list[BandPoint]:
    """Banded deepest-cell profile from 2D results (see `band_cells`)."""
    xy_arr = np.asarray(xy, dtype=np.float64)
    depth_arr = np.asarray(depth, dtype=np.float64).ravel()
    wse_arr = np.asarray(wse, dtype=np.float64).ravel()
    if len(wse_arr) != len(depth_arr):
        raise ValueError("xy, depth, and wse must have the same length")
    idx = band_cells(xy_arr, depth_arr, band, axis, min_depth)
    return [BandPoint(chainage=float(xy_arr[i, axis]), x=float(xy_arr[i, 0]),
                      y=float(xy_arr[i, 1]), depth=float(depth_arr[i]), wse=float(wse_arr[i]))
            for i in idx]


def trace_centerline(
    points: Sequence[BandPoint],
    k: int = 5,
    descending: bool = True,
) -> LineString:
    """Trace centerline from band points smoothed with centered moving average."""
    if not points:
        return LineString()
    if len(points) == 1:
        raise ValueError("At least 2 points are required to form a LineString")
    if k < 1:
        raise ValueError("k must be at least 1")

    sorted_pts = sorted(points, key=lambda p: p.y, reverse=descending)
    n = len(sorted_pts)
    xs = np.array([p.x for p in sorted_pts], dtype=np.float64)
    ys = np.array([p.y for p in sorted_pts], dtype=np.float64)

    h = k // 2
    smooth_x = np.empty(n, dtype=np.float64)
    smooth_y = np.empty(n, dtype=np.float64)
    for i in range(n):
        i0 = max(0, i - h)
        i1 = min(n, i + h + 1)
        smooth_x[i] = float(np.mean(xs[i0:i1]))
        smooth_y[i] = float(np.mean(ys[i0:i1]))

    coords = [(float(x), float(y)) for x, y in zip(smooth_x, smooth_y, strict=True)]
    return LineString(coords)


def profile_along(
    centerline: LineString,
    points: Sequence[BandPoint],
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Project points onto centerline, sort by chainage, and return (chainage, wse)."""
    if not points:
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)

    projected: list[tuple[float, float]] = []
    for p in points:
        ch = float(centerline.project(Point(p.x, p.y)))
        projected.append((ch, p.wse))

    projected.sort(key=lambda item: item[0])
    chainages: NDArray[np.float64] = np.array([item[0] for item in projected], dtype=np.float64)
    wses: NDArray[np.float64] = np.array([item[1] for item in projected], dtype=np.float64)
    return chainages, wses

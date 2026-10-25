"""River centerlines and thalwegs from depth rasters, as least-cost paths on a grid, and
profiles sampled along a line. Work at the raster's resolution; callers pass a raster at a
working resolution.
"""

from __future__ import annotations

import heapq
import math
from pathlib import Path

import numpy as np
import rasterio
import shapely
from numpy.typing import ArrayLike, NDArray
from rasterio.transform import Affine
from scipy.spatial import cKDTree
from shapely.geometry import LineString

F = NDArray[np.float64]

__all__ = [
    "F",
    "centerline",
    "distance_to_edge",
    "least_cost_path",
    "profile_from_cells",
    "sample_raster",
    "thalweg",
]


def distance_to_edge(mask: NDArray[np.bool_], cell: float) -> NDArray[np.float64]:
    """Compute distance in map units to the nearest False cell for True cells.

    Treats everything outside the array boundary as False. False cells have distance 0.
    Uses a two-pass chamfer transform with orthogonal weight 1 and diagonal weight sqrt(2).
    """
    if cell <= 0.0:
        raise ValueError("cell must be positive")
    if mask.ndim != 2:
        raise ValueError("mask must be a 2D array")

    h, w = mask.shape
    if h == 0 or w == 0:
        return np.empty((h, w), dtype=np.float64)

    padded = np.zeros((h + 2, w + 2), dtype=np.float64)
    padded[1 : h + 1, 1 : w + 1] = np.where(mask, np.inf, 0.0)

    sqrt2 = math.sqrt(2.0)

    for r in range(1, h + 1):
        m_row = mask[r - 1]
        if not np.any(m_row):
            continue
        p_row = padded[r]
        p_prev = padded[r - 1]

        v_above = np.minimum(
            p_prev[1 : w + 1] + 1.0,
            np.minimum(p_prev[0:w] + sqrt2, p_prev[2 : w + 2] + sqrt2),
        )
        p_row[1 : w + 1] = np.where(m_row, np.minimum(p_row[1 : w + 1], v_above), 0.0)

        for c in range(1, w + 1):
            if m_row[c - 1]:
                cand = p_row[c - 1] + 1.0
                if cand < p_row[c]:
                    p_row[c] = cand

    for r in range(h, 0, -1):
        m_row = mask[r - 1]
        if not np.any(m_row):
            continue
        p_row = padded[r]
        p_next = padded[r + 1]

        v_below = np.minimum(
            p_next[1 : w + 1] + 1.0,
            np.minimum(p_next[0:w] + sqrt2, p_next[2 : w + 2] + sqrt2),
        )
        p_row[1 : w + 1] = np.where(m_row, np.minimum(p_row[1 : w + 1], v_below), 0.0)

        for c in range(w, 0, -1):
            if m_row[c - 1]:
                cand = p_row[c + 1] + 1.0
                if cand < p_row[c]:
                    p_row[c] = cand

    out: NDArray[np.float64] = (padded[1 : h + 1, 1 : w + 1] * float(cell)).astype(np.float64)
    out[~mask] = 0.0
    return out


def least_cost_path(
    cost: NDArray[np.float64],
    start: tuple[int, int],
    end: tuple[int, int],
) -> list[tuple[int, int]]:
    """Find least-cost path on an 8-connected grid using Dijkstra's algorithm.

    Moving between neighbours costs the mean of the two cells' costs times the step length
    (1 for orthogonal, sqrt(2) for diagonal).
    """
    if cost.ndim != 2:
        raise ValueError("cost must be a 2D array")

    h, w = cost.shape
    r_s, c_s = start
    r_e, c_e = end

    if not (0 <= r_s < h and 0 <= c_s < w):
        raise ValueError(f"start {start} outside grid of shape {cost.shape}")
    if not (0 <= r_e < h and 0 <= c_e < w):
        raise ValueError(f"end {end} outside grid of shape {cost.shape}")

    if not np.isfinite(cost[r_s, c_s]):
        raise ValueError(f"start cell {start} has non-finite cost")
    if not np.isfinite(cost[r_e, c_e]):
        raise ValueError(f"end cell {end} has non-finite cost")

    if start == end:
        return [start]

    dist = np.full((h, w), np.inf, dtype=np.float64)
    dist[r_s, c_s] = 0.0

    parent_r = np.full((h, w), -1, dtype=np.intp)
    parent_c = np.full((h, w), -1, dtype=np.intp)

    sqrt2 = math.sqrt(2.0)
    nbrs = [
        (-1, -1, sqrt2),
        (-1, 0, 1.0),
        (-1, 1, sqrt2),
        (0, -1, 1.0),
        (0, 1, 1.0),
        (1, -1, sqrt2),
        (1, 0, 1.0),
        (1, 1, sqrt2),
    ]

    pq: list[tuple[float, int, int]] = [(0.0, r_s, c_s)]

    while pq:
        d, r, c = heapq.heappop(pq)
        if r == r_e and c == c_e:
            break
        if d > dist[r, c]:
            continue

        c_u = cost[r, c]
        for dr, dc, step_len in nbrs:
            nr = r + dr
            nc = c + dc
            if 0 <= nr < h and 0 <= nc < w:
                c_v = cost[nr, nc]
                if not np.isfinite(c_v):
                    continue
                step_cost = 0.5 * (c_u + c_v) * step_len
                new_d = d + step_cost
                if new_d < dist[nr, nc]:
                    dist[nr, nc] = new_d
                    parent_r[nr, nc] = r
                    parent_c[nr, nc] = c
                    heapq.heappush(pq, (new_d, nr, nc))

    if not np.isfinite(dist[r_e, c_e]):
        raise ValueError(f"No path exists between {start} and {end}")

    path: list[tuple[int, int]] = []
    curr_r, curr_c = r_e, c_e
    while True:
        path.append((curr_r, curr_c))
        if curr_r == r_s and curr_c == c_s:
            break
        pr = parent_r[curr_r, curr_c]
        pc = parent_c[curr_r, curr_c]
        if pr == -1 or pc == -1:
            raise ValueError(f"No path exists between {start} and {end}")
        curr_r, curr_c = int(pr), int(pc)

    path.reverse()
    return path


def _smooth_coords(coords: list[tuple[float, float]], smooth: int) -> list[tuple[float, float]]:
    n = len(coords)
    if smooth <= 1 or n <= 2:
        return coords

    xs = np.array([c[0] for c in coords], dtype=np.float64)
    ys = np.array([c[1] for c in coords], dtype=np.float64)

    h = smooth // 2
    smooth_x = np.empty(n, dtype=np.float64)
    smooth_y = np.empty(n, dtype=np.float64)

    smooth_x[0] = xs[0]
    smooth_y[0] = ys[0]
    smooth_x[-1] = xs[-1]
    smooth_y[-1] = ys[-1]

    for i in range(1, n - 1):
        i0 = max(0, i - h)
        i1 = min(n, i + h + 1)
        smooth_x[i] = float(np.mean(xs[i0:i1]))
        smooth_y[i] = float(np.mean(ys[i0:i1]))

    return [(float(x), float(y)) for x, y in zip(smooth_x, smooth_y, strict=True)]


def _simplify_line(line: LineString, max_vertices: int | None, cell: float) -> LineString:
    """Douglas-Peucker with a doubling tolerance until <= max_vertices; both ends are kept."""
    if max_vertices is None or len(line.coords) <= max_vertices:
        return line
    if max_vertices < 2:
        raise ValueError(f"max_vertices must be at least 2, got {max_vertices}")
    tol = max(0.01 * cell, 1e-9)
    for _ in range(200):                       # 2**200 x the start: always reaches 2 vertices
        cand = line.simplify(tol, preserve_topology=False)
        if isinstance(cand, LineString) and len(cand.coords) <= max_vertices:
            return cand
        tol *= 2.0
    return LineString([line.coords[0], line.coords[-1]])


def _snap_to_mask(
    mask: NDArray[np.bool_],
    transform: Affine,
    pt_xy: tuple[float, float],
) -> tuple[int, int]:
    rows, cols = np.nonzero(mask)
    if len(rows) == 0:
        raise ValueError("Mask contains no True cells")

    col_f = cols.astype(np.float64) + 0.5
    row_f = rows.astype(np.float64) + 0.5
    xs_arr = transform.c + col_f * transform.a + row_f * transform.b
    ys_arr = transform.f + col_f * transform.d + row_f * transform.e

    dx = xs_arr - pt_xy[0]
    dy = ys_arr - pt_xy[1]
    dist_sq = dx * dx + dy * dy
    best_idx = int(np.argmin(dist_sq))
    return int(rows[best_idx]), int(cols[best_idx])


def _build_linestring(
    path: list[tuple[int, int]],
    transform: Affine,
    smooth: int,
    max_vertices: int | None,
    cell: float,
) -> LineString:
    if len(path) == 1:
        col_f = float(path[0][1]) + 0.5
        row_f = float(path[0][0]) + 0.5
        x = transform.c + col_f * transform.a + row_f * transform.b
        y = transform.f + col_f * transform.d + row_f * transform.e
        return LineString([(float(x), float(y)), (float(x), float(y))])

    path_r = [p[0] for p in path]
    path_c = [p[1] for p in path]

    col_f_arr = np.asarray(path_c, dtype=np.float64) + 0.5
    row_f_arr = np.asarray(path_r, dtype=np.float64) + 0.5
    px = transform.c + col_f_arr * transform.a + row_f_arr * transform.b
    py = transform.f + col_f_arr * transform.d + row_f_arr * transform.e
    coords = [(float(x), float(y)) for x, y in zip(px, py, strict=True)]

    smoothed_coords = _smooth_coords(coords, smooth)
    line = LineString(smoothed_coords)
    return _simplify_line(line, max_vertices, cell)


def centerline(
    mask: NDArray[np.bool_],
    transform: Affine,
    start_xy: tuple[float, float],
    end_xy: tuple[float, float],
    *,
    power: float = 2.0,
    smooth: int = 5,
    max_vertices: int | None = None,
) -> LineString:
    """Compute river centerline through True cells of mask."""
    cell = float(abs(transform.a))
    start_cell = _snap_to_mask(mask, transform, start_xy)
    end_cell = _snap_to_mask(mask, transform, end_xy)

    d = distance_to_edge(mask, cell)
    cost = np.full(mask.shape, np.inf, dtype=np.float64)
    cost[mask] = 1.0 / (d[mask] + cell / 2.0) ** power

    path = least_cost_path(cost, start_cell, end_cell)
    return _build_linestring(path, transform, smooth, max_vertices, cell)


def thalweg(
    depth: ArrayLike,
    transform: Affine,
    start_xy: tuple[float, float],
    end_xy: tuple[float, float],
    *,
    power: float = 2.0,
    smooth: int = 3,
    max_vertices: int | None = None,
) -> LineString:
    """Compute thalweg through wet cells (depth > 0) following deepest path."""
    cell = float(abs(transform.a))
    depth_arr: NDArray[np.float64] = np.asarray(depth, dtype=np.float64)
    wet = np.isfinite(depth_arr) & (depth_arr > 0.0)

    start_cell = _snap_to_mask(wet, transform, start_xy)
    end_cell = _snap_to_mask(wet, transform, end_xy)

    cost = np.full(depth_arr.shape, np.inf, dtype=np.float64)
    cost[wet] = 1.0 / (depth_arr[wet] + 1e-3) ** power

    path = least_cost_path(cost, start_cell, end_cell)
    return _build_linestring(path, transform, smooth, max_vertices, cell)


def _line_chainages(line: LineString, spacing: float) -> NDArray[np.float64]:
    if spacing <= 0.0:
        raise ValueError("spacing must be positive")
    if line.is_empty:
        return np.empty(0, dtype=np.float64)
    total_len = float(line.length)
    if total_len == 0.0:
        return np.array([0.0], dtype=np.float64)

    n_steps = int(math.floor(total_len / spacing))
    ch_list = [i * spacing for i in range(n_steps + 1)]
    if total_len - ch_list[-1] > 1e-7:
        ch_list.append(total_len)
    else:
        ch_list[-1] = total_len
    return np.array(ch_list, dtype=np.float64)


def sample_raster(
    raster: Path,
    line: LineString,
    spacing: float,
) -> tuple[F, F]:
    """Sample raster along line at uniform spacing, always including line length exactly."""
    ch_arr = _line_chainages(line, spacing)
    if len(ch_arr) == 0:
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)

    pts = [line.interpolate(float(d)) for d in ch_arr]
    coords = [(float(pt.x), float(pt.y)) for pt in pts]

    vals = np.full(len(coords), np.nan, dtype=np.float64)
    with rasterio.open(raster) as ds:
        nodata = ds.nodata
        samples = list(ds.sample(coords, indexes=1))
        for i, (pt, s) in enumerate(zip(coords, samples, strict=True)):
            x, y = pt
            r, c = ds.index(x, y)
            if 0 <= r < ds.height and 0 <= c < ds.width:
                val = float(s[0])
                if nodata is not None:
                    if np.isnan(nodata):
                        if not np.isnan(val):
                            vals[i] = val
                    elif val != nodata:
                        vals[i] = val
                else:
                    vals[i] = val

    return ch_arr, vals


def profile_from_cells(
    line: LineString,
    cell_xy: ArrayLike,
    values: ArrayLike,
    spacing: float,
    max_distance: float,
) -> tuple[F, F]:
    """Sample nearest cell values along line within max_distance."""
    if max_distance < 0.0:
        raise ValueError("max_distance must be non-negative")

    ch_arr = _line_chainages(line, spacing)
    v_arr = np.full(len(ch_arr), np.nan, dtype=np.float64)

    cells = np.asarray(cell_xy, dtype=np.float64)
    vals = np.asarray(values, dtype=np.float64).ravel()

    if cells.ndim != 2 or cells.shape[1] != 2:
        raise ValueError("cell_xy must be a 2D array of shape (N, 2)")
    if len(cells) != len(vals):
        raise ValueError("cell_xy and values must have the same length")

    if len(cells) == 0 or len(ch_arr) == 0:
        return ch_arr, v_arr

    q = shapely.get_coordinates(shapely.line_interpolate_point(line, ch_arr))
    ok = np.isfinite(cells).all(axis=1)
    if not ok.any():
        return ch_arr, v_arr
    dist, idx = cKDTree(cells[ok]).query(q, distance_upper_bound=max_distance)
    hit = np.isfinite(dist)
    v_arr[hit] = vals[ok][idx[hit]]
    return ch_arr, v_arr

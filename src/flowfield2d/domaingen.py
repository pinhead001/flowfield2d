"""Automated 2D-domain outlines with few vertices, so a person can still edit them: the data
footprint of a DEM, and the envelope of ground within a freeboard of a coarse
max-flow model's water surface.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import rasterio.features
import rasterio.fill
from numpy.typing import ArrayLike, NDArray
from rasterio.transform import rowcol
from shapely import make_valid, unary_union
from shapely.geometry import MultiPoint, MultiPolygon, Point, Polygon, shape

__all__ = ["data_footprint", "flood_envelope", "simplify_to"]


def _vertex_count(poly: Polygon) -> int:
    """Number of vertices on exterior boundary, excluding the closing point."""
    return len(poly.exterior.coords) - 1


def _largest_polygon(geom: Any) -> Polygon:
    """Extract the largest valid polygon from a geometry."""
    if isinstance(geom, Polygon):
        if not geom.is_valid:
            geom = make_valid(geom)
            return _largest_polygon(geom)
        if geom.is_empty:
            raise ValueError("Polygon is empty")
        return geom
    if hasattr(geom, "geoms"):
        polys: list[Polygon] = []
        for g in geom.geoms:
            if isinstance(g, Polygon) and not g.is_empty:
                polys.append(g)
            elif isinstance(g, MultiPolygon):
                for sub_p in g.geoms:
                    if isinstance(sub_p, Polygon) and not sub_p.is_empty:
                        polys.append(sub_p)
        if polys:
            return max(polys, key=lambda p: float(p.area))
    raise ValueError(f"Geometry contains no valid polygons: {geom}")


def _drop_holes(poly: Polygon) -> Polygon:
    """Return a polygon with all interior rings dropped."""
    if len(poly.interiors) == 0:
        return poly
    p = Polygon(poly.exterior.coords)
    if not p.is_valid:
        p = _largest_polygon(make_valid(p))
    return p


def _find_tolerance(geom: Polygon, max_vertices: int) -> tuple[Polygon, float]:
    """Find Douglas-Peucker tolerance keeping as much detail as fits <= max_vertices."""
    minx, miny, maxx, maxy = geom.bounds
    diag = math.hypot(maxx - minx, maxy - miny)
    if diag <= 0.0:
        return geom, 0.0
    tol = 0.001 * diag
    cand = _drop_holes(_largest_polygon(geom.simplify(tol, preserve_topology=True)))
    if _vertex_count(cand) <= max_vertices:
        low = 0.0
        high = tol
        best = cand
    else:
        low = tol
        high = tol * 2.0
        while True:
            cand = _drop_holes(_largest_polygon(geom.simplify(high, preserve_topology=True)))
            if _vertex_count(cand) <= max_vertices:
                best = cand
                break
            low = high
            high *= 2.0
            if high > 1e6 * diag:
                best = cand
                break

    for _ in range(16):
        mid = (low + high) / 2.0
        cand = _drop_holes(_largest_polygon(geom.simplify(mid, preserve_topology=True)))
        if _vertex_count(cand) <= max_vertices:
            high = mid
            best = cand
        else:
            low = mid

    return best, high


def simplify_to(poly: Polygon, max_vertices: int, *, cover: bool = False) -> Polygon:
    """Simplify polygon exterior to at most max_vertices using Douglas-Peucker.

    Parameters
    ----------
    poly:
        Input polygon.
    max_vertices:
        Maximum allowed vertices on the exterior boundary (closing point not counted).
    cover:
        If True, buffer by tolerance before simplifying so the result contains the input.

    Returns
    -------
    Polygon
        Valid, non-empty simplified polygon with holes dropped.
    """
    if max_vertices < 3:
        raise ValueError(f"max_vertices must be at least 3, got {max_vertices}")

    if _vertex_count(poly) <= max_vertices:
        return poly

    poly_clean = _drop_holes(_largest_polygon(poly))
    best, final_tol = _find_tolerance(poly_clean, max_vertices)

    if not cover:
        return best

    buf_dist = final_tol
    res = best
    for _ in range(5):
        buffered = poly_clean.buffer(buf_dist, join_style="mitre")
        buffered_clean = _drop_holes(_largest_polygon(buffered))
        if _vertex_count(buffered_clean) <= max_vertices:
            res = buffered_clean
            tol_buf = 0.0
        else:
            res, tol_buf = _find_tolerance(buffered_clean, max_vertices)
        if res.buffer(1e-6).contains(poly):
            return res
        buf_dist = max(buf_dist * 1.1, tol_buf * 1.05)

    return res


def data_footprint(dem: Path, *, max_vertices: int = 200) -> Polygon:
    """Compute the simplified valid-data footprint polygon of a DEM raster.

    Parameters
    ----------
    dem:
        Path to the DEM raster file.
    max_vertices:
        Maximum vertices on the exterior boundary of the footprint.

    Returns
    -------
    Polygon
        Simplified valid-data footprint polygon with holes dropped.
    """
    with rasterio.open(dem) as ds:
        data = ds.read(1)
        valid: NDArray[np.bool_] = np.isfinite(data)
        if ds.nodata is not None and not np.isnan(ds.nodata):
            valid &= (data != ds.nodata)
        if not valid.any():
            raise ValueError(f"No valid data cells found in {dem}")

        mask_u8 = valid.astype(np.uint8)
        shapes_gen = rasterio.features.shapes(
            mask_u8,
            mask=valid,
            transform=ds.transform,
        )
        polys: list[Polygon] = []
        for geom_dict, _ in shapes_gen:
            geom = shape(geom_dict)
            if geom.is_empty:
                continue
            if not geom.is_valid:
                geom = make_valid(geom)
            if isinstance(geom, Polygon):
                polys.append(geom)
            elif isinstance(geom, MultiPolygon):
                for sub_p in geom.geoms:
                    if isinstance(sub_p, Polygon) and not sub_p.is_empty:
                        polys.append(sub_p)

        if not polys:
            raise ValueError(f"No polygons generated from valid data mask in {dem}")

        largest = max(polys, key=lambda p: float(p.area))
        largest_no_holes = _drop_holes(largest)
        return simplify_to(largest_no_holes, max_vertices)


def flood_envelope(
    dem: Path,
    cell_xy: ArrayLike,
    cell_wse: ArrayLike,
    freeboard: float,
    *,
    buffer: float = 0.0,
    clip: Polygon | None = None,
    max_vertices: int = 50,
) -> Polygon:
    """Compute simplified flood envelope polygon from DEM and coarse wet cell WSE.

    Parameters
    ----------
    dem:
        Path to the DEM raster.
    cell_xy:
        Array-like of wet cell (x, y) coordinates.
    cell_wse:
        Array-like of wet cell water surface elevations.
    freeboard:
        Additional elevation added to the water surface envelope.
    buffer:
        Buffer distance in map units applied to the flooded polygon.
    clip:
        Optional polygon boundary to clip the envelope to.
    max_vertices:
        Maximum vertices on the exterior boundary of the envelope.

    Returns
    -------
    Polygon
        Simplified flood envelope polygon.
    """
    xy = np.asarray(cell_xy, dtype=np.float64)
    wse = np.asarray(cell_wse, dtype=np.float64)

    if xy.ndim != 2 or xy.shape[1] != 2:
        raise ValueError("cell_xy must be a 2D array of shape (N, 2)")
    if wse.ndim != 1 or xy.shape[0] != wse.shape[0]:
        raise ValueError("cell_wse must be a 1D array with same length as cell_xy")

    finite_mask = np.isfinite(wse) & np.isfinite(xy[:, 0]) & np.isfinite(xy[:, 1])
    if not finite_mask.any():
        raise ValueError("No wet cells with finite WSE values provided")

    xy_wet = xy[finite_mask]
    wse_wet = wse[finite_mask]

    with rasterio.open(dem) as ds:
        z = ds.read(1)
        valid: NDArray[np.bool_] = np.isfinite(z)
        if ds.nodata is not None and not np.isnan(ds.nodata):
            valid &= (z != ds.nodata)

        rows_raw, cols_raw = rowcol(ds.transform, xy_wet[:, 0], xy_wet[:, 1])
        rows: NDArray[np.intp] = np.asarray(rows_raw, dtype=np.intp)
        cols: NDArray[np.intp] = np.asarray(cols_raw, dtype=np.intp)

        in_bounds = (rows >= 0) & (rows < ds.height) & (cols >= 0) & (cols < ds.width)
        if not in_bounds.any():
            raise ValueError("No wet cells fall within DEM bounds")

        rows_in = rows[in_bounds]
        cols_in = cols[in_bounds]
        wse_in = wse_wet[in_bounds]

        wse_grid: NDArray[np.float32] = np.full(
            (ds.height, ds.width), -np.inf, dtype=np.float32
        )
        np.maximum.at(wse_grid, (rows_in, cols_in), wse_in.astype(np.float32))

        hit_mask = ~np.isneginf(wse_grid)
        fill_mask = hit_mask.astype(np.uint8)
        wse_grid[~hit_mask] = 0.0

        diag_pixels = float(math.hypot(ds.height, ds.width) * 2.0)
        wse_ext = rasterio.fill.fillnodata(
            wse_grid,
            mask=fill_mask,
            max_search_distance=diag_pixels,
        )

        flood_mask: NDArray[np.bool_] = valid & (z <= (wse_ext + float(freeboard)))
        if not flood_mask.any():
            raise ValueError("No flood area found matching wet cells and freeboard")

        mask_u8 = flood_mask.astype(np.uint8)
        shapes_gen = rasterio.features.shapes(
            mask_u8,
            mask=flood_mask,
            transform=ds.transform,
        )

        polys: list[Polygon] = []
        for geom_dict, _ in shapes_gen:
            geom = shape(geom_dict)
            if geom.is_empty:
                continue
            if not geom.is_valid:
                geom = make_valid(geom)
            if isinstance(geom, Polygon):
                polys.append(geom)
            elif isinstance(geom, MultiPolygon):
                for sub_p in geom.geoms:
                    if isinstance(sub_p, Polygon) and not sub_p.is_empty:
                        polys.append(sub_p)

        wet_pts = MultiPoint([Point(float(p[0]), float(p[1])) for p in xy_wet])
        kept = [
            p
            for p in polys
            if p.intersects(wet_pts) or p.buffer(1e-5).intersects(wet_pts)
        ]
        if not kept:
            raise ValueError("No flood polygons intersect wet cells")

        if len(kept) == 1:
            union_poly = kept[0]
        else:
            union_poly = unary_union(kept)

        main_poly = _drop_holes(_largest_polygon(union_poly))

        if buffer > 0.0:
            main_poly = _drop_holes(_largest_polygon(main_poly.buffer(buffer)))

        if clip is not None:
            inter = main_poly.intersection(clip)
            main_poly = _drop_holes(_largest_polygon(inter))

        simplified = simplify_to(main_poly, max_vertices, cover=True)

        if clip is not None:
            inter2 = simplified.intersection(clip)
            simplified = _drop_holes(_largest_polygon(inter2))

        return simplified

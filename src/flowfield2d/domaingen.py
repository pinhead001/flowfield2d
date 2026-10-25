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
import scipy.ndimage
import shapely
from numpy.typing import ArrayLike, NDArray
from rasterio.enums import Resampling
from rasterio.transform import Affine, rowcol
from shapely import make_valid, unary_union
from shapely.geometry import LineString, MultiPoint, MultiPolygon, Point, Polygon, shape
from shapely.ops import split
from shapely.prepared import prep

__all__ = [
    "cut_between",
    "data_footprint",
    "fit_inside",
    "flood_envelope",
    "simplify_to",
    "valid_area",
]


def _vertex_count(poly: Polygon) -> int:
    """Number of vertices on exterior boundary, excluding the closing point."""
    return len(poly.exterior.coords) - 1


def _extract_polygons(geom: Any) -> list[Polygon]:
    """Recursively collect non-empty Polygons from a geometry using get_parts."""
    polys: list[Polygon] = []
    parts: NDArray[Any] = shapely.get_parts(geom)
    for part in parts:
        if isinstance(part, Polygon):
            if not part.is_empty:
                polys.append(part)
        elif hasattr(part, "geoms"):
            polys.extend(_extract_polygons(part))
    return polys


def _largest_polygon(geom: Any) -> Polygon:
    """Extract the largest valid polygon from a geometry."""
    if not geom.is_valid:
        geom = make_valid(geom)
    polys = _extract_polygons(geom)
    if polys:
        return max(polys, key=lambda p: float(p.area))
    raise ValueError(f"Geometry contains no valid polygons: {geom}")


def _extract_linestrings(geom: Any) -> list[LineString]:
    """Recursively collect non-empty LineStrings from a geometry using get_parts."""
    lines: list[LineString] = []
    parts: NDArray[Any] = shapely.get_parts(geom)
    for part in parts:
        if isinstance(part, LineString):
            if not part.is_empty:
                lines.append(part)
        elif hasattr(part, "geoms"):
            lines.extend(_extract_linestrings(part))
    return lines


def _extend_line(line: LineString, total_length: float) -> LineString:
    """Extend line through its midpoint along its direction to total_length."""
    coords: list[tuple[float, ...]] = list(line.coords)
    if len(coords) < 2:
        raise ValueError("LineString must have at least 2 points")
    x0, y0 = coords[0][0], coords[0][1]
    x1, y1 = coords[-1][0], coords[-1][1]
    dx = x1 - x0
    dy = y1 - y0
    orig_len = math.hypot(dx, dy)
    if orig_len <= 0.0:
        raise ValueError("LineString endpoints must not be identical")
    ux = dx / orig_len
    uy = dy / orig_len
    mid = line.interpolate(0.5, normalized=True)
    mx = float(mid.x)
    my = float(mid.y)
    half = total_length / 2.0
    p0 = (mx - ux * half, my - uy * half)
    p1 = (mx + ux * half, my + uy * half)
    return LineString([p0, p1])


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
            cand = _drop_holes(
                _largest_polygon(geom.simplify(high, preserve_topology=True))
            )
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
        cand = _drop_holes(
            _largest_polygon(geom.simplify(mid, preserve_topology=True))
        )
        if _vertex_count(cand) <= max_vertices:
            high = mid
            best = cand
        else:
            low = mid

    return best, high


def simplify_to(
    poly: Polygon,
    max_vertices: int,
    *,
    cover: bool = False,
) -> Polygon:
    """Simplify polygon exterior to at most max_vertices using Douglas-Peucker.

    Parameters
    ----------
    poly:
        Input polygon.
    max_vertices:
        Maximum allowed vertices on the exterior boundary (closing point not counted).
    cover:
        If True, buffer by tolerance before simplifying so the result covers the input.

    Returns
    -------
    Polygon
        Valid, non-empty simplified polygon with holes dropped.
    """
    if max_vertices < 3:
        raise ValueError(f"max_vertices must be at least 3, got {max_vertices}")

    poly_clean = _drop_holes(_largest_polygon(poly))

    if _vertex_count(poly_clean) <= max_vertices:
        if not cover or poly_clean.covers(poly):
            return poly_clean

    best, final_tol = _find_tolerance(poly_clean, max_vertices)

    if not cover:
        return best

    minx, miny, maxx, maxy = poly_clean.bounds
    diag = math.hypot(maxx - minx, maxy - miny)
    buf_dist = max(final_tol, 0.001 * diag) if diag > 0.0 else 1.0
    if buf_dist <= 0.0:
        buf_dist = 1.0

    hard_cap = 1e6 * (diag if diag > 0.0 else 1.0)
    for _ in range(50):
        if buf_dist > hard_cap:
            break
        buffered = poly_clean.buffer(buf_dist)
        buffered_clean = _drop_holes(_largest_polygon(buffered))
        if _vertex_count(buffered_clean) <= max_vertices:
            cand = buffered_clean
        else:
            cand, _ = _find_tolerance(buffered_clean, max_vertices)
        if _vertex_count(cand) <= max_vertices and cand.covers(poly):
            return cand
        buf_dist *= 2.0

    raise ValueError(
        f"Could not simplify polygon to {max_vertices} vertices while covering input"
    )


def _mask_polygons(mask: NDArray[np.bool_], transform: Affine) -> list[Polygon]:
    """Extract valid Polygon geometries from a boolean raster mask."""
    if not mask.any():
        return []
    mask_u8 = mask.astype(np.uint8)
    shapes_gen = rasterio.features.shapes(
        mask_u8,
        mask=mask,
        transform=transform,
    )
    polys: list[Polygon] = []
    for geom_dict, val in shapes_gen:
        if val != 1:
            continue
        geom = shape(geom_dict)
        if geom.is_empty:
            continue
        if not geom.is_valid:
            geom = make_valid(geom)
        polys.extend(_extract_polygons(geom))
    return polys


def data_footprint(
    dem: Path,
    *,
    max_vertices: int = 200,
    resolution: float | None = None,
) -> Polygon:
    """Compute the simplified valid-data footprint polygon of a DEM raster.

    Parameters
    ----------
    dem:
        Path to the DEM raster file.
    max_vertices:
        Maximum vertices on the exterior boundary of the footprint.
    resolution:
        Optional working resolution in map units. If None, native resolution is used.

    Returns
    -------
    Polygon
        Simplified valid-data footprint polygon with holes dropped.
    """
    with rasterio.open(dem) as ds:
        if resolution is not None:
            out_h = max(1, int(round(ds.height * ds.res[1] / resolution)))
            out_w = max(1, int(round(ds.width * ds.res[0] / resolution)))
            out_shape: tuple[int, int] | None = (out_h, out_w)
            scale_x = ds.width / out_w
            scale_y = ds.height / out_h
            transform = ds.transform @ Affine.scale(scale_x, scale_y)
            data = ds.read(
                1,
                out_shape=out_shape,
                masked=True,
                resampling=Resampling.nearest,
            )
        else:
            transform = ds.transform
            data = ds.read(1, masked=True)

        valid: NDArray[np.bool_] = (
            ~np.ma.getmaskarray(data)
        ) & np.isfinite(np.ma.getdata(data))
        del data

        if not valid.any():
            raise ValueError(f"No valid data cells found in {dem}")

        polys = _mask_polygons(valid, transform)
        del valid

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
    resolution: float | None = None,
    margin: float | None = None,
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
    resolution:
        Optional working resolution in map units. If None, native resolution is used.
    margin:
        Margin in map units around wet cell bounds to read. Defaults to 2000.

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

    margin_val = 2000.0 if margin is None else float(margin)
    min_x = float(np.min(xy_wet[:, 0])) - margin_val
    max_x = float(np.max(xy_wet[:, 0])) + margin_val
    min_y = float(np.min(xy_wet[:, 1])) - margin_val
    max_y = float(np.max(xy_wet[:, 1])) + margin_val

    with rasterio.open(dem) as ds:
        clamped_left = max(min_x, ds.bounds.left)
        clamped_bottom = max(min_y, ds.bounds.bottom)
        clamped_right = min(max_x, ds.bounds.right)
        clamped_top = min(max_y, ds.bounds.top)

        if clamped_left >= clamped_right or clamped_bottom >= clamped_top:
            raise ValueError("No wet cells fall within DEM bounds")

        raw_window = rasterio.windows.from_bounds(
            clamped_left,
            clamped_bottom,
            clamped_right,
            clamped_top,
            transform=ds.transform,
        )
        col_off = max(0, math.floor(raw_window.col_off))
        row_off = max(0, math.floor(raw_window.row_off))
        end_col = min(ds.width, math.ceil(raw_window.col_off + raw_window.width))
        end_row = min(ds.height, math.ceil(raw_window.row_off + raw_window.height))
        win_w = end_col - col_off
        win_h = end_row - row_off
        if win_w <= 0 or win_h <= 0:
            raise ValueError("No wet cells fall within DEM bounds")

        window = rasterio.windows.Window(col_off, row_off, win_w, win_h)
        win_transform = rasterio.windows.transform(window, ds.transform)

        raw_z = ds.read(1, window=window, masked=True)

        if resolution is not None:
            map_w = win_w * ds.res[0]
            map_h = win_h * ds.res[1]
            out_w = min(win_w, max(1, int(round(map_w / resolution))))
            out_h = min(win_h, max(1, int(round(map_h / resolution))))
            if out_w < win_w or out_h < win_h:
                scaled_transform = win_transform @ Affine.scale(
                    win_w / out_w, win_h / out_h
                )
                z_data = np.ma.getdata(raw_z).astype(np.float32)
                z_mask = np.ma.getmaskarray(raw_z) | ~np.isfinite(z_data)
                z_vals: NDArray[np.float32] = np.where(
                    ~z_mask, z_data, np.float32(np.inf)
                )
                del raw_z, z_data, z_mask

                row_splits = np.floor(
                    np.linspace(0, win_h, out_h, endpoint=False)
                ).astype(np.intp)
                col_splits = np.floor(
                    np.linspace(0, win_w, out_w, endpoint=False)
                ).astype(np.intp)

                temp: NDArray[np.float32] = np.minimum.reduceat(
                    z_vals, row_splits, axis=0
                )
                del z_vals
                out_vals: NDArray[np.float32] = np.minimum.reduceat(
                    temp, col_splits, axis=1
                )
                del temp

                out_mask: NDArray[np.bool_] = np.isinf(out_vals) | np.isnan(out_vals)
                out_clean = np.where(~out_mask, out_vals, np.float32(-9999.0))
                z_masked = np.ma.masked_array(out_clean, mask=out_mask)
                del out_vals, out_mask, out_clean
            else:
                scaled_transform = win_transform
                z_masked = raw_z
        else:
            scaled_transform = win_transform
            z_masked = raw_z

        grid_h, grid_w = z_masked.shape
        valid: NDArray[np.bool_] = (
            ~np.ma.getmaskarray(z_masked)
        ) & np.isfinite(np.ma.getdata(z_masked))
        z: NDArray[np.float32] = np.ma.getdata(z_masked).astype(np.float32)
        del z_masked

        rows_raw, cols_raw = rowcol(scaled_transform, xy_wet[:, 0], xy_wet[:, 1])
        rows: NDArray[np.intp] = np.asarray(rows_raw, dtype=np.intp)
        cols: NDArray[np.intp] = np.asarray(cols_raw, dtype=np.intp)

        in_bounds = (rows >= 0) & (rows < grid_h) & (cols >= 0) & (cols < grid_w)
        if not in_bounds.any():
            raise ValueError("No wet cells fall within DEM bounds")

        rows_in = rows[in_bounds]
        cols_in = cols[in_bounds]
        wse_in = wse_wet[in_bounds]

        wse_grid: NDArray[np.float32] = np.full(
            (grid_h, grid_w), -np.inf, dtype=np.float32
        )
        np.maximum.at(wse_grid, (rows_in, cols_in), wse_in.astype(np.float32))

        hit_mask = ~np.isneginf(wse_grid)
        fill_mask = hit_mask.astype(np.uint8)
        wse_grid[~hit_mask] = 0.0

        diag_pixels = float(math.hypot(grid_h, grid_w))
        wse_ext = rasterio.fill.fillnodata(
            wse_grid,
            mask=fill_mask,
            max_search_distance=diag_pixels,
        )
        del wse_grid, fill_mask

        flood_mask: NDArray[np.bool_] = valid & (z <= (wse_ext + float(freeboard)))
        del z, wse_ext, valid

        if not flood_mask.any():
            raise ValueError("No flood area found matching wet cells and freeboard")

        polys = _mask_polygons(flood_mask, scaled_transform)
        del flood_mask

        if not polys:
            raise ValueError("No flood polygons intersect wet cells")

        hit_rows, hit_cols = np.nonzero(hit_mask)
        hit_xs, hit_ys = rasterio.transform.xy(
            scaled_transform, hit_rows, hit_cols, offset="center"
        )
        del hit_mask

        hit_pts = MultiPoint(shapely.points(np.column_stack([hit_xs, hit_ys])))
        prep_hits = prep(hit_pts)
        kept = [p for p in polys if prep_hits.intersects(p)]

        if not kept:
            raise ValueError("No flood polygons intersect wet cells")

        if len(kept) == 1:
            union_poly = kept[0]
        else:
            union_poly = unary_union(kept)

        main_poly = _drop_holes(_largest_polygon(union_poly))

        one_pixel = max(abs(scaled_transform.a), abs(scaled_transform.e))
        main_poly = _drop_holes(
            _largest_polygon(main_poly.simplify(one_pixel, preserve_topology=True))
        )

        if buffer > 0.0:
            main_poly = _drop_holes(_largest_polygon(main_poly.buffer(buffer)))

        if clip is not None:
            main_poly = _drop_holes(_largest_polygon(main_poly.intersection(clip)))

        simplified = simplify_to(main_poly, max_vertices, cover=True)

        if clip is not None:
            simplified = _drop_holes(_largest_polygon(simplified.intersection(clip)))
            # A clipped outline can follow the clip boundary, which may introduce extra
            # vertices. If vertex count exceeds max_vertices, simplify again without cover
            # and clip once more.
            if _vertex_count(simplified) > max_vertices:
                simplified = simplify_to(simplified, max_vertices, cover=False)
                simplified = _drop_holes(
                    _largest_polygon(simplified.intersection(clip))
                )

        return simplified


def valid_area(
    dem: Path,
    *,
    bounds: tuple[float, float, float, float] | None = None,
    erode: float = 0.0,
    resolution: float | None = None,
) -> Polygon | MultiPolygon:
    """Compute the valid-data footprint polygon(s) of a DEM raster.

    Parameters
    ----------
    dem:
        Path to the DEM raster file.
    bounds:
        Optional (minx, miny, maxx, maxy) bounding box to read. If None, reads whole raster.
        Rounded outward to whole pixels and clipped to raster bounds.
    erode:
        Distance in map units to erode the valid area mask.
    resolution:
        Optional working resolution in map units. If None, native resolution is used.

    Returns
    -------
    Polygon | MultiPolygon
        Valid data area geometry with interior holes preserved.
    """
    with rasterio.open(dem) as ds:
        if bounds is not None:
            minx, miny, maxx, maxy = bounds
            clamped_left = max(minx, ds.bounds.left)
            clamped_bottom = max(miny, ds.bounds.bottom)
            clamped_right = min(maxx, ds.bounds.right)
            clamped_top = min(maxy, ds.bounds.top)

            if clamped_left >= clamped_right or clamped_bottom >= clamped_top:
                raise ValueError("Bounds do not intersect raster")

            raw_window = rasterio.windows.from_bounds(
                clamped_left,
                clamped_bottom,
                clamped_right,
                clamped_top,
                transform=ds.transform,
            )
            col_off = max(0, math.floor(raw_window.col_off))
            row_off = max(0, math.floor(raw_window.row_off))
            end_col = min(ds.width, math.ceil(raw_window.col_off + raw_window.width))
            end_row = min(ds.height, math.ceil(raw_window.row_off + raw_window.height))
            win_w = end_col - col_off
            win_h = end_row - row_off
            if win_w <= 0 or win_h <= 0:
                raise ValueError("Window has zero area")

            window: rasterio.windows.Window | None = rasterio.windows.Window(
                col_off, row_off, win_w, win_h
            )
            win_transform = rasterio.windows.transform(window, ds.transform)
        else:
            window = None
            win_transform = ds.transform
            win_w = ds.width
            win_h = ds.height

        if resolution is not None:
            out_h = max(1, int(round(win_h * ds.res[1] / resolution)))
            out_w = max(1, int(round(win_w * ds.res[0] / resolution)))
            out_shape: tuple[int, int] | None = (out_h, out_w)
            scale_x = win_w / out_w
            scale_y = win_h / out_h
            transform = win_transform @ Affine.scale(scale_x, scale_y)
            data = ds.read(
                1,
                window=window,
                out_shape=out_shape,
                masked=True,
                resampling=Resampling.nearest,
            )
        else:
            transform = win_transform
            data = ds.read(1, window=window, masked=True)

        valid: NDArray[np.bool_] = (
            ~np.ma.getmaskarray(data)
        ) & np.isfinite(np.ma.getdata(data))
        del data

        if not valid.any():
            raise ValueError(f"No valid data cells found in {dem}")

        if erode > 0.0:
            pixel = max(abs(transform.a), abs(transform.e))
            iterations = math.ceil(erode / pixel)
            if iterations > 0:
                structure = scipy.ndimage.generate_binary_structure(2, 2)
                eroded = scipy.ndimage.binary_erosion(
                    valid,
                    structure=structure,
                    iterations=iterations,
                    border_value=0,
                )
                valid = np.asarray(eroded, dtype=np.bool_)
                if not valid.any():
                    raise ValueError(
                        f"No valid data cells remaining after erosion in {dem}"
                    )

        polys = _mask_polygons(valid, transform)
        del valid

        if not polys:
            raise ValueError(f"No valid polygons generated from {dem}")

        if len(polys) == 1:
            union_poly = polys[0]
        else:
            union_poly = unary_union(polys)

        if not union_poly.is_valid:
            union_poly = make_valid(union_poly)

        if isinstance(union_poly, (Polygon, MultiPolygon)):
            return union_poly

        extracted = _extract_polygons(union_poly)
        if not extracted:
            raise ValueError(f"No valid polygons found in {dem}")
        if len(extracted) == 1:
            return extracted[0]
        return MultiPolygon(extracted)


def fit_inside(
    poly: Polygon,
    valid: Polygon | MultiPolygon,
    *,
    inset: float,
    smooth: float,
) -> Polygon:
    """Fit domain outline inside valid terrain area with smoothing.

    Parameters
    ----------
    poly:
        Input outline polygon.
    valid:
        Valid data area polygon or multipolygon.
    inset:
        Buffer inset distance in map units.
    smooth:
        Simplification tolerance in map units (must satisfy 0 <= smooth < inset).

    Returns
    -------
    Polygon
        Smoothed polygon fitting inside the valid area.
    """
    if smooth < 0.0 or smooth >= inset:
        raise ValueError(
            f"smooth must satisfy 0 <= smooth < inset, got smooth={smooth}, inset={inset}"
        )

    valid_buffered = valid.buffer(-inset)
    if valid_buffered.is_empty:
        raise ValueError("No valid area remaining after applying inset")

    inter = poly.intersection(valid_buffered)
    if inter.is_empty:
        raise ValueError("Intersection of poly with inset valid area is empty")

    largest = _largest_polygon(inter)
    simplified = largest.simplify(smooth, preserve_topology=True)
    buffered = simplified.buffer(0)
    largest_simp = _largest_polygon(buffered)

    # Drop holes only if they are fully inside valid (keep the exterior)
    kept_holes: list[Any] = []
    for ring in largest_simp.interiors:
        hole_poly = Polygon(ring)
        if not (valid.contains(hole_poly) or valid.covers(hole_poly)):
            kept_holes.append(ring)

    if len(kept_holes) == len(largest_simp.interiors):
        res: Polygon = largest_simp
    elif len(kept_holes) == 0:
        res = Polygon(largest_simp.exterior.coords)
    else:
        holes_coords = [list(ring.coords) for ring in kept_holes]
        res = Polygon(largest_simp.exterior.coords, holes_coords)

    if not res.is_valid:
        res = _largest_polygon(make_valid(res))
    return res


def cut_between(
    poly: Polygon,
    line_a: LineString,
    line_b: LineString,
    inside: Point,
    *,
    extend: float | None = None,
) -> tuple[Polygon, LineString, LineString]:
    """Cut polygon between two boundary lines, returning the piece containing inside point.

    Parameters
    ----------
    poly:
        Input polygon to be cut.
    line_a:
        First boundary line string.
    line_b:
        Second boundary line string.
    inside:
        Point that must lie inside the returned polygon piece.
    extend:
        Total length to extend each line through its midpoint along its direction.
        Defaults to 2 x the polygon's bounding-box diagonal.

    Returns
    -------
    tuple[Polygon, LineString, LineString]
        The cut polygon piece, and the exact boundary segments corresponding to line_a and line_b.
    """
    minx, miny, maxx, maxy = poly.bounds
    diag = math.hypot(maxx - minx, maxy - miny)
    total_len = 2.0 * diag if extend is None else float(extend)
    if total_len <= 0.0:
        raise ValueError(f"extend length must be positive, got {total_len}")

    ext_a = _extend_line(line_a, total_len)
    ext_b = _extend_line(line_b, total_len)

    pieces_after_a = _extract_polygons(split(poly, ext_a))
    if not pieces_after_a:
        pieces_after_a = [poly]

    all_pieces: list[Polygon] = []
    for p in pieces_after_a:
        sub = _extract_polygons(split(p, ext_b))
        if sub:
            all_pieces.extend(sub)
        else:
            all_pieces.append(p)

    matching = [p for p in all_pieces if p.contains(inside)]
    if not matching:
        raise ValueError(f"No cut piece contains inside point {inside}")

    chosen_piece = max(matching, key=lambda p: float(p.area))

    tol = 1e-7
    boundary_buf = chosen_piece.boundary.buffer(tol)

    la_geom = ext_a.intersection(boundary_buf)
    lb_geom = ext_b.intersection(boundary_buf)

    lines_a = [ls for ls in _extract_linestrings(la_geom) if ls.length > tol]
    lines_b = [ls for ls in _extract_linestrings(lb_geom) if ls.length > tol]

    if not lines_a or not lines_b:
        raise ValueError(
            f"Piece containing {inside} does not touch both cut lines"
        )

    la = max(lines_a, key=lambda ls: float(ls.length))
    lb = max(lines_b, key=lambda ls: float(ls.length))

    return chosen_piece, la, lb

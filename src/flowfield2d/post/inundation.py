"""Inundation polygons from a depth raster (REQUIREMENTS 4, Outputs).

Wet = finite depth greater than `min_depth` (and not nodata). Cells are joined with 4-connectivity.
Polygons stay in the raster's CRS. GeoJSON output carries the legacy named-CRS member, because the
data are generally not in WGS 84.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import rasterio.features
import shapely
from numpy.typing import ArrayLike, NDArray
from scipy.ndimage import generate_binary_structure, label
from shapely.geometry import MultiPolygon, Polygon, mapping, shape


def isolated_wet(depth: ArrayLike, connected_to: ArrayLike,
                 min_depth: float = 0.0) -> NDArray[np.bool_]:
    """Wet cells (finite depth > `min_depth`) whose 4-connected wet component contains
    no True cell of `connected_to`.

    These are terrain pits / ponds disconnected from the flow path at that time.
    """
    d = np.asarray(depth, dtype=np.float64)
    c = np.asarray(connected_to, dtype=bool)
    if d.shape != c.shape:
        raise ValueError(f"depth and connected_to shapes differ: {d.shape} vs {c.shape}")

    with np.errstate(invalid="ignore"):
        wet = np.isfinite(d) & (d > min_depth)

    struct = generate_binary_structure(d.ndim, 1)
    labeled, num_features = label(wet, structure=struct)
    if num_features == 0:
        return np.zeros(d.shape, dtype=bool)

    connected_labels = np.unique(labeled[c & wet])
    is_connected = np.zeros(num_features + 1, dtype=bool)
    is_connected[connected_labels] = True
    return (labeled > 0) & (~is_connected[labeled])


def inundation_polygons(depth_raster: Path, min_depth: float = 0.0,
                        min_area: float = 0.0) -> tuple[list[Polygon], str | None]:
    """Polygons of wet cells, each at least `min_area` (in CRS units squared), and the CRS."""
    if min_depth < 0:
        raise ValueError("min_depth must be >= 0")
    with rasterio.open(depth_raster) as ds:
        d = ds.read(1, masked=True)
        transform = ds.transform
        crs = ds.crs.to_string() if ds.crs else None
    filled = np.ma.filled(d.astype("f8"), np.nan)
    with np.errstate(invalid="ignore"):
        wet = np.isfinite(filled) & (filled > min_depth)
    polys = [shape(geom) for geom, val in
             rasterio.features.shapes(wet.astype("uint8"), mask=wet, transform=transform,
                                      connectivity=4) if val == 1]
    return [p for p in polys if p.area >= min_area], crs


def write_geojson(polygons: list[Polygon], out: Path, crs: str | None = None,
                  properties: Mapping[str, Any] | None = None) -> Path:
    features = [{"type": "Feature", "geometry": mapping(p),
                 "properties": {**(properties or {}), "area": p.area}} for p in polygons]
    fc: dict[str, Any] = {"type": "FeatureCollection", "features": features}
    if crs:
        fc["crs"] = {"type": "name", "properties": {"name": crs}}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(fc), encoding="utf-8")
    return Path(out)


def _chaikin_ring(coords: ArrayLike, iterations: int) -> NDArray[np.float64]:
    """Chaikin corner cutting on a closed ring (iterations times)."""
    pts: NDArray[np.float64] = np.asarray(coords, dtype=np.float64)
    if len(pts) == 0:
        return pts
    if len(pts) >= 2 and np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]

    if iterations <= 0 or len(pts) < 3:
        if len(pts) >= 1 and not np.allclose(pts[0], pts[-1]):
            res: NDArray[np.float64] = np.vstack([pts, pts[0:1]])
            return res
        return pts

    current: NDArray[np.float64] = pts
    for _ in range(iterations):
        nxt = np.roll(current, -1, axis=0)
        q = 0.75 * current + 0.25 * nxt
        r = 0.25 * current + 0.75 * nxt
        interleaved: NDArray[np.float64] = np.empty((2 * len(current), 2), dtype=np.float64)
        interleaved[0::2] = q
        interleaved[1::2] = r
        current = interleaved

    result: NDArray[np.float64] = np.vstack([current, current[0:1]])
    return result


def _extract_largest_polygon(geom: Any) -> Polygon:
    """Extract the largest Polygon from a geometry or collection."""
    if isinstance(geom, Polygon):
        return geom
    if isinstance(geom, MultiPolygon):
        if not geom.geoms:
            return Polygon()
        return max(geom.geoms, key=lambda g: float(g.area))
    if hasattr(geom, "geoms"):
        polys = [g for g in geom.geoms if isinstance(g, Polygon) and not g.is_empty]
        if polys:
            return max(polys, key=lambda g: float(g.area))
    return Polygon()


@dataclass(frozen=True)
class SmoothReport:
    n_in: int
    n_out: int
    area_in: float
    area_out: float
    max_offset: float


def smooth_outer(
    polygons: Sequence[Polygon],
    pixel: float,
    *,
    closing: float = 1.5,
    simplify: float = 0.5,
    iterations: int = 2,
    min_area: float = 0.0,
    min_hole: float = 0.0,
) -> tuple[list[Polygon], SmoothReport]:
    """Smooth pixel-edge polygons along the outer corners of stair steps."""
    if pixel <= 0:
        raise ValueError(f"pixel must be positive, got {pixel}")
    if closing < 0:
        raise ValueError(f"closing must be non-negative, got {closing}")
    if simplify < 0:
        raise ValueError(f"simplify must be non-negative, got {simplify}")
    if iterations < 0:
        raise ValueError(f"iterations must be non-negative, got {iterations}")
    if min_area < 0:
        raise ValueError(f"min_area must be non-negative, got {min_area}")
    if min_hole < 0:
        raise ValueError(f"min_hole must be non-negative, got {min_hole}")

    if not polygons:
        return [], SmoothReport(0, 0, 0.0, 0.0, 0.0)

    n_in = len(polygons)
    area_in = float(sum(p.area for p in polygons))
    out: list[Polygon] = []
    offsets: list[float] = []

    for poly in polygons:
        # 1. Skip when area < min_area
        if poly.area < min_area:
            continue

        # 2. Fill holes whose area < min_hole
        kept_interiors = [r for r in poly.interiors if Polygon(r).area >= min_hole]
        poly_step2 = Polygon(poly.exterior, kept_interiors)
        if not poly_step2.is_valid:
            poly_step2 = _extract_largest_polygon(shapely.make_valid(poly_step2))

        # 3. Closing: buffer(r) then buffer(-r) with r = closing * pixel
        if closing > 0:
            r = closing * pixel
            closed = poly_step2.buffer(r, join_style="round").buffer(-r, join_style="round")
        else:
            closed = poly_step2

        if isinstance(closed, Polygon):
            parts = [closed] if not closed.is_empty else []
        elif isinstance(closed, MultiPolygon):
            parts = [g for g in closed.geoms if isinstance(g, Polygon) and not g.is_empty]
        elif hasattr(closed, "geoms"):
            parts = [g for g in closed.geoms if isinstance(g, Polygon) and not g.is_empty]
        else:
            parts = []

        for part in parts:
            if len(parts) == 1:
                target_in = poly_step2
            else:
                sub = poly_step2.intersection(
                    part.buffer(closing * pixel if closing > 0 else pixel)
                )
                target_in = _extract_largest_polygon(sub) if not sub.is_empty else poly_step2

            # 4. Simplify
            if simplify > 0:
                part = part.simplify(simplify * pixel, preserve_topology=True)
                if not isinstance(part, Polygon):
                    part = _extract_largest_polygon(part)
                if part.is_empty:
                    continue

            # 5. Outward offset by 0.5 * pixel with round joins
            part = part.buffer(0.5 * pixel, join_style="round")
            if not isinstance(part, Polygon):
                part = _extract_largest_polygon(part)
            if part.is_empty:
                continue

            # 6. Chaikin corner cutting on every ring
            ext_smoothed = _chaikin_ring(part.exterior.coords, iterations)
            if len(ext_smoothed) < 4:
                continue
            int_smoothed: list[NDArray[np.float64]] = []
            for ring in part.interiors:
                r_smoothed = _chaikin_ring(ring.coords, iterations)
                if len(r_smoothed) >= 4:
                    int_smoothed.append(r_smoothed)

            rebuilt = Polygon(ext_smoothed, int_smoothed)
            part = _extract_largest_polygon(shapely.make_valid(rebuilt))
            if part.is_empty:
                continue

            # 7. Containment guarantee
            if not part.covers(target_in):
                merged = shapely.unary_union([part, target_in]).buffer(
                    0.25 * pixel, join_style="round"
                )
                part = _extract_largest_polygon(shapely.make_valid(merged))

            if not part.is_empty:
                out.append(part)
                offsets.append(float(shapely.hausdorff_distance(target_in, part)))

    n_out = len(out)
    area_out = float(sum(p.area for p in out))
    max_offset = max(offsets) if offsets else 0.0
    return out, SmoothReport(
        n_in=n_in,
        n_out=n_out,
        area_in=area_in,
        area_out=area_out,
        max_offset=max_offset,
    )

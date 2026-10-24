"""Inundation polygons from a depth raster (REQUIREMENTS 4, Outputs).

Wet = finite depth greater than `min_depth` (and not nodata). Cells are joined with 4-connectivity.
Polygons stay in the raster's CRS. GeoJSON output carries the legacy named-CRS member, because the
data are generally not in WGS 84.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import rasterio.features
from shapely.geometry import Polygon, mapping, shape


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

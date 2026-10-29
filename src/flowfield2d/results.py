"""Results as fields on a raster grid or as a cell table (REQUIREMENTS 4, Outputs; 5, Out).

Input is either an engine `Results` object (protocol in `engines`) or an already-exported
depth / velocity / WSE GeoTIFF triple. Outputs are SI rasters (COG), wet extents and cell tables.
The engine HDF reader itself stays in the engine adapter (`engines.ras2025.results`).

Units: inputs arrive in "model units" with `unit_m` metres per unit (0.3048 for a US-customary
model, 1.0 for SI). Conversion happens only in `to_si` (and inside `cell_table_from_results`,
which returns SI directly); x and y stay in CRS units throughout.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import rasterio
import rasterio.features
import rasterio.transform
import shapely
from numpy.typing import NDArray
from rasterio import Affine
from scipy.ndimage import binary_dilation, median_filter
from shapely.geometry import MultiPolygon, Polygon, shape

from flowfield2d.engines import Results

G: float = 9.80665
TABLE_KEYS = ("cell_id", "x", "y", "depth_m", "vel_mps", "wse_m", "froude")


@dataclass(frozen=True)
class Fields:
    """Depth, speed and WSE on one raster grid; NaN where dry or nodata."""

    depth: NDArray[np.float64]
    speed: NDArray[np.float64]
    wse: NDArray[np.float64]
    transform: Affine
    crs: str                      # as rasterio ds.crs.to_wkt()
    unit_m: float                 # metres per value unit (1.0 once in SI)


def _read_band(path: Path) -> tuple[NDArray[np.float64], Affine, str]:
    with rasterio.open(path) as ds:
        a = np.asarray(ds.read(1, masked=True).astype("f8").filled(np.nan), dtype=np.float64)
        crs = ds.crs.to_wkt() if ds.crs else ""
        transform = ds.transform
    a[~np.isfinite(a)] = np.nan
    return a, transform, crs


def read_fields(depth: Path, velocity: Path, wse: Path, unit_m: float) -> Fields:
    """Read a depth / velocity / WSE triple; nodata and non-finite values become NaN.
    The three rasters must share shape, transform and CRS."""
    d, t, c = _read_band(Path(depth))
    out = [d]
    for name, p in (("velocity", Path(velocity)), ("wse", Path(wse))):
        a, ta, ca = _read_band(p)
        if a.shape != d.shape:
            raise ValueError(f"{name} shape {a.shape} differs from depth {d.shape}")
        if ta != t:
            raise ValueError(f"{name} transform {ta!r} differs from depth {t!r}")
        if ca != c:
            raise ValueError(f"{name} CRS differs from depth CRS")
        out.append(a)
    return Fields(out[0], out[1], out[2], t, c, float(unit_m))


def to_si(f: Fields) -> Fields:
    """Scale the three fields by `unit_m` to metres; a no-op when already SI."""
    if f.unit_m == 1.0:
        return f
    k = f.unit_m
    return replace(f, depth=f.depth * k, speed=f.speed * k, wse=f.wse * k, unit_m=1.0)


def spike_mask(depth: NDArray[np.float64], *, jump: float, window: int = 9,
               dilate: int = 1) -> NDArray[np.bool_]:
    """Pixels whose depth exceeds the `window` x `window` median (NaN as 0, nearest-edge
    padding) by more than `jump` depth units, dilated `dilate` times with 4-connectivity;
    True only where depth is finite."""
    d = np.asarray(depth, dtype=np.float64)
    finite = np.isfinite(d)
    filled = np.where(finite, d, 0.0)
    med = median_filter(filled, size=int(window), mode="nearest")
    bad: NDArray[np.bool_] = finite & (filled - med > jump)
    if dilate > 0 and bad.any():
        cross = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)
        bad = np.asarray(binary_dilation(bad, structure=cross, iterations=int(dilate)),
                         dtype=bool)
    return bad & finite


def mask_fields(f: Fields, bad: NDArray[np.bool_]) -> Fields:
    """NaN in all three fields where `bad`."""
    b = np.asarray(bad, dtype=bool)
    if b.shape != f.depth.shape:
        raise ValueError(f"mask shape {b.shape} differs from fields {f.depth.shape}")
    return replace(f, depth=np.where(b, np.nan, f.depth), speed=np.where(b, np.nan, f.speed),
                   wse=np.where(b, np.nan, f.wse))


def froude(speed: NDArray[np.float64], depth: NDArray[np.float64],
           g: float = G) -> NDArray[np.float64]:
    """speed / sqrt(g * depth); NaN where depth <= 0 or NaN (no warnings)."""
    v = np.asarray(speed, dtype=np.float64)
    d = np.asarray(depth, dtype=np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        ok = np.isfinite(d) & (d > 0)
        out = np.where(ok, v / np.sqrt(g * np.where(ok, d, 1.0)), np.nan)
    return np.asarray(out, dtype=np.float64)


def wet_mask(depth: NDArray[np.float64], min_depth: float) -> NDArray[np.bool_]:
    """Finite depth greater than `min_depth`."""
    d = np.asarray(depth, dtype=np.float64)
    with np.errstate(invalid="ignore"):
        wet: NDArray[np.bool_] = np.isfinite(d) & (d > min_depth)
    return wet


def wet_polygon(mask: NDArray[np.bool_], transform: Affine) -> MultiPolygon | None:
    """Union of the wet pixels (4-connected) as a MultiPolygon; None when nothing is wet."""
    m = np.asarray(mask, dtype=bool)
    if not m.any():
        return None
    polys = [shape(geom) for geom, val in
             rasterio.features.shapes(m.astype("uint8"), mask=m, transform=transform,
                                      connectivity=4) if val == 1]
    u = shapely.unary_union(polys)
    if isinstance(u, MultiPolygon):
        return u
    if isinstance(u, Polygon):
        return MultiPolygon([u])
    parts = [g for g in shapely.get_parts(u) if isinstance(g, Polygon) and not g.is_empty]
    return MultiPolygon(parts) if parts else None


def nesting_violations(lower: NDArray[np.bool_], higher: NDArray[np.bool_]) -> int:
    """Pixels wet at the lower flow but dry at the higher one."""
    return int(np.count_nonzero(np.asarray(lower, dtype=bool) & ~np.asarray(higher, dtype=bool)))


def write_cog(a: NDArray[np.floating[Any]], path: Path, transform: Affine, crs: str,
              nodata: float = -9999.0) -> Path:
    """Write `a` as a float32 Cloud-Optimized GeoTIFF (deflate, floating-point predictor);
    NaN becomes `nodata`. Parent directories are created."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    data = np.asarray(a, dtype=np.float32)
    data = np.where(np.isfinite(data), data, np.float32(nodata))
    with rasterio.open(out, "w", driver="COG", height=data.shape[0], width=data.shape[1],
                       count=1, dtype="float32", crs=crs, transform=transform, nodata=nodata,
                       COMPRESS="DEFLATE", PREDICTOR=3, BIGTIFF="IF_SAFER") as ds:
        ds.write(data, 1)
    return out


def cells_table(f: Fields, mask: NDArray[np.bool_], g: float = G) -> dict[str, NDArray[Any]]:
    """One row per True pixel of `mask`, in row-major order, from SI fields: cell_id
    (row * width + col), x, y (pixel centres), depth_m, vel_mps, wse_m, froude."""
    if f.unit_m != 1.0:
        raise ValueError(f"fields must be SI (unit_m == 1.0), got unit_m={f.unit_m}")
    m = np.asarray(mask, dtype=bool)
    if m.shape != f.depth.shape:
        raise ValueError(f"mask shape {m.shape} differs from fields {f.depth.shape}")
    rows, cols = np.nonzero(m)
    width = f.depth.shape[1]
    xs, ys = rasterio.transform.xy(f.transform, rows, cols, offset="center")
    depth = f.depth[rows, cols].astype(np.float64)
    speed = f.speed[rows, cols].astype(np.float64)
    return {
        "cell_id": (rows.astype(np.int64) * width + cols.astype(np.int64)),
        "x": np.asarray(xs, dtype=np.float64),
        "y": np.asarray(ys, dtype=np.float64),
        "depth_m": depth,
        "vel_mps": speed,
        "wse_m": f.wse[rows, cols].astype(np.float64),
        "froude": froude(speed, depth, g),
    }


def write_parquet(table: Mapping[str, NDArray[Any]], path: Path) -> Path:
    """Write a column table to Parquet (zstd). Parent directories are created."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    t = pa.table({k: pa.array(np.asarray(v)) for k, v in table.items()})
    pq.write_table(t, out, compression="zstd")
    return out


def cell_table_from_results(results: Results, area: str, t: int, unit_m: float,
                            min_depth: float = 0.0) -> dict[str, NDArray[Any]]:
    """Cell table straight from an engine `Results` object at output `t`: cell_id = index,
    x, y from the cell centres (CRS units), depth / speed / WSE converted to SI with `unit_m`.
    Speed comes from `cell_max_face_speed` when the object provides it, else NaN. Dry cells
    (depth <= min_depth) get NaN depth, speed and WSE."""
    xy = np.asarray(results.cell_coordinates(area), dtype=np.float64)
    depth = np.asarray(results.cell_depth(area, t), dtype=np.float64)
    n = len(depth)
    wse = np.asarray(results.cell_wse(area, t, min_depth), dtype=np.float64)[:n]
    getter = getattr(results, "cell_max_face_speed", None)
    speed = (np.asarray(getter(area, t), dtype=np.float64)[:n] if callable(getter)
             else np.full(n, np.nan))
    with np.errstate(invalid="ignore"):
        wet = np.isfinite(depth) & (depth > min_depth)
    k = float(unit_m)
    depth_m = np.where(wet, depth * k, np.nan)
    speed_m = np.where(wet, speed * k, np.nan)
    wse_m = np.where(wet, wse * k, np.nan)
    return {
        "cell_id": np.arange(n, dtype=np.int64),
        "x": xy[:n, 0].astype(np.float64),
        "y": xy[:n, 1].astype(np.float64),
        "depth_m": depth_m,
        "vel_mps": speed_m,
        "wse_m": wse_m,
        "froude": froude(speed_m, depth_m),
    }

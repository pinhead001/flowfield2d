"""Clip and mosaic DEM tiles per domain; void-mask summaries (REQUIREMENTS 4, Terrain).

No reprojection or resampling: tiles must share CRS and resolution, otherwise this refuses.
CRS, units and vertical datum come from each DEM delivery's sidecar JSON.
Terrain guards: vertical scale check, declared vertical units, and region coverage.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
import rasterio.merge
import shapely
from numpy.typing import ArrayLike, NDArray
from shapely.geometry import MultiPolygon, Polygon

from flowfield2d.units import M_PER_FT

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


class TerrainScaleError(ValueError):
    """Raised when DEM and model vertical scales do not agree."""


class TerrainCoverageError(ValueError):
    """Raised when a region is not sufficiently covered by valid DEM data."""


UNIT_FACTORS: tuple[float, ...] = (1 / M_PER_FT, M_PER_FT)


def sample_dem(dem: Path, xy: ArrayLike) -> NDArray[np.float64]:
    """Band-1 values at (n, 2) coordinates; NaN outside raster or on nodata/non-finite cells."""
    pts = np.asarray(xy, dtype=np.float64)
    if pts.size == 0:
        return np.empty((0,), dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 2:
        raise ValueError(f"expected (n, 2) coordinates, got shape {pts.shape}")

    with rasterio.open(dem) as ds:
        inv = ~ds.transform
        xs = pts[:, 0]
        ys = pts[:, 1]
        cols = inv.a * xs + inv.b * ys + inv.c
        rows = inv.d * xs + inv.e * ys + inv.f
        c_idx = np.floor(cols).astype(np.int64)
        r_idx = np.floor(rows).astype(np.int64)

        inside = (c_idx >= 0) & (c_idx < ds.width) & (r_idx >= 0) & (r_idx < ds.height)
        out = np.full(pts.shape[0], np.nan, dtype=np.float64)
        if np.any(inside):
            # per-point reads (the DEM may be far larger than memory)
            vals = np.array([v[0] for v in ds.sample(pts[inside].tolist(), indexes=1)],
                            dtype=np.float64)
            vals[~np.isfinite(vals)] = np.nan
            if ds.nodata is not None and not np.isnan(ds.nodata):
                is_finite = np.isfinite(vals)
                matches_nodata = np.zeros(vals.shape, dtype=bool)
                matches_nodata[is_finite] = np.isclose(vals[is_finite], ds.nodata)
                vals[matches_nodata] = np.nan
            out[inside] = vals

    return out


@dataclass(frozen=True)
class ScaleCheck:
    n: int
    ratio: float
    max_abs_diff: float
    unit_factor: float | None
    ok: bool


def vertical_scale_check(
    reference: ArrayLike,
    model: ArrayLike,
    *,
    tolerance: float,
    factors: Sequence[float] = UNIT_FACTORS,
    factor_tolerance: float = 0.02,
) -> ScaleCheck:
    """Compare reference and model elevations, flagging unit-mismatch factors."""
    ref = np.asarray(reference, dtype=np.float64).squeeze()
    mod = np.asarray(model, dtype=np.float64).squeeze()
    if ref.ndim == 0:
        ref = ref.reshape(1)
    if mod.ndim == 0:
        mod = mod.reshape(1)
    if ref.ndim != 1 or mod.ndim != 1 or ref.shape[0] != mod.shape[0]:
        raise ValueError(
            f"reference and model must have the same length, got {ref.shape} and {mod.shape}"
        )
    if tolerance <= 0:
        raise ValueError(f"tolerance must be > 0, got {tolerance}")

    finite = np.isfinite(ref) & np.isfinite(mod)
    n = int(np.count_nonzero(finite))
    if n == 0:
        raise ValueError("no finite point pairs to compare")

    ref_valid = ref[finite]
    mod_valid = mod[finite]

    diffs = np.abs(mod_valid - ref_valid)
    max_abs_diff = float(np.max(diffs))
    ok = bool(max_abs_diff <= tolerance)

    has_mag = np.abs(ref_valid) > 1.0
    if np.any(has_mag):
        ratio = float(np.median(mod_valid[has_mag] / ref_valid[has_mag]))
    else:
        ratio = float(np.nan)

    unit_factor: float | None = None
    if not ok and np.isfinite(ratio):
        for f in factors:
            if abs(ratio - f) <= factor_tolerance * f:
                unit_factor = float(f)
                break

    return ScaleCheck(
        n=n,
        ratio=ratio,
        max_abs_diff=max_abs_diff,
        unit_factor=unit_factor,
        ok=ok,
    )


def assert_vertical_scale(
    dem: Path,
    xy: ArrayLike,
    model: ArrayLike,
    *,
    tolerance: float,
    factors: Sequence[float] = UNIT_FACTORS,
    factor_tolerance: float = 0.02,
) -> ScaleCheck:
    """Check DEM against model elevations; raise TerrainScaleError on scale or unit mismatch."""
    ref = sample_dem(dem, xy)
    mod = np.asarray(model, dtype=np.float64).reshape(-1)
    if mod.shape == ref.shape and not np.any(np.isfinite(ref) & np.isfinite(mod)):
        raise TerrainScaleError("no finite point pairs to compare")
    check = vertical_scale_check(
        ref,
        model,
        tolerance=tolerance,
        factors=factors,
        factor_tolerance=factor_tolerance,
    )

    if not check.ok:
        if check.unit_factor is not None:
            msg = (
                f"model elevations are {check.unit_factor:.4g}x the DEM at "
                f"{check.n} points: a feet/metres mix?"
            )
        else:
            msg = (
                f"model elevations differ from DEM by up to {check.max_abs_diff:.4g} "
                f"(tolerance {tolerance})"
            )
        raise TerrainScaleError(msg)

    return check


def wkt_vertical_units(wkt: str) -> str | None:
    """Extract the vertical CRS unit name from a WKT1 or WKT2 string, if present."""
    if not wkt:
        return None
    m_vert = re.search(r"(?:VERT_CS|VERT(?:ICAL)?CRS)\s*\[", wkt, re.IGNORECASE)
    if not m_vert:
        return None
    m_unit = re.search(
        r'(?:UNIT|LENGTHUNIT)\s*\[\s*["\']([^"\']+)["\']',
        wkt[m_vert.end():],
        re.IGNORECASE,
    )
    if not m_unit:
        return None
    return m_unit.group(1)


def vertical_units(dem: Path) -> str | None:
    """The vertical unit of the raster's CRS, or None if missing or raster has no CRS."""
    with rasterio.open(dem) as ds:
        if ds.crs is None:
            return None
        wkt = ds.crs.to_wkt()
    return wkt_vertical_units(wkt)


def require_vertical_units(dem: Path, declared: str | None) -> str:
    """Return the raster's vertical unit or stripped `declared`; raise ValueError if neither."""
    v_unit = vertical_units(dem)
    if v_unit is not None and v_unit.strip():
        return v_unit.strip()
    if declared is not None and declared.strip():
        return declared.strip()
    raise ValueError(f"no vertical units found in raster CRS for {dem} and none declared")


@dataclass(frozen=True)
class Coverage:
    region_area: float
    uncovered_area: float
    uncovered: Polygon | MultiPolygon

    @property
    def fraction(self) -> float:
        return self.uncovered_area / self.region_area if self.region_area else 0.0


def coverage(
    dem: Path,
    region: Polygon | MultiPolygon,
    *,
    resolution: float | None = None,
) -> Coverage:
    """Compute region area uncovered by the valid-data footprint of dem."""
    if region.is_empty:
        raise ValueError("cannot compute coverage of an empty region")

    from flowfield2d.domaingen import valid_area

    try:
        dem_valid: Polygon | MultiPolygon = valid_area(
            dem, bounds=region.bounds, resolution=resolution
        )
    except ValueError:
        dem_valid = Polygon()

    diff = region.difference(dem_valid)
    polys = [g for g in shapely.get_parts(diff) if isinstance(g, Polygon) and not g.is_empty]
    uncovered: Polygon | MultiPolygon
    if not polys:
        uncovered = Polygon()
    elif len(polys) == 1:
        uncovered = polys[0]
    else:
        uncovered = MultiPolygon(polys)

    region_area = float(region.area)
    uncovered_area = float(uncovered.area)
    return Coverage(
        region_area=region_area,
        uncovered_area=uncovered_area,
        uncovered=uncovered,
    )


def assert_covered(
    dem: Path,
    region: Polygon | MultiPolygon,
    *,
    max_uncovered: float = 0.0,
    resolution: float | None = None,
) -> Coverage:
    """Verify dem covers region; raise TerrainCoverageError if uncovered area exceeds max."""
    cov = coverage(dem, region, resolution=resolution)
    if cov.uncovered_area > max_uncovered:
        raise TerrainCoverageError(
            f"dem leaves {cov.uncovered_area:.4g} uncovered area "
            f"(bounds {cov.uncovered.bounds}) exceeding maximum allowed {max_uncovered}"
        )
    return cov

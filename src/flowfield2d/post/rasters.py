"""COG rasters of WSE, depth, velocity and shear."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
import rasterio.io
from rasterio import Affine
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.warp import reproject
from rasterio.windows import Window
from rasterio.windows import transform as window_transform
from shapely.geometry import MultiPolygon, Polygon


@dataclass(frozen=True)
class Grid:
    """Snapped north-up raster grid specification."""

    transform: Affine
    width: int
    height: int
    crs: str

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """Return (left, bottom, right, top) bounds of the grid."""
        left = self.transform.c
        top = self.transform.f
        right = left + self.width * self.transform.a
        bottom = top + self.height * self.transform.e
        return (float(left), float(bottom), float(right), float(top))


def snapped_grid(
    bounds: Sequence[float],
    pixel: float,
    crs: str,
    origin: tuple[float, float] = (0.0, 0.0),
) -> Grid:
    """Compute the smallest north-up grid of square cells covering bounds anchored at origin."""
    if pixel <= 0.0:
        raise ValueError(f"pixel must be positive, got {pixel}")
    if len(bounds) != 4:
        raise ValueError(f"bounds must be a sequence of 4 floats, got {len(bounds)}")

    minx, miny, maxx, maxy = (float(b) for b in bounds)
    if minx >= maxx or miny >= maxy:
        raise ValueError(f"inverted or empty bounds: ({minx}, {miny}, {maxx}, {maxy})")

    ox, oy = origin
    left = ox + math.floor((minx - ox) / pixel) * pixel
    right = ox + math.ceil((maxx - ox) / pixel) * pixel
    bottom = oy + math.floor((miny - oy) / pixel) * pixel
    top = oy + math.ceil((maxy - oy) / pixel) * pixel

    width = int(round((right - left) / pixel))
    height = int(round((top - bottom) / pixel))
    transform = Affine(pixel, 0.0, left, 0.0, -pixel, top)
    return Grid(transform=transform, width=width, height=height, crs=crs)


@dataclass(frozen=True)
class Source:
    """Source raster with optional clipping area and map spike filter."""

    path: Path
    area: Polygon | MultiPolygon | None = None
    max_value: float | None = None


def mosaic(
    sources: Sequence[Source],
    out: Path,
    *,
    pixel: float,
    nodata: float = -9999.0,
    origin: tuple[float, float] = (0.0, 0.0),
    overviews: Sequence[int] = (2, 4, 8, 16, 32, 64),
    overview_resampling: str = "nearest",
    blocksize: int = 512,
) -> Grid:
    """Priority mosaic of per-domain rasters onto one snapped grid written as a sparse GeoTIFF."""
    if not sources:
        raise ValueError("At least one source is required")

    common_crs: str | None = None
    minx: float = float("inf")
    miny: float = float("inf")
    maxx: float = float("-inf")
    maxy: float = float("-inf")

    for src in sources:
        with rasterio.open(src.path) as ds:
            if ds.crs is None:
                raise ValueError(f"Source {src.path} has no CRS")
            crs_str = ds.crs.to_string()
            if common_crs is None:
                common_crs = crs_str
            elif crs_str != common_crs:
                raise ValueError(
                    f"Conflicting CRS: source {src.path} has CRS {crs_str}, expected {common_crs}"
                )
            b = ds.bounds
            minx = min(minx, b.left)
            miny = min(miny, b.bottom)
            maxx = max(maxx, b.right)
            maxy = max(maxy, b.top)

    assert common_crs is not None
    grid = snapped_grid((minx, miny, maxx, maxy), pixel=pixel, crs=common_crs, origin=origin)

    out.parent.mkdir(parents=True, exist_ok=True)

    max_dim = max(grid.width, grid.height)
    actual_blocksize = blocksize
    if max_dim < blocksize:
        actual_blocksize = max(16, int(math.ceil(max_dim / 16.0) * 16))

    with rasterio.open(
        out,
        "w",
        driver="GTiff",
        height=grid.height,
        width=grid.width,
        count=1,
        dtype="float32",
        crs=grid.crs,
        transform=grid.transform,
        nodata=nodata,
        tiled=True,
        blockxsize=actual_blocksize,
        blockysize=actual_blocksize,
        compress="deflate",
        predictor=3,
        sparse_ok=True,
        BIGTIFF="IF_SAFER",
    ) as _:
        pass

    try:
        with rasterio.open(out, "r+") as dst:
            for src in sources:
                with rasterio.open(src.path) as src_ds:
                    _write_source(dst, src_ds, src, grid, pixel, origin, nodata, actual_blocksize)
            factors = [f for f in overviews if f <= max(grid.width, grid.height)]
            if factors:
                dst.build_overviews(factors, Resampling[overview_resampling])
                dst.update_tags(ns="rio_overview", resampling=overview_resampling)
    except BaseException:
        out.unlink(missing_ok=True)
        raise

    return grid


def _is_nodata(values: np.ndarray, nodata: float) -> np.ndarray:
    """Exact nodata test (NaN nodata compares with isnan); non-finite values count as nodata."""
    bad = ~np.isfinite(values)
    if not np.isnan(nodata):
        bad |= values == nodata
    return bad


def _write_source(
    dst: rasterio.io.DatasetWriter,
    src_ds: rasterio.io.DatasetReader,
    src: Source,
    grid: Grid,
    pixel: float,
    origin: tuple[float, float],
    nodata: float,
    blocksize: int,
) -> None:
    """Resample one source onto its window of the grid, strip by strip (block-row aligned), and
    fill only the destination pixels that are still nodata. Memory stays at one strip."""
    g_left, g_bottom, g_right, g_top = grid.bounds
    sb = src_ds.bounds
    s_left = origin[0] + math.floor((sb.left - origin[0]) / pixel) * pixel
    s_right = origin[0] + math.ceil((sb.right - origin[0]) / pixel) * pixel
    s_bottom = origin[1] + math.floor((sb.bottom - origin[1]) / pixel) * pixel
    s_top = origin[1] + math.ceil((sb.top - origin[1]) / pixel) * pixel

    c_left, c_right = max(g_left, s_left), min(g_right, s_right)
    c_bottom, c_top = max(g_bottom, s_bottom), min(g_top, s_top)
    if c_left >= c_right or c_bottom >= c_top:
        return
    col_off = int(round((c_left - g_left) / pixel))
    row_off = int(round((g_top - c_top) / pixel))
    win_width = int(round((c_right - c_left) / pixel))
    win_height = int(round((c_top - c_bottom) / pixel))
    if win_width <= 0 or win_height <= 0:
        return

    row_end = row_off + win_height
    row = row_off
    while row < row_end:
        row_next = min(row_end, (row // blocksize + 1) * blocksize)
        strip = Window(col_off, row, win_width, row_next - row)
        strip_transform = window_transform(strip, grid.transform)
        data = np.full((row_next - row, win_width), nodata, dtype=np.float32)
        reproject(
            source=rasterio.band(src_ds, 1),
            destination=data,
            dst_transform=strip_transform,
            dst_crs=dst.crs,
            resampling=Resampling.nearest,
            src_nodata=src_ds.nodata,
            dst_nodata=nodata,
        )
        invalid = _is_nodata(data, nodata)
        if src.max_value is not None:
            invalid |= data > src.max_value
        if src.area is not None:
            mask = rasterize(
                [src.area],
                out_shape=data.shape,
                transform=strip_transform,
                all_touched=False,
                fill=0,
                default_value=1,
                dtype=np.uint8,
            )
            invalid |= mask == 0
        valid = ~invalid
        if valid.any():
            current = dst.read(1, window=strip)
            update = valid & _is_nodata(current, nodata)
            if update.any():
                current[update] = data[update]
                dst.write(current, 1, window=strip)
        row = row_next

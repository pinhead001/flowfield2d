"""Terrain guards: vertical-scale agreement between a DEM and a model, declared vertical units,
and terrain coverage of a region (no RAS; synthetic rasters only)."""

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box

from flowfield2d.terrain import (
    Coverage,
    ScaleCheck,
    TerrainCoverageError,
    TerrainScaleError,
    assert_covered,
    assert_vertical_scale,
    coverage,
    require_vertical_units,
    sample_dem,
    vertical_scale_check,
    vertical_units,
    wkt_vertical_units,
)

CRS = "EPSG:3857"
FT_PER_M = 1 / 0.3048


def _tif(path: Path, data: np.ndarray, x0: float, y0: float, res: float = 1.0,
         nodata: float | None = -9999.0, crs: str = CRS) -> Path:
    with rasterio.open(path, "w", driver="GTiff", height=data.shape[0], width=data.shape[1],
                       count=1, dtype=data.dtype, crs=crs, nodata=nodata,
                       transform=from_origin(x0, y0, res, res)) as ds:
        ds.write(data, 1)
    return path


def test_sample_dem_values_nodata_and_outside(tmp_path: Path) -> None:
    z = (np.arange(4)[:, None] * 10 + np.arange(4)[None, :]).astype("f4")   # z = 10*row + col
    z[1, 1] = -9999.0
    dem = _tif(tmp_path / "dem.tif", z, 0, 4)
    got = sample_dem(dem, [(0.5, 3.5), (3.5, 0.5), (1.5, 2.5), (10.0, 10.0), (-1.0, 2.0)])
    assert got[0] == 0.0 and got[1] == 33.0
    assert np.isnan(got[2]) and np.isnan(got[3]) and np.isnan(got[4])
    assert got.dtype == np.float64 and got.shape == (5,)
    assert sample_dem(dem, np.empty((0, 2))).shape == (0,)


def test_vertical_scale_check_flags_unit_factors() -> None:
    ref = np.array([100.0, 200.0, 300.0, 400.0])
    c = vertical_scale_check(ref, ref * FT_PER_M, tolerance=0.5)
    assert isinstance(c, ScaleCheck) and not c.ok and c.n == 4
    assert c.unit_factor == pytest.approx(FT_PER_M, rel=1e-6)
    assert c.ratio == pytest.approx(FT_PER_M, rel=1e-6)
    c = vertical_scale_check(ref, ref * 0.3048, tolerance=0.5)
    assert not c.ok and c.unit_factor == pytest.approx(0.3048, rel=1e-6)
    # 1.5% off the factor still matches (survey vs international foot, sampling noise)
    c = vertical_scale_check(ref, ref * FT_PER_M * 1.015, tolerance=0.5)
    assert not c.ok and c.unit_factor == pytest.approx(FT_PER_M, rel=1e-6)
    # a different factor is a plain mismatch, not a unit factor
    c = vertical_scale_check(ref, ref * 2.0, tolerance=0.5)
    assert not c.ok and c.unit_factor is None and c.max_abs_diff == pytest.approx(400.0)


def test_vertical_scale_check_within_tolerance_and_nans() -> None:
    ref = np.array([100.0, 200.0, np.nan, 400.0, 500.0])
    model = np.array([99.7, 199.8, 300.0, np.nan, 499.6])          # cell minima a little below
    c = vertical_scale_check(ref, model, tolerance=0.5)
    assert c.ok and c.n == 3 and c.unit_factor is None
    assert c.max_abs_diff == pytest.approx(0.4) and c.ratio == pytest.approx(0.999, abs=2e-3)
    c = vertical_scale_check(ref, model + 2.0, tolerance=0.5)
    assert not c.ok and c.unit_factor is None and c.max_abs_diff == pytest.approx(1.8)
    # near-datum points: a ratio near a unit factor with differences inside tolerance is fine
    c = vertical_scale_check([0.1, 0.2], [0.328, 0.656], tolerance=0.5)
    assert c.ok and c.unit_factor is None
    with pytest.raises(ValueError, match="no"):
        vertical_scale_check([np.nan, 1.0], [1.0, np.nan], tolerance=0.5)
    with pytest.raises(ValueError):
        vertical_scale_check([1.0, 2.0], [1.0], tolerance=0.5)
    with pytest.raises(ValueError):
        vertical_scale_check([1.0], [1.0], tolerance=0.0)


def test_assert_vertical_scale_against_raster(tmp_path: Path) -> None:
    xs = (np.arange(10) + 0.5)[None, :]
    z = (100.0 + np.repeat(xs, 10, axis=0)).astype("f4")           # z = 100 + x
    dem = _tif(tmp_path / "dem.tif", z, 0, 10)
    xy = np.array([(1.5, 5.5), (4.5, 2.5), (8.5, 8.5)])
    bed = np.array([101.3, 104.4, 108.2])                            # DEM 101.5, 104.5, 108.5
    c = assert_vertical_scale(dem, xy, bed, tolerance=0.5)
    assert c.ok and c.n == 3 and c.max_abs_diff == pytest.approx(0.3)
    with pytest.raises(TerrainScaleError, match="3.281"):
        assert_vertical_scale(dem, xy, bed * FT_PER_M, tolerance=0.5)
    with pytest.raises(TerrainScaleError, match="tolerance"):
        assert_vertical_scale(dem, xy, bed + 1.0, tolerance=0.5)
    with pytest.raises(TerrainScaleError, match="no"):
        assert_vertical_scale(dem, [(50.0, 50.0)], [1.0], tolerance=0.5)


WKT2_COMPOUND = """COMPOUNDCRS["H + V",
  PROJCRS["H", BASEGEOGCRS["G", DATUM["D", ELLIPSOID["E", 6378137, 298.257]]],
    CONVERSION["C", METHOD["Transverse Mercator"]],
    CS[Cartesian, 2], AXIS["(E)", east], AXIS["(N)", north], LENGTHUNIT["metre", 1]],
  VERTCRS["V", VDATUM["VD"], CS[vertical, 1], AXIS["up", up], LENGTHUNIT["foot", 0.3048]]]"""

WKT1_COMPOUND = """COMPD_CS["H + V",
  PROJCS["H", GEOGCS["G", DATUM["D", SPHEROID["E", 6378137, 298.257]],
    UNIT["degree", 0.0174532925]], PROJECTION["Transverse_Mercator"], UNIT["metre", 1]],
  VERT_CS["V", VERT_DATUM["VD", 2005], UNIT["US survey foot", 0.304800609601219],
    AXIS["Up", UP]]]"""

WKT2_PROJECTED = """PROJCRS["H", BASEGEOGCRS["G", DATUM["D", ELLIPSOID["E", 6378137, 298.257]]],
  CONVERSION["C", METHOD["Transverse Mercator"]],
  CS[Cartesian, 2], AXIS["(E)", east], AXIS["(N)", north], LENGTHUNIT["metre", 1]]"""


def test_wkt_vertical_units() -> None:
    assert wkt_vertical_units(WKT2_COMPOUND) == "foot"
    assert wkt_vertical_units(WKT1_COMPOUND) == "US survey foot"
    assert wkt_vertical_units(WKT2_PROJECTED) is None
    assert wkt_vertical_units("") is None


def test_require_vertical_units(tmp_path: Path) -> None:
    dem = _tif(tmp_path / "dem.tif", np.ones((2, 2), "f4"), 0, 2)   # projected CRS, no vertical
    assert vertical_units(dem) is None
    with pytest.raises(ValueError, match="vertical"):
        require_vertical_units(dem, None)
    with pytest.raises(ValueError, match="vertical"):
        require_vertical_units(dem, "  ")
    assert require_vertical_units(dem, "m") == "m"
    bare = _tif(tmp_path / "bare.tif", np.ones((2, 2), "f4"), 0, 2, crs=None)
    assert vertical_units(bare) is None
    assert require_vertical_units(bare, "ft") == "ft"


def _coverage_dem(tmp_path: Path) -> Path:
    z = np.full((20, 20), 50.0, "f4")                                # x 0..20, y 0..20
    z[:, :5] = -9999.0                                               # no data for x < 5
    return _tif(tmp_path / "dem.tif", z, 0, 20)


def test_coverage_reports_uncovered_area(tmp_path: Path) -> None:
    dem = _coverage_dem(tmp_path)
    c = coverage(dem, box(2, 2, 12, 12))
    assert isinstance(c, Coverage)
    assert c.region_area == pytest.approx(100.0)
    assert c.uncovered_area == pytest.approx(30.0) and c.fraction == pytest.approx(0.3)
    assert c.uncovered.bounds == pytest.approx((2.0, 2.0, 5.0, 12.0))
    full = coverage(dem, box(6, 6, 10, 10))
    assert full.uncovered_area == 0.0 and full.fraction == 0.0 and full.uncovered.is_empty
    edge = coverage(dem, box(15, 15, 25, 25))                        # half outside the raster
    assert edge.uncovered_area == pytest.approx(75.0)
    outside = coverage(dem, box(30, 30, 40, 40))                     # entirely outside
    assert outside.uncovered_area == pytest.approx(100.0) and outside.fraction == pytest.approx(1.0)
    with pytest.raises(ValueError):
        coverage(dem, Polygon())


def test_coverage_at_working_resolution(tmp_path: Path) -> None:
    dem = _coverage_dem(tmp_path)
    c = coverage(dem, box(2, 2, 12, 12), resolution=2.0)      # edge quantised to 2 px: 20..40
    assert 15.0 <= c.uncovered_area <= 45.0 and c.uncovered_area == pytest.approx(30.0, abs=10.0)


def test_assert_covered(tmp_path: Path) -> None:
    dem = _coverage_dem(tmp_path)
    region = box(2, 2, 12, 12)
    with pytest.raises(TerrainCoverageError, match="uncovered"):
        assert_covered(dem, region)
    c = assert_covered(dem, region, max_uncovered=35.0)
    assert c.uncovered_area == pytest.approx(30.0)
    assert assert_covered(dem, box(6, 6, 10, 10)).uncovered_area == 0.0

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString

from flowfield2d.slope import cut_slope, fit_slope, terrain_profile, thalweg_profile


def _dem(tmp_path: Path) -> Path:
    """Plane falling 0.01 per unit toward +x, with a 2-unit-deep trench along y = 50."""
    x = np.arange(0.5, 200, 1.0)
    y = np.arange(99.5, 0, -1.0)
    xx, yy = np.meshgrid(x, y)
    z = 100.0 - 0.01 * xx - np.where(np.abs(yy - 50) < 5, 2.0, 0.0)
    p = tmp_path / "dem.tif"
    with rasterio.open(p, "w", driver="GTiff", height=z.shape[0], width=z.shape[1], count=1,
                       dtype="float32", crs="EPSG:3857", transform=from_origin(0, 100, 1, 1)) as ds:
        ds.write(z.astype("float32"), 1)
    return p


def test_fit_slope_windows() -> None:
    ch = np.arange(0, 1000.0, 10)
    z = 50 - 0.02 * ch
    assert fit_slope(ch, z, at=500, window=200) == pytest.approx(0.02)
    assert fit_slope(ch, z, at=500, window=200, side="downstream") == pytest.approx(0.02)
    z2 = np.where(ch < 500, 50 - 0.05 * ch, 25 - 0.01 * (ch - 500))
    assert fit_slope(ch, z2, at=500, window=300, side="downstream") == pytest.approx(0.01)
    assert fit_slope(ch, z2, at=500, window=300, side="upstream") == pytest.approx(0.05)
    with pytest.raises(ValueError):
        fit_slope(ch, z, at=5000, window=10)


def test_terrain_and_thalweg_profiles(tmp_path: Path) -> None:
    dem = _dem(tmp_path)
    centerline = LineString([(10, 45), (190, 45)])        # just off the trench centre
    ch, z = terrain_profile(dem, centerline, spacing=5)
    assert fit_slope(ch, z, at=90, window=60) == pytest.approx(0.01, rel=0.05)
    ch2, zmin = thalweg_profile(dem, centerline, spacing=5, half_width=20)
    assert np.all(zmin <= z + 1e-6)
    assert np.nanmin(z - zmin) > 1.5                      # transect minima find the trench
    assert fit_slope(ch2, zmin, at=90, window=60) == pytest.approx(0.01, rel=0.05)


def test_cut_slope_dispatch(tmp_path: Path) -> None:
    dem = _dem(tmp_path)
    line = LineString([(10, 50), (190, 50)])
    ch = np.arange(0, 181.0, 5)
    wse = 99.0 - 0.012 * ch
    kw = dict(at=90, window=60)
    assert cut_slope("specified", value=0.004, **kw) == 0.004
    assert cut_slope("terrain", dem=dem, centerline=line, **kw) == pytest.approx(0.01, rel=0.05)
    assert cut_slope("thalweg", dem=dem, centerline=line, half_width=20, **kw) == \
        pytest.approx(0.01, rel=0.05)
    assert cut_slope("wse", chainage=ch, wse=wse, **kw) == pytest.approx(0.012)
    with pytest.raises(ValueError):
        cut_slope("terrain", **kw)                        # missing dem/centerline
    with pytest.raises(ValueError):
        cut_slope("guess", **kw)
    with pytest.raises(ValueError, match="positive"):
        cut_slope("wse", chainage=ch, wse=99.0 + 0.012 * ch, **kw)   # adverse slope

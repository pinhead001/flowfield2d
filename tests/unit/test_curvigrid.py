import math
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString

from flowfield2d.curvigrid import build_grid, sample_raster


def test_straight_channel_grid() -> None:
    g = build_grid(LineString([(0, 0), (100, 0)]), width=20.0, ni=11, nj=5)
    assert g.xy.shape == (11, 5, 2) and (g.ni, g.nj) == (11, 5)
    assert np.allclose(g.s, np.linspace(0, 100, 11))
    assert np.allclose(g.xy[:, :, 0], np.linspace(0, 100, 11)[:, None])
    # i runs along the line; j runs from the right bank to the left bank (looking along i)
    assert np.allclose(g.xy[:, :, 1], np.linspace(-10, 10, 5)[None, :])
    assert np.allclose(g.cell_areas(), 10.0 * 5.0)
    assert np.allclose(g.cell_centres()[0, 0], (5.0, -7.5))


def test_arc_sections_are_radial() -> None:
    r = 100.0
    th = np.linspace(0, math.pi / 2, 400)
    line = LineString(np.column_stack([r * np.sin(th), r * (1 - np.cos(th))]))  # centre (0, r)
    g = build_grid(line, width=40.0, ni=21, nj=9)
    radius = np.hypot(g.xy[:, :, 0], g.xy[:, :, 1] - r)
    assert np.allclose(radius, np.linspace(r + 20, r - 20, 9)[None, :], atol=0.05)
    assert (g.cell_areas() > 0).all()


def test_width_per_station() -> None:
    w = np.linspace(10, 30, 6)
    g = build_grid(LineString([(0, 0), (50, 0)]), width=w, ni=6, nj=3)
    assert np.allclose(g.xy[:, 2, 1] - g.xy[:, 0, 1], w)


def test_folded_grid_is_refused() -> None:
    th = np.linspace(0, math.pi, 200)
    line = LineString(np.column_stack([10 * np.sin(th), 10 * (1 - np.cos(th))]))  # radius 10
    with pytest.raises(ValueError, match="fold"):
        build_grid(line, width=30.0, ni=21, nj=5)      # half width 15 > radius


def test_bad_arguments() -> None:
    line = LineString([(0, 0), (10, 0)])
    for kw in ({"ni": 1, "nj": 3}, {"ni": 3, "nj": 1}):
        with pytest.raises(ValueError):
            build_grid(line, width=2.0, **kw)
    with pytest.raises(ValueError):
        build_grid(line, width=0.0, ni=3, nj=3)
    with pytest.raises(ValueError):
        build_grid(line, width=np.ones(4), ni=3, nj=3)


def _plane(path: Path) -> Path:
    """z = 2x + 3y at cell centres, 1-unit cells over x 0..20, y 0..10; one nodata cell."""
    ys, xs = np.mgrid[0:10, 0:20]
    z = (2 * (xs + 0.5) + 3 * (10 - ys - 0.5)).astype("float32")
    z[0, 0] = -9999.0
    with rasterio.open(path, "w", driver="GTiff", height=10, width=20, count=1, dtype="float32",
                       transform=from_origin(0, 10, 1, 1), nodata=-9999.0) as ds:
        ds.write(z, 1)
    return path


def test_sample_raster_bilinear_and_nearest(tmp_path: Path) -> None:
    p = _plane(tmp_path / "z.tif")
    x = np.array([[5.0, 7.25], [12.6, 3.3]])
    y = np.array([[5.2, 2.75], [8.1, 4.4]])
    assert np.allclose(sample_raster(p, x, y), 2 * x + 3 * y, atol=1e-4)
    near = sample_raster(p, x, y, method="nearest")
    assert np.allclose(near, 2 * (np.floor(x) + 0.5) + 3 * (np.floor(y) + 0.5), atol=1e-4)


def test_sample_raster_nan_outside_and_nodata(tmp_path: Path) -> None:
    p = _plane(tmp_path / "z.tif")
    x = np.array([-5.0, 0.5, 25.0, 0.2])
    y = np.array([5.0, 9.5, 5.0, 5.0])
    out = sample_raster(p, x, y)
    assert np.isnan(out[[0, 1, 2]]).all()        # outside, nodata cell, outside
    assert math.isclose(out[3], 2 * 0.5 + 3 * 5.0, abs_tol=1e-4)   # outer half cell: edge value
    assert np.isnan(sample_raster(p, x, y, method="nearest")[[0, 1, 2]]).all()

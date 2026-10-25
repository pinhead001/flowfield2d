"""Centerlines and thalwegs from depth rasters; profiles sampled along a line."""

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point

from flowfield2d.post.centerline import (
    centerline,
    distance_to_edge,
    least_cost_path,
    profile_from_cells,
    sample_raster,
    thalweg,
)

CELL = 5.0
NR, NC = 120, 200                                   # 1000 m (x) by 600 m (y)
TR = from_origin(0.0, NR * CELL, CELL, CELL)


def _xy(r: np.ndarray, c: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return (c + 0.5) * CELL, NR * CELL - (r + 0.5) * CELL


def _sine_band(half_width: float = 40.0) -> tuple[np.ndarray, np.ndarray]:
    """Depth raster of a meandering channel: centre y = 300 + 100 sin(2 pi x / 1000)."""
    r, c = np.mgrid[0:NR, 0:NC]
    x, y = _xy(r, c)
    yc = 300.0 + 100.0 * np.sin(2 * np.pi * x / 1000.0)
    off = y - yc
    depth = np.where(np.abs(off) < half_width, 2.0 * (1 - (off / half_width) ** 2), 0.0)
    return depth, yc


def test_distance_to_edge_rectangle() -> None:
    mask = np.zeros((9, 15), dtype=bool)
    mask[2:7, 1:14] = True                          # 5 rows tall
    d = distance_to_edge(mask, CELL)
    assert d[0, 0] == 0 and d[4, 7] == pytest.approx(3 * CELL)  # middle row: 3 cells to dry
    assert d[2, 7] == pytest.approx(CELL)
    assert (d[~mask] == 0).all()


def test_least_cost_path_finds_gap() -> None:
    cost = np.ones((20, 20))
    cost[:, 10] = 1e6
    cost[15, 10] = 1.0                              # one gap in the wall
    path = least_cost_path(cost, (2, 2), (2, 17))
    assert path[0] == (2, 2) and path[-1] == (2, 17)
    assert (15, 10) in path
    steps = zip(path, path[1:], strict=False)
    assert all(max(abs(a[0] - b[0]), abs(a[1] - b[1])) == 1 for a, b in steps)   # 8-connected
    with pytest.raises(ValueError):
        least_cost_path(cost, (0, 0), (25, 0))


def test_centerline_follows_meander_middle() -> None:
    depth, _ = _sine_band()
    line = centerline(depth > 0, TR, (10.0, 300.0), (990.0, 300.0))
    assert isinstance(line, LineString)
    assert Point(line.coords[0]).distance(Point(10.0, 300.0)) < 3 * CELL
    assert Point(line.coords[-1]).distance(Point(990.0, 300.0)) < 3 * CELL
    xs = np.linspace(50.0, 950.0, 40)
    for x in xs:                                    # stays within 2 cells of the band's middle
        yc = 300.0 + 100.0 * np.sin(2 * np.pi * x / 1000.0)
        assert line.distance(Point(x, yc)) < 2 * CELL + 1e-6


def test_centerline_simplify_and_snap_outside_endpoints() -> None:
    depth, _ = _sine_band()
    line = centerline(depth > 0, TR, (5.0, 590.0), (995.0, 10.0), max_vertices=30)
    assert len(line.coords) <= 30
    assert depth[rasterio.transform.rowcol(TR, *line.coords[0])] > 0   # snapped into the water


def test_thalweg_follows_deep_groove_not_middle() -> None:
    depth, yc = _sine_band(half_width=60.0)
    r, c = np.mgrid[0:NR, 0:NC]
    _, y = _xy(r, c)
    groove = (np.abs(y - (yc + 30.0)) < CELL) & (depth > 0)     # 30 m off-centre
    depth = np.where(groove, depth + 3.0, depth)
    tw = thalweg(depth, TR, (10.0, 330.0), (990.0, 330.0))
    for x in np.linspace(100.0, 900.0, 20):
        y_groove = 330.0 + 100.0 * np.sin(2 * np.pi * x / 1000.0)
        assert tw.distance(Point(x, y_groove)) < 2 * CELL + 1e-6
    cl = centerline(depth > 0, TR, (10.0, 300.0), (990.0, 300.0))
    assert cl.hausdorff_distance(tw) > 15.0


def test_sample_raster_profile(tmp_path: Path) -> None:
    depth, _ = _sine_band()
    p = tmp_path / "d.tif"
    with rasterio.open(p, "w", driver="GTiff", width=NC, height=NR, count=1, dtype="float32",
                       transform=TR, nodata=-9999.0) as ds:
        ds.write(np.where(depth > 0, depth, -9999.0).astype("float32"), 1)
    line = LineString([(0.0, 300.0), (1000.0, 300.0)])
    ch, v = sample_raster(p, line, spacing=50.0)
    assert ch[0] == 0.0 and ch[-1] == pytest.approx(1000.0) and np.all(np.diff(ch) > 0)
    assert np.isnan(v[ch == 250.0]).all()          # y=300 is dry at x=250 (centre at y=400)
    assert v[ch == 0.0][0] == pytest.approx(2.0, abs=0.1)


def test_profile_from_cells_nearest_within_distance() -> None:
    cells = np.array([[0.0, 0.0], [100.0, 0.0], [200.0, 50.0]])
    vals = np.array([10.0, 9.0, 8.0])
    line = LineString([(0.0, 0.0), (200.0, 0.0)])
    ch, v = profile_from_cells(line, cells, vals, spacing=100.0, max_distance=20.0)
    assert ch.tolist() == [0.0, 100.0, 200.0]
    assert v[0] == 10.0 and v[1] == 9.0 and np.isnan(v[2])  # nearest cell 50 m away > 20 m

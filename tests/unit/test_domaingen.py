"""Automated domain outlines: data footprint, vertex-capped simplification, flood envelope."""

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import MultiPoint, Point, Polygon

from flowfield2d.domaingen import data_footprint, flood_envelope, simplify_to

CELL = 10.0
NX, NY = 120, 200                      # 1200 m x 2000 m grid, origin (0, 2000)
X0 = 600.0                             # valley axis (x), channel runs along y


def _dem(tmp_path: Path, nodata_left: int = 0, pit: bool = False) -> Path:
    """V valley z = 100 + 0.02 |x - X0| + 0.001 y; optional nodata strip and isolated pit."""
    xs = (np.arange(NX) + 0.5) * CELL
    ys = 2000.0 - (np.arange(NY) + 0.5) * CELL
    z = 100.0 + 0.02 * np.abs(xs[None, :] - X0) + 0.001 * ys[:, None]
    if pit:                                            # low pocket far from the channel
        z[20:30, 5:15] = 90.0
    z = z.astype("float32")
    if nodata_left:
        z[:, :nodata_left] = -9999.0
        z[:40, nodata_left:nodata_left + 20] = -9999.0  # a notch, so the footprint is an L-shape
    p = tmp_path / "dem.tif"
    with rasterio.open(p, "w", driver="GTiff", width=NX, height=NY, count=1, dtype="float32",
                       transform=from_origin(0.0, 2000.0, CELL, CELL), nodata=-9999.0) as ds:
        ds.write(z, 1)
    return p


def _n(poly: Polygon) -> int:
    return len(poly.exterior.coords) - 1


def test_simplify_to_caps_vertices_and_can_cover() -> None:
    circle = Point(0, 0).buffer(1000.0, quad_segs=250)             # ~1000 vertices
    s = simplify_to(circle, 20)
    assert s.is_valid and _n(s) <= 20
    assert s.area == pytest.approx(circle.area, rel=0.05)
    c = simplify_to(circle, 20, cover=True)
    assert c.is_valid and _n(c) <= 20 and c.buffer(1e-6).contains(circle)
    small = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    assert simplify_to(small, 20).equals(small)                    # already small: unchanged
    with pytest.raises(ValueError):
        simplify_to(circle, 2)


def test_data_footprint_l_shape(tmp_path: Path) -> None:
    fp = data_footprint(_dem(tmp_path, nodata_left=20), max_vertices=30)
    valid_area = (NX - 20) * NY * CELL**2 - 20 * 40 * CELL**2
    assert fp.is_valid and _n(fp) <= 30
    assert fp.area == pytest.approx(valid_area, rel=0.02)
    assert not fp.contains(Point(100.0, 1000.0))                   # inside the nodata strip
    assert fp.contains(Point(X0, 1000.0))


def _wet(depth: float = 2.0) -> tuple[np.ndarray, np.ndarray]:
    """Wet cells along the channel axis, WSE = bed + depth."""
    ys = np.arange(105.0, 1900.0, 30.0)
    xy = np.column_stack([np.full(ys.size, X0), ys])
    return xy, 100.0 + 0.001 * ys + depth


def test_flood_envelope_width_follows_freeboard(tmp_path: Path) -> None:
    xy, wse = _wet()
    env = flood_envelope(_dem(tmp_path), xy, wse, freeboard=3.0, max_vertices=40)
    # Ground within wse + 3 m: 0.02 |x - X0| <= 5  ->  |x - X0| <= 250 m.
    assert env.is_valid and _n(env) <= 40
    assert env.covers(MultiPoint([tuple(p) for p in xy]))
    minx, _, maxx, _ = env.bounds
    assert minx == pytest.approx(X0 - 250.0, abs=3 * CELL)
    assert maxx == pytest.approx(X0 + 250.0, abs=3 * CELL)
    wider = flood_envelope(_dem(tmp_path), xy, wse, freeboard=6.0, max_vertices=40)
    assert wider.area > env.area * 1.5


def test_flood_envelope_buffer_clip_and_isolated_low_ground(tmp_path: Path) -> None:
    dem = _dem(tmp_path, pit=True)
    xy, wse = _wet()
    env = flood_envelope(dem, xy, wse, freeboard=3.0, max_vertices=40)
    assert not env.contains(Point(100.0, 1750.0))                  # the pit is not connected
    buffered = flood_envelope(dem, xy, wse, freeboard=3.0, buffer=100.0, max_vertices=40)
    assert buffered.contains(env) and buffered.bounds[0] < env.bounds[0] - 50.0
    clip = Polygon([(0, 500), (1200, 500), (1200, 1500), (0, 1500)])
    clipped = flood_envelope(dem, xy, wse, freeboard=3.0, buffer=100.0, clip=clip, max_vertices=40)
    assert clip.buffer(1e-6).contains(clipped)


def test_flood_envelope_needs_wet_cells(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="wet"):
        flood_envelope(_dem(tmp_path), np.empty((0, 2)), np.empty(0), freeboard=3.0)


# --- scale: working resolution, windowed reads, bounded memory (R21b) ---------------------------

def test_cover_is_guaranteed_for_concave_shapes() -> None:
    star = Polygon([(np.cos(a) * (100 if i % 2 else 30), np.sin(a) * (100 if i % 2 else 30))
                    for i, a in enumerate(np.linspace(0, 2 * np.pi, 40, endpoint=False))])
    c = simplify_to(star, 4, cover=True)
    assert _n(c) <= 4 and c.covers(star)


def test_footprint_at_working_resolution(tmp_path: Path) -> None:
    fp = data_footprint(_dem(tmp_path, nodata_left=20), max_vertices=30, resolution=2 * CELL)
    valid_area = (NX - 20) * NY * CELL**2 - 20 * 40 * CELL**2
    assert fp.area == pytest.approx(valid_area, rel=0.04)


def test_envelope_window_and_resolution(tmp_path: Path) -> None:
    xy, wse = _wet()
    env = flood_envelope(_dem(tmp_path), xy, wse, freeboard=3.0, max_vertices=40,
                         resolution=2 * CELL, margin=400.0)
    minx, _, maxx, _ = env.bounds
    assert minx == pytest.approx(X0 - 250.0, abs=3 * 2 * CELL)
    assert maxx == pytest.approx(X0 + 250.0, abs=3 * 2 * CELL)
    tight = flood_envelope(_dem(tmp_path), xy, wse, freeboard=3.0, max_vertices=40, margin=100.0)
    assert tight.bounds[0] >= X0 - 100.0 - CELL and tight.bounds[2] <= X0 + 100.0 + CELL


def test_large_sparse_raster_time_and_memory(tmp_path: Path) -> None:
    import time
    import tracemalloc

    n, cell = 4000, 3.0                                   # 4000 x 4000 px, ~2 % valid corridor
    p = tmp_path / "big.tif"
    with rasterio.open(p, "w", driver="GTiff", width=n, height=n, count=1, dtype="float32",
                       transform=from_origin(0.0, n * cell, cell, cell), nodata=-9999.0,
                       tiled=True, blockxsize=256, blockysize=256, compress="deflate") as ds:
        for r0 in range(0, n, 500):
            cols = np.arange(n)
            centre = n / 2 + 300 * np.sin((np.arange(r0, r0 + 500) / n) * 2 * np.pi)[:, None]
            z = 100.0 + 0.05 * np.abs(cols[None, :] - centre) * cell
            z = np.where(np.abs(cols[None, :] - centre) < 40, z, -9999.0).astype("float32")
            ds.write(z, 1, window=rasterio.windows.Window(0, r0, n, 500))
    rows = np.arange(100, n - 100, 50)
    cx = (n / 2 + 300 * np.sin(rows / n * 2 * np.pi) + 0.5) * cell
    xy = np.column_stack([cx, (n - rows - 0.5) * cell])
    wse = np.full(rows.size, 102.0)
    tracemalloc.start()
    t0 = time.monotonic()
    fp = data_footprint(p, max_vertices=100, resolution=4 * cell)
    env = flood_envelope(p, xy, wse, freeboard=3.0, max_vertices=50, resolution=2 * cell,
                         margin=200.0, clip=fp)
    elapsed = time.monotonic() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert fp.is_valid and env.is_valid and env.area > 0
    assert elapsed < 30.0, f"{elapsed:.1f} s"
    assert peak < 300e6, f"peak {peak / 1e6:.0f} MB"            # never the full 64 MB x many copies

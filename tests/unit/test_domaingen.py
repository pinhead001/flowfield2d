"""Automated domain outlines: data footprint, vertex-capped simplification, flood envelope."""

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, MultiPoint, Point, Polygon

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


# --- domain generator helpers from the v01 benchmark (R24) ---------------------------------------

def test_valid_area_keeps_holes_and_erodes(tmp_path: Path) -> None:
    from flowfield2d.domaingen import valid_area

    p = _dem(tmp_path, nodata_left=20)
    with rasterio.open(p, "r+") as ds:                     # an interior void
        z = ds.read(1)
        z[100:110, 60:70] = -9999.0
        ds.write(z, 1)
    v = valid_area(p)
    assert sum(len(g.interiors) for g in getattr(v, "geoms", [v])) == 1
    e = valid_area(p, erode=30.0)
    assert e.area < v.area and v.buffer(-29.0).buffer(1e-6).contains(e.buffer(-1.0))
    w = valid_area(p, bounds=(400.0, 500.0, 800.0, 1500.0))
    assert w.bounds[0] >= 400.0 - CELL and w.bounds[2] <= 800.0 + CELL


def test_fit_inside_is_smooth_and_on_valid_ground(tmp_path: Path) -> None:
    from flowfield2d.domaingen import fit_inside, valid_area

    v = valid_area(_dem(tmp_path, nodata_left=20))
    big = Polygon([(0, 0), (1200, 0), (1200, 2000), (0, 2000)])
    out = fit_inside(big, v, inset=60.0, smooth=30.0)
    assert out.is_valid and isinstance(out, Polygon)
    assert v.buffer(-25.0).contains(out)                    # >= inset - smooth inside the data
    assert len(out.exterior.coords) < 40                    # staircase removed


def test_cut_between_returns_middle_and_bc_segments() -> None:
    from flowfield2d.domaingen import cut_between

    corridor = Polygon([(0, 0), (300, 0), (300, 3000), (0, 3000)])
    a = LineString([(140, 2500), (160, 2500)])              # short GUI-style BC lines, mid-channel
    b = LineString([(140, 400), (160, 400)])
    mid, la, lb = cut_between(corridor, a, b, Point(150, 1500))
    assert mid.area == pytest.approx(300 * 2100)
    assert la.length == pytest.approx(300) and lb.length == pytest.approx(300)
    assert mid.exterior.buffer(1e-6).contains(la) and mid.exterior.buffer(1e-6).contains(lb)
    with pytest.raises(ValueError):
        cut_between(corridor, a, b, Point(150, 2900))      # inside point not between the cuts


# --- domains from two points (R28) ----------------------------------------------------------------

def test_cross_line_is_the_shortest_chord_through_the_point() -> None:
    from flowfield2d.domaingen import cross_line

    corridor = Polygon([(0, 0), (300, 0), (300, 3000), (0, 3000)])
    line = cross_line(corridor, Point(100, 1500))
    assert line.length == pytest.approx(300.0, rel=0.01)           # across, not along
    assert abs(line.coords[0][1] - line.coords[-1][1]) < 10.0
    bent = Polygon([(0, 0), (300, 0), (3000, 2700), (3000, 3000), (2700, 3000), (0, 300)])
    diag = cross_line(bent, Point(1500, 1500))
    assert diag.length < 600.0                                      # across the diagonal band
    with pytest.raises(ValueError):
        cross_line(corridor, Point(1000, 1500))                     # outside


def test_cut_between_without_inside_point() -> None:
    from flowfield2d.domaingen import cross_line, cut_between

    corridor = Polygon([(0, 0), (300, 0), (300, 3000), (0, 3000)])
    a = cross_line(corridor, Point(150, 2500))
    b = cross_line(corridor, Point(150, 400))
    mid, la, lb = cut_between(corridor, a, b, None)
    assert mid.area == pytest.approx(300 * 2100, rel=0.01)


def test_cross_line_perpendicular_to_a_flow_direction() -> None:
    from flowfield2d.domaingen import cross_line

    wide = Polygon([(-1300, -100), (1300, -100), (1300, 3000), (-1300, 3000)])
    near_end = Point(0, 2900)                                       # corner chords are shorter
    line = cross_line(wide, near_end, along=(0.0, -1.0))
    assert line.length == pytest.approx(2600.0, rel=0.01)
    assert abs(line.coords[0][1] - 2900) < 1e-6 and abs(line.coords[-1][1] - 2900) < 1e-6

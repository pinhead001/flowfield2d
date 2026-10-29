"""post.inundation.smooth_outer: smooth pixel-edge polygons along the outer corners of their
stair steps, never dropping a wet pixel (synthetic masks only)."""

import numpy as np
import pytest
import rasterio.features
from rasterio.transform import from_origin
from shapely.geometry import Point, Polygon, shape
from shapely.ops import unary_union

from flowfield2d.post.inundation import SmoothReport, smooth_outer

N = 40


def _polys(mask: np.ndarray) -> list[Polygon]:
    """Pixel-edge polygons of a boolean mask on a 1-unit grid with origin (0, N)."""
    shapes = rasterio.features.shapes(mask.astype("uint8"), mask=mask,
                                      transform=from_origin(0.0, float(mask.shape[0]), 1.0, 1.0),
                                      connectivity=4)
    return [shape(g) for g, v in shapes if v == 1]


def _band() -> np.ndarray:
    r, c = np.mgrid[0:N, 0:N]
    return np.abs(r - c) <= 3                                  # diagonal stair-stepped band


def _nv(p: Polygon) -> int:
    return len(p.exterior.coords) - 1 + sum(len(r.coords) - 1 for r in p.interiors)


def _max_turn_deg(p: Polygon) -> float:
    """Largest direction change between consecutive exterior segments (90 on a pixel edge)."""
    xy = np.asarray(p.exterior.coords)[:-1]
    seg = np.roll(xy, -1, axis=0) - xy
    seg = seg[np.hypot(*seg.T) > 1e-9]
    ang = np.arctan2(seg[:, 1], seg[:, 0])
    turn = np.abs((np.diff(np.append(ang, ang[0])) + np.pi) % (2 * np.pi) - np.pi)
    return float(np.degrees(turn.max()))


def test_smooth_outer_follows_outer_corners_and_covers_every_pixel() -> None:
    raw = _polys(_band())
    assert len(raw) == 1 and _nv(raw[0]) > 100
    out, rep = smooth_outer(raw, pixel=1.0)
    assert isinstance(rep, SmoothReport)
    assert len(out) == 1 and out[0].is_valid
    assert unary_union(out).buffer(1e-9).covers(raw[0])          # no wet pixel outside
    assert _max_turn_deg(raw[0]) == pytest.approx(90.0)
    assert _max_turn_deg(out[0]) <= 50.0                          # the stair steps are gone
    assert _nv(out[0]) < 4 * _nv(raw[0])                         # smoothing, not densifying
    assert rep.n_in == 1 and rep.n_out == 1
    assert rep.area_in == pytest.approx(raw[0].area)
    assert rep.area_out == pytest.approx(out[0].area)
    assert raw[0].area < rep.area_out < 1.5 * raw[0].area
    assert 0.0 < rep.max_offset <= 2.0                           # boundary within 2 px outward
    # the boundary runs close to the outer corners: no raw vertex is more than 2 px inside it
    assert max(out[0].exterior.distance(Point(x, y)) for x, y in raw[0].exterior.coords) <= 2.0


def test_smooth_outer_is_deterministic_and_scales_with_pixel() -> None:
    raw = _polys(_band())
    a, rep1 = smooth_outer(raw, pixel=1.0)
    b, _ = smooth_outer(raw, pixel=1.0)
    assert a[0].equals_exact(b[0], 0.0)
    # the same shape drawn at 3-unit pixels smooths to the same geometry scaled by 3
    big = [Polygon([(3 * x, 3 * y) for x, y in p.exterior.coords]) for p in raw]
    c, rep3 = smooth_outer(big, pixel=3.0)
    assert c[0].area == pytest.approx(9 * a[0].area, rel=1e-6)
    assert rep3.max_offset == pytest.approx(3 * rep1.max_offset, rel=1e-3)


def test_smooth_outer_drops_specks_and_keeps_them_by_default() -> None:
    m = _band()
    m[35, 5] = True                                              # a one-pixel speck
    m[5, 34:36] = True                                           # a two-pixel speck
    raw = _polys(m)
    assert len(raw) == 3
    out, rep = smooth_outer(raw, pixel=1.0)
    assert rep.n_in == 3 and rep.n_out == 3 and len(out) == 3
    out, rep = smooth_outer(raw, pixel=1.0, min_area=1.5)
    assert rep.n_out == 2 and len(out) == 2
    out, rep = smooth_outer(raw, pixel=1.0, min_area=3.0)
    assert rep.n_out == 1 and len(out) == 1
    assert rep.area_in == pytest.approx(sum(p.area for p in raw))   # area_in = all input


def test_smooth_outer_holes_shrink_or_fill_but_never_grow() -> None:
    m = np.zeros((N, N), dtype=bool)
    m[5:30, 5:30] = True                                         # 25 x 25 block
    m[10, 10] = False                                            # one-pixel hole
    m[15:21, 15:21] = False                                      # 6 x 6 hole
    raw = _polys(m)
    assert len(raw) == 1 and len(raw[0].interiors) == 2
    big_hole = max((Polygon(r) for r in raw[0].interiors), key=lambda h: h.area)
    out, rep = smooth_outer(raw, pixel=1.0)                       # closing fills the 1-px hole
    assert len(out) == 1 and out[0].is_valid and len(out[0].interiors) == 1
    hole = Polygon(out[0].interiors[0])
    assert big_hole.buffer(1e-9).covers(hole) and hole.area < big_hole.area
    assert out[0].buffer(1e-9).covers(raw[0])
    # no closing: min_hole fills the small hole, the large one survives
    out, rep = smooth_outer(raw, pixel=1.0, closing=0.0, min_hole=2.0)
    assert len(out) == 1 and len(out[0].interiors) == 1 and out[0].buffer(1e-9).covers(raw[0])
    # a hole larger than min_hole is kept even when closing is off and min_hole is large-ish
    out, rep = smooth_outer(raw, pixel=1.0, closing=0.0, min_hole=30.0)
    assert len(out[0].interiors) == 1


def _blob() -> np.ndarray:
    """A jagged 200 x 200 mask with holes (deterministic noise, thresholded and smoothed)."""
    rng = np.random.default_rng(7)
    noise = rng.random((200, 200))
    from scipy.ndimage import uniform_filter
    field = uniform_filter(noise, size=15)
    return field > np.quantile(field, 0.55)


def test_smooth_outer_output_vertex_count_is_bounded() -> None:
    raw = [p for p in _polys(_blob()) if p.area > 50]
    nv_raw = sum(_nv(p) for p in raw)
    assert nv_raw > 2000
    out, rep = smooth_outer(raw, pixel=1.0)
    assert sum(_nv(p) for p in out) <= 2 * nv_raw            # the final simplify keeps it lean
    assert unary_union(out).buffer(1e-9).covers(unary_union(raw))
    dense, _ = smooth_outer(raw, pixel=1.0, final_simplify=0.0)
    assert sum(_nv(p) for p in dense) > 3 * nv_raw           # round joins + Chaikin densify
    assert unary_union(dense).buffer(1e-9).covers(unary_union(raw))
    with pytest.raises(ValueError):
        smooth_outer(raw, pixel=1.0, final_simplify=-0.1)


def test_outward_offset_matches_brute_force() -> None:
    from flowfield2d.post.inundation import _outward_offset
    raw = _polys(_blob())
    big = max(raw, key=lambda p: p.area)
    out, _ = smooth_outer([big], pixel=1.0)
    for piece in out:
        coords = np.vstack([np.asarray(r.coords) for r in (piece.exterior, *piece.interiors)])
        brute = float(np.max([big.distance(Point(x, y)) for x, y in coords]))
        assert _outward_offset(big, piece) == pytest.approx(brute, abs=1e-9)
    assert _outward_offset(big, Polygon(big.exterior)) == 0.0   # nothing outside


def test_smooth_outer_empty_and_invalid_arguments() -> None:
    out, rep = smooth_outer([], pixel=1.0)
    assert out == [] and rep == SmoothReport(0, 0, 0.0, 0.0, 0.0)
    raw = _polys(_band())
    with pytest.raises(ValueError):
        smooth_outer(raw, pixel=0.0)
    with pytest.raises(ValueError):
        smooth_outer(raw, pixel=1.0, closing=-1.0)
    with pytest.raises(ValueError):
        smooth_outer(raw, pixel=1.0, iterations=-1)

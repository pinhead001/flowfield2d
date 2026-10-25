"""Chained channel patches between two bank lines (engine-neutral geometry for quad meshing)."""

import numpy as np
import pytest
from shapely.geometry import LineString, Point
from shapely.ops import substring

from flowfield2d.channel_patches import channel_patches, smooth_line


def _straight(length: float) -> tuple[LineString, LineString, LineString]:
    left = LineString([(0, 10), (length, 10)])
    right = LineString([(0, 0), (length, 0)])
    centre = LineString([(0, 5), (length, 5)])
    return left, right, centre


def test_regular_patches_share_their_cross_sections() -> None:
    left, right, centre = _straight(100.0)
    p = channel_patches(left, right, centre, spacing=25.0)
    assert len(p.cross_sections) == 5 and len(p.patches) == 4
    assert [round(c.coords[0][0], 6) for c in p.cross_sections] == [0, 25, 50, 75, 100]
    for c in p.cross_sections:                     # left bank end first, then right bank end
        (x0, y0), (x1, y1) = c.coords[0], c.coords[-1]
        assert (y0, y1) == pytest.approx((10.0, 0.0)) and x0 == pytest.approx(x1)
    assert len(p.left) == len(p.right) == 4
    for i in range(4):                             # bank pieces end exactly on the cross-sections
        assert p.left[i].coords[0] == p.cross_sections[i].coords[0]
        assert p.left[i].coords[-1] == p.cross_sections[i + 1].coords[0]
        assert p.right[i].coords[0] == p.cross_sections[i].coords[-1]
        assert p.right[i].coords[-1] == p.cross_sections[i + 1].coords[-1]
        assert p.patches[i].area == pytest.approx(250.0)
        assert p.patches[i].is_valid


def test_short_remainder_merges_into_the_last_patch() -> None:
    left, right, centre = _straight(110.0)
    p = channel_patches(left, right, centre, spacing=25.0)
    assert [round(c.coords[0][0], 6) for c in p.cross_sections] == [0, 25, 50, 75, 110]
    p2 = channel_patches(*_straight(115.0), spacing=25.0)    # remainder 15 >= spacing / 2: kept
    assert [round(c.coords[0][0], 6) for c in p2.cross_sections] == [0, 25, 50, 75, 100, 115]


def test_bends_follow_the_banks() -> None:
    left = LineString([(0, 10), (50, 10), (90, 50)])
    right = LineString([(0, 0), (54, 0), (100, 46)])
    centre = LineString([(0, 5), (52, 5), (95, 48)])
    p = channel_patches(left, right, centre, spacing=20.0)
    assert all(pt.is_valid and pt.area > 0 for pt in p.patches)
    total = sum(pt.area for pt in p.patches)
    channel = p.patches[0]
    for pt in p.patches[1:]:
        channel = channel.union(pt)
    assert channel.area == pytest.approx(total, rel=1e-9)          # no overlaps
    for c in p.cross_sections:                     # ends on the banks; interior clear of both
        inner = substring(c, 0.01, 0.99, normalized=True)
        assert not inner.intersects(left) and not inner.intersects(right)
        assert left.distance(Point(c.coords[0])) < 1e-9
        assert right.distance(Point(c.coords[-1])) < 1e-9


def test_invalid_inputs() -> None:
    left, right, centre = _straight(100.0)
    with pytest.raises(ValueError):
        channel_patches(left, right, centre, spacing=0.0)
    with pytest.raises(ValueError):
        channel_patches(left, right, centre, spacing=150.0)        # fewer than one patch


def test_smooth_line_keeps_ends_and_removes_the_staircase() -> None:
    stairs = LineString([(i // 2 * 3.0 + (i % 2) * 3.0, i // 2 * 3.0) for i in range(21)])
    s = smooth_line(stairs, iterations=3)
    assert s.coords[0] == stairs.coords[0] and s.coords[-1] == stairs.coords[-1]
    assert s.length < stairs.length
    xy = np.asarray(s.coords)
    turn = np.abs(np.diff(np.arctan2(np.diff(xy[:, 1]), np.diff(xy[:, 0]))))
    assert turn.max() < np.pi / 4                                   # no 90 degree corners left
    assert smooth_line(stairs, iterations=0).equals(stairs)
    with pytest.raises(ValueError):
        smooth_line(stairs, iterations=-1)

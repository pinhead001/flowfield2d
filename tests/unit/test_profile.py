"""Tests for flowfield2d.post.profile: banded deepest-cell profiles and centerline tracing."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from shapely.geometry import LineString

from flowfield2d.post.profile import BandPoint, band_profile, profile_along, trace_centerline

# (x, y, depth); band = 10 along y, min y = 0 so bands are [0,10), [10,20), [20,30).
CELLS = [
    (0.0, 0.0, 0.1), (0.0, 2.0, 1.0), (5.0, 3.0, 2.0), (9.0, 4.0, 0.2),  # band 0
    (1.0, 12.0, 3.0), (2.0, 15.0, 0.4),  # band 1: only one cell > 0.5 -> skipped
    (3.0, 21.0, 0.6), (4.0, 25.0, 0.7), (6.0, 28.0, 0.9),  # band 2
]


def _points(xs: list[float], ys: list[float]) -> list[BandPoint]:
    return [BandPoint(y, x, y, 1.0, 100.0) for x, y in zip(xs, ys, strict=True)]


def test_band_profile_deepest_per_band() -> None:
    xy = np.array([(x, y) for x, y, _ in CELLS])
    depth = np.array([d for _, _, d in CELLS])
    wse = 100.0 + depth
    pts = sorted(band_profile(xy, depth, wse, band=10.0), key=lambda p: p.y)
    assert [(p.x, p.y) for p in pts] == [(5.0, 3.0), (6.0, 28.0)]
    assert [p.depth for p in pts] == pytest.approx([2.0, 0.9])
    assert [p.wse for p in pts] == pytest.approx([102.0, 100.9])


def test_band_profile_axis0() -> None:
    xy = np.array([(y, x) for x, y, _ in CELLS])  # swap columns
    depth = np.array([d for _, _, d in CELLS])
    pts = sorted(band_profile(xy, depth, depth, band=10.0, axis=0), key=lambda p: p.x)
    assert [(p.x, p.y) for p in pts] == [(3.0, 5.0), (28.0, 6.0)]


def test_band_point_frozen() -> None:
    p = BandPoint(0.0, 1.0, 2.0, 3.0, 4.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.depth = 5.0  # type: ignore[misc]


def test_trace_centerline_k1_sorts_descending() -> None:
    line = trace_centerline(_points([1.0, 2.0, 3.0], [10.0, 30.0, 20.0]), k=1)
    assert isinstance(line, LineString)
    assert list(line.coords) == [(2.0, 30.0), (3.0, 20.0), (1.0, 10.0)]


def test_trace_centerline_ascending() -> None:
    line = trace_centerline(_points([1.0, 2.0, 3.0], [10.0, 30.0, 20.0]), k=1, descending=False)
    assert list(line.coords) == [(1.0, 10.0), (3.0, 20.0), (2.0, 30.0)]


def test_trace_centerline_smooths_interior() -> None:
    pts = _points([0.0, 10.0, 0.0, 10.0, 0.0], [0.0, 10.0, 20.0, 30.0, 40.0])
    c = np.array(trace_centerline(pts, k=3).coords)
    assert c.shape == (5, 2)
    assert c[0, 1] > c[-1, 1]  # upstream (high y) first
    np.testing.assert_allclose(c[1:4, 0], [10.0 / 3, 20.0 / 3, 10.0 / 3])
    np.testing.assert_allclose(c[1:4, 1], [30.0, 20.0, 10.0])


def test_profile_along_sorted_by_chainage() -> None:
    cl = LineString([(0.0, 40.0), (0.0, 0.0)])
    pts = [BandPoint(0.0, 1.0, 0.0, 1.0, 100.0), BandPoint(40.0, -2.0, 40.0, 1.0, 102.0),
           BandPoint(20.0, 3.0, 20.0, 1.0, 101.0)]
    ch, wse = profile_along(cl, pts)
    np.testing.assert_allclose(ch, [0.0, 20.0, 40.0])
    np.testing.assert_allclose(wse, [102.0, 101.0, 100.0])

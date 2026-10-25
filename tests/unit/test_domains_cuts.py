"""Tests for cut_line and keep_polygon in flowfield2d.domains."""

from __future__ import annotations

import pytest
from shapely import affinity
from shapely.geometry import LineString, Polygon, box

from flowfield2d.domains import cut_line, keep_polygon

AREA: Polygon = box(0.0, 0.0, 300.0, 3000.0)
# Upstream at high y; chainage 0 at (150, 3000), length 3000.
CL = LineString([(150.0, 3000.0), (150.0, 0.0)])


def test_cut_line_clipped_to_area() -> None:
    cut = cut_line(AREA, CL, 1000.0, 500.0)
    assert isinstance(cut, LineString)
    assert cut.length == pytest.approx(300.0)
    assert AREA.buffer(1e-6).contains(cut)
    ys = {round(y, 6) for _, y in cut.coords}
    assert ys == {2000.0}


def test_cut_line_inside_unchanged() -> None:
    cut = cut_line(AREA, CL, 1000.0, 100.0)
    assert cut.length == pytest.approx(200.0)
    xs = sorted(round(x, 6) for x, _ in cut.coords)
    assert xs == [50.0, 250.0]


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (1000.0, 2500.0, 300.0 * 1500.0),
        (0.0, 1000.0, 300.0 * 1000.0),
        (2000.0, 3000.0, 300.0 * 1000.0),
        (0.0, 3000.0, 300.0 * 3000.0),
    ],
)
def test_keep_polygon_areas(start: float, end: float, expected: float) -> None:
    kept = keep_polygon(AREA, CL, start, end, 500.0)
    assert kept.area == pytest.approx(expected, rel=1e-6)


def test_keep_polygon_location() -> None:
    kept = keep_polygon(AREA, CL, 1000.0, 2500.0, 500.0)
    minx, miny, maxx, maxy = kept.bounds
    assert minx == pytest.approx(0.0)
    assert maxx == pytest.approx(300.0)
    assert miny == pytest.approx(500.0)
    assert maxy == pytest.approx(2000.0)


def test_oblique_rotated_case() -> None:
    area = affinity.rotate(AREA, 30.0, origin=(0.0, 0.0))
    cl = affinity.rotate(CL, 30.0, origin=(0.0, 0.0))
    cut = cut_line(area, cl, 1500.0, 1000.0)
    assert cut.length == pytest.approx(300.0)
    assert area.buffer(1e-6).contains(cut)
    kept = keep_polygon(area, cl, 1000.0, 2500.0, 1000.0)
    assert kept.area == pytest.approx(450000.0, rel=1e-6)
    assert area.buffer(1e-6).contains(kept)


@pytest.mark.parametrize(("start", "end"), [(1000.0, 1000.0), (2000.0, 1000.0)])
def test_keep_polygon_bad_order_raises(start: float, end: float) -> None:
    with pytest.raises(ValueError):
        keep_polygon(AREA, CL, start, end, 500.0)

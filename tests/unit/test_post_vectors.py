"""Velocity vector helpers: compass direction and nearest-vector sampling on a grid."""

from __future__ import annotations

import numpy as np
from rasterio.transform import from_origin

from flowfield2d.post.vectors import NearestVectors, direction_deg


def test_direction_is_a_compass_bearing_clockwise_from_north() -> None:
    vx = np.array([1.0, 0.0, 0.0, -1.0, 0.0, np.nan])
    vy = np.array([0.0, 1.0, -1.0, 0.0, 0.0, 1.0])
    d = direction_deg(vx, vy)
    np.testing.assert_allclose(d[:4], [90.0, 0.0, 180.0, 270.0])
    assert np.isnan(d[4]) and np.isnan(d[5])          # no flow, no direction


def test_nearest_vectors_sample_unit_direction_inside_the_mask() -> None:
    xy = np.array([[0.5, 0.5], [3.5, 0.5], [9.0, 9.0]])
    uv = np.array([[2.0, 0.0], [0.0, -1.0], [np.nan, np.nan]])   # the NaN row is dropped
    nv = NearestVectors(xy, uv)
    assert nv.n == 2
    ux, uy = nv.unit_at(np.array([0.4, 3.0]), np.array([0.6, 0.0]))
    np.testing.assert_allclose(ux, [1.0, 0.0])
    np.testing.assert_allclose(uy, [0.0, -1.0])
    mask = np.array([[True, False, True, True]])
    ux, uy = nv.window(from_origin(0.0, 1.0, 1.0, 1.0), (1, 4), mask)
    np.testing.assert_allclose(ux[0], [1.0, np.nan, 0.0, 0.0])
    np.testing.assert_allclose(uy[0], [0.0, np.nan, -1.0, -1.0])


def test_nearest_vectors_without_points_gives_nan() -> None:
    nv = NearestVectors(np.zeros((0, 2)), np.zeros((0, 2)))
    ux, uy = nv.window(from_origin(0.0, 1.0, 1.0, 1.0), (1, 2), np.ones((1, 2), dtype=bool))
    assert np.isnan(ux).all() and np.isnan(uy).all()

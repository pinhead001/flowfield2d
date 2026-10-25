"""Small WSE rises as info, isolated wet regions (pits), metrics with excluded cells."""

import numpy as np
import pytest

from flowfield2d.post.inundation import isolated_wet
from flowfield2d.post.metrics import METRIC_COLUMNS, feature_metrics
from flowfield2d.qa.checks import wse_monotonic


def test_wse_rises_within_tol_are_reported_as_info() -> None:
    station = np.array([0.0, 100.0, 200.0, 300.0, 400.0])
    wse = np.array([10.0, 9.5, 9.53, 9.0, 9.02])           # rises 0.03 at 200 and 0.02 at 400
    r = wse_monotonic(station, wse, tol=0.1)
    assert r.ok and r.value == 0.0
    assert r.detail == "info: 2 rise(s) within tolerance, max 0.030 at station 200"
    strict = wse_monotonic(station, wse, tol=0.025)
    assert not strict.ok and strict.value == pytest.approx(0.03)
    assert strict.detail == ("rise 0.030 at station 200; "
                             "info: 1 rise(s) within tolerance, max 0.020 at station 400")


def test_wse_info_absent_when_monotonic_and_exceptions_skip_info() -> None:
    station = np.array([0.0, 100.0, 200.0])
    assert wse_monotonic(station, np.array([3.0, 2.0, 1.0]), tol=0.1).detail == ""
    r = wse_monotonic(station, np.array([3.0, 3.05, 1.0]), exceptions=[100.0], tol=0.1)
    assert r.ok and r.detail == ""


def test_isolated_wet_finds_components_not_touching_the_reference() -> None:
    depth = np.array([[1.0, 1.0, 0.0, 0.5],
                      [0.0, 1.0, 0.0, 0.5],
                      [0.0, 0.0, 0.0, 0.0],
                      [2.0, 0.0, 0.3, np.nan]])
    channel = np.zeros(depth.shape, dtype=bool)
    channel[0, 0] = True                                   # the main channel touches cell (0, 0)
    pits = isolated_wet(depth, channel)
    assert pits.dtype == bool and pits.shape == depth.shape
    expected = np.zeros(depth.shape, dtype=bool)
    expected[0:2, 3] = True                                # pond on the right
    expected[3, 0] = expected[3, 2] = True                 # single-cell ponds (4-connectivity)
    assert np.array_equal(pits, expected)
    assert not isolated_wet(depth, channel, min_depth=0.4)[3, 2]   # 0.3 is dry at min_depth 0.4
    assert not isolated_wet(depth, np.ones(depth.shape, dtype=bool)).any()


def test_isolated_wet_rejects_mismatched_shapes() -> None:
    with pytest.raises(ValueError):
        isolated_wet(np.ones((2, 2)), np.ones((3, 2), dtype=bool))


def test_feature_metrics_excludes_cells_from_statistics_not_from_area() -> None:
    depth = np.array([[1.0, 2.0], [3.0, 9.0]])
    vel = np.array([[1.0, 1.0], [1.0, 5.0]])
    mask = np.ones(depth.shape, dtype=bool)
    pit = np.array([[False, False], [False, True]])
    m = feature_metrics("f", "s", depth, vel, mask, cell_area=2.0, length=4.0, exclude_mask=pit)
    assert m["wetted_area"] == 8.0                          # all four wet cells
    assert m["excluded_area"] == 2.0                        # the pit cell
    assert m["depth_max"] == 3.0 and m["depth_mean"] == pytest.approx(2.0)
    assert m["velocity_max"] == 1.0
    assert m["depth_p50"] == pytest.approx(2.0)
    plain = feature_metrics("f", "s", depth, vel, mask, cell_area=2.0, length=4.0)
    assert plain["depth_max"] == 9.0 and np.isnan(plain["excluded_area"])
    assert "excluded_area" in METRIC_COLUMNS and set(METRIC_COLUMNS) <= set(m)
    with pytest.raises(ValueError):
        feature_metrics("f", "s", depth, vel, mask, cell_area=2.0, length=4.0,
                        exclude_mask=np.ones((3, 3), dtype=bool))

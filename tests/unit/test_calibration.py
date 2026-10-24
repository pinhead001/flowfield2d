import numpy as np
import pytest

from flowfield2d.qa.calibration import Observation, best_n, compare, modeled_wse_at


def test_modeled_wse_interpolates_rating_and_refuses_extrapolation() -> None:
    q = np.array([10.0, 20.0, 40.0])
    wse = np.array([100.0, 101.0, 102.0])
    assert modeled_wse_at(q, wse, 30.0) == pytest.approx(101.5)
    assert modeled_wse_at(q[::-1], wse[::-1], 15.0) == pytest.approx(100.5)   # any input order
    with pytest.raises(ValueError):
        modeled_wse_at(q, wse, 50.0)


def test_compare_applies_datum_offset_and_tolerance() -> None:
    ratings = {"g1": (np.array([10.0, 40.0]), np.array([100.0, 103.0])),
               "g2": (np.array([5.0, 15.0]), np.array([50.0, 51.0]))}
    obs = [Observation("g1", q=20.0, stage=1.0, datum_offset=100.0),   # model 101.0 -> d 0.0
           Observation("g1", q=30.0, stage=2.2, datum_offset=100.0),   # model 102.0 -> d -0.2
           Observation("g2", q=10.0, stage=0.4, datum_offset=50.0),    # model 50.5  -> d +0.1
           Observation("g9", q=1.0, stage=0.0, datum_offset=0.0)]      # no rating -> skipped
    r = compare(ratings, obs, tol=0.15)
    assert r.n_used == 3 and r.skipped == ["g9"]
    assert r.mean_abs == pytest.approx(0.1) and r.ok
    assert [round(d, 6) for d in r.deltas] == [0.0, -0.2, 0.1]
    assert r.by_gage["g1"] == pytest.approx(0.1)
    assert not compare(ratings, obs, tol=0.05).ok


def test_best_n_within_bounds() -> None:
    sweep = {0.020: 0.05, 0.030: 0.08, 0.045: 0.04, 0.070: 0.01}
    n, err = best_n(sweep, n_min=0.025, n_max=0.060)
    assert n == 0.045 and err == 0.04
    with pytest.raises(ValueError):
        best_n({0.02: 0.1}, n_min=0.025, n_max=0.060)

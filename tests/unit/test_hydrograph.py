import numpy as np
import pytest

from flowfield2d.hydrograph import (
    LateralInflowWarning,
    Plateau,
    breakpoints,
    lateral_inflow,
    plateaus,
    sample,
)


def test_breakpoints_and_plateaus() -> None:
    assert breakpoints([10, 20], ramp_s=100, hold_s=300) == [
        (0.0, 10.0), (300.0, 10.0), (400.0, 20.0), (700.0, 20.0)]
    assert plateaus([10, 20], ramp_s=100, hold_s=300) == [
        Plateau(10.0, 0.0, 300.0), Plateau(20.0, 400.0, 700.0)]
    assert breakpoints([5], ramp_s=1, hold_s=60) == [(0.0, 5.0), (60.0, 5.0)]


@pytest.mark.parametrize("flows,ramp,hold", [
    ([], 1, 1), ([20, 10], 1, 1), ([-1, 2], 1, 1), ([1, 2], 0, 1), ([1, 2], 1, 0)])
def test_breakpoints_rejects(flows: list[float], ramp: float, hold: float) -> None:
    with pytest.raises(ValueError):
        breakpoints(flows, ramp_s=ramp, hold_s=hold)


def test_sample_linear_and_includes_end() -> None:
    t, q = sample(breakpoints([10, 20], 100, 300), dt_s=50)
    assert t[0] == 0 and t[-1] == 700 and len(t) == 15
    assert q[t.tolist().index(350.0)] == pytest.approx(15.0)
    t2, _ = sample([(0.0, 1.0), (130.0, 1.0)], dt_s=60)
    assert t2.tolist() == [0.0, 60.0, 120.0, 130.0]
    with pytest.raises(ValueError):
        sample([(0.0, 1.0), (1.0, 1.0)], dt_s=0)


def test_lateral_inflow_floored_with_warning() -> None:
    with pytest.warns(LateralInflowWarning, match="1"):
        out = lateral_inflow(np.array([5.0, 10.0, 8.0]), np.array([3.0, 12.0, 8.0]))
    assert out.tolist() == [2.0, 0.0, 0.0]
    with pytest.raises(ValueError):
        lateral_inflow([1.0, 2.0], [1.0])


def test_sample_rejects_empty_points() -> None:
    with pytest.raises(ValueError):
        sample([], dt_s=60)

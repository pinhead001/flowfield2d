"""Tests for per-flow hold variants of breakpoints/plateaus."""

from __future__ import annotations

import pytest

from flowfield2d.hydrograph import (
    Plateau,
    breakpoints,
    breakpoints_holds,
    plateaus,
    plateaus_holds,
)


def test_breakpoints_holds_hand_computed() -> None:
    pts = breakpoints_holds([10.0, 20.0, 40.0], ramp_s=100.0, holds_s=[300.0, 500.0, 200.0])
    assert pts == [
        (0.0, 10.0),
        (300.0, 10.0),
        (400.0, 20.0),
        (900.0, 20.0),
        (1000.0, 40.0),
        (1200.0, 40.0),
    ]


def test_plateaus_holds_hand_computed() -> None:
    pls = plateaus_holds([10.0, 20.0, 40.0], ramp_s=100.0, holds_s=[300.0, 500.0, 200.0])
    assert pls == [
        Plateau(10.0, 0.0, 300.0),
        Plateau(20.0, 400.0, 900.0),
        Plateau(40.0, 1000.0, 1200.0),
    ]


def test_single_flow() -> None:
    assert breakpoints_holds([5.0], ramp_s=60.0, holds_s=[120.0]) == [(0.0, 5.0), (120.0, 5.0)]
    assert plateaus_holds([5.0], ramp_s=60.0, holds_s=[120.0]) == [Plateau(5.0, 0.0, 120.0)]


def test_equal_holds_match_existing_functions() -> None:
    flows = [1.0, 2.5, 7.0, 7.0]
    assert breakpoints_holds(flows, 90.0, [600.0] * 4) == breakpoints(flows, 90.0, 600.0)
    assert plateaus_holds(flows, 90.0, [600.0] * 4) == plateaus(flows, 90.0, 600.0)


@pytest.mark.parametrize("holds", [[100.0], [100.0, 100.0, 100.0]])
def test_length_mismatch_raises(holds: list[float]) -> None:
    with pytest.raises(ValueError):
        breakpoints_holds([1.0, 2.0], 10.0, holds)
    with pytest.raises(ValueError):
        plateaus_holds([1.0, 2.0], 10.0, holds)


@pytest.mark.parametrize("bad", [0.0, -5.0])
def test_non_positive_hold_raises(bad: float) -> None:
    with pytest.raises(ValueError):
        breakpoints_holds([1.0, 2.0], 10.0, [100.0, bad])
    with pytest.raises(ValueError):
        plateaus_holds([1.0, 2.0], 10.0, [bad, 100.0])


def test_other_validation_kept() -> None:
    with pytest.raises(ValueError):
        breakpoints_holds([2.0, 1.0], 10.0, [100.0, 100.0])
    with pytest.raises(ValueError):
        breakpoints_holds([1.0, 2.0], 0.0, [100.0, 100.0])

"""Tests for cut_slope_with_fallback and SlopeChoice."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from flowfield2d.slope import SlopeChoice, cut_slope_with_fallback

CH = np.arange(0.0, 1001.0, 50.0)
WSE_ADVERSE = 100.0 + 0.002 * CH  # rises downstream -> adverse
WSE_DOWN = 100.0 - 0.004 * CH  # falls downstream -> slope 0.004


def test_primary_valid_used() -> None:
    c = cut_slope_with_fallback("specified", "specified", at=500.0, window=200.0,
                                primary_kw={"value": 0.003}, fallback_kw={"value": 0.001})
    assert isinstance(c, SlopeChoice)
    assert c.slope == pytest.approx(0.003)
    assert c.source == "specified"
    assert c.rejected is None


def test_primary_adverse_falls_back() -> None:
    c = cut_slope_with_fallback("wse", "specified", at=500.0, window=200.0,
                                primary_kw={"chainage": CH, "wse": WSE_ADVERSE},
                                fallback_kw={"value": 0.001})
    assert c.slope == pytest.approx(0.001)
    assert c.source == "specified"
    assert isinstance(c.rejected, str) and c.rejected
    assert "wse" in c.rejected


def test_primary_flat_falls_back() -> None:
    c = cut_slope_with_fallback("specified", "wse", at=500.0, window=200.0, side="upstream",
                                primary_kw={"value": 0.0},
                                fallback_kw={"chainage": CH, "wse": WSE_DOWN})
    assert c.slope == pytest.approx(0.004)
    assert c.source == "wse"
    assert c.rejected is not None and "specified" in c.rejected


def test_primary_raising_falls_back() -> None:
    c = cut_slope_with_fallback("specified", "wse", at=500.0, window=200.0,
                                primary_kw={}, fallback_kw={"chainage": CH, "wse": WSE_DOWN})
    assert c.slope == pytest.approx(0.004)
    assert c.source == "wse"
    assert c.rejected is not None and "specified" in c.rejected


def test_negative_specified_primary_rejected() -> None:
    c = cut_slope_with_fallback("specified", "specified", at=0.0, window=1.0,
                                primary_kw={"value": -0.01}, fallback_kw={"value": 0.005})
    assert c.slope == pytest.approx(0.005)
    assert c.rejected


def test_both_rejected_raises() -> None:
    with pytest.raises(ValueError):
        cut_slope_with_fallback("wse", "specified", at=500.0, window=200.0,
                                primary_kw={"chainage": CH, "wse": WSE_ADVERSE},
                                fallback_kw={"value": 0.0})


def test_slope_choice_is_frozen() -> None:
    c = SlopeChoice(slope=0.001, source="specified", rejected=None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.slope = 0.002  # type: ignore[misc]

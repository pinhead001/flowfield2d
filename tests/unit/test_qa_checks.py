import numpy as np
import pytest

from rasdrive.qa.checks import (
    CheckResult,
    bc_sensitivity,
    convergence,
    determinism,
    overlap,
    volume_balance,
    wet_dry,
    wse_monotonic,
)


def test_volume_balance() -> None:
    r = volume_balance(np.array([100.0, 100.0]), np.array([100.5, 100.5]), tol=0.01)
    assert isinstance(r, CheckResult) and r.ok and r.value == pytest.approx(0.005)
    assert not volume_balance(np.array([100.0]), np.array([103.0]), tol=0.01).ok
    with pytest.raises(ValueError):
        volume_balance(np.array([0.0]), np.array([1.0]))


def test_convergence_uses_end_of_hold_window() -> None:
    t = np.arange(0, 3601, 600.0)                  # 0..3600 s
    q_in = np.full(t.size, 50.0)
    q_out = np.array([10, 30, 45, 49, 49.8, 49.9, 50.0])
    wse = np.column_stack([np.array([1, 1.5, 1.8, 1.998, 1.999, 2.0, 2.0]),
                           np.array([3, 3.2, 3.3, 3.400, 3.401, 3.402, 3.403])])
    ok = convergence(t, q_in, q_out, wse, hold_end_s=3600, window_s=1800, q_tol=0.01, wse_tol=0.005)
    assert ok.ok, ok.detail
    early = convergence(t, q_in, q_out, wse, hold_end_s=1800, window_s=1800)
    assert not early.ok


def test_wse_monotonic_with_exceptions() -> None:
    station = np.array([0.0, 100.0, 200.0, 300.0])     # increasing downstream
    wse = np.array([10.0, 9.5, 9.6, 9.0])               # rise at index 2
    r = wse_monotonic(station, wse)
    assert not r.ok and "200" in r.detail
    assert wse_monotonic(station, wse, tol=0.2).ok
    assert wse_monotonic(station, wse, exceptions=[200.0]).ok
    shuffled = wse_monotonic(station[::-1], wse[::-1])
    assert not shuffled.ok                              # order comes from station, not input order


def test_bc_sensitivity_overlap_determinism() -> None:
    base = np.array([1.0, 2.0, np.nan])
    assert bc_sensitivity(base, base + 0.02, base - 0.01, tol=0.03).ok
    r = bc_sensitivity(base, base + 0.04, base, tol=0.03)
    assert not r.ok and r.value == pytest.approx(0.04)
    assert overlap(np.array([1.0, np.nan]), np.array([1.04, 5.0]), tol=0.05).ok
    d = determinism(np.ones(3), np.ones(3), tol=0.0)
    assert d.ok and "identical" in d.detail
    assert not determinism(np.ones(3), np.ones(3) + 1e-3, tol=1e-4).ok
    with pytest.raises(ValueError):
        overlap(np.ones(2), np.ones(3))


def test_wet_dry() -> None:
    assert wet_dry(np.array([0.0, 0.5, 1.2])).ok
    neg = wet_dry(np.array([0.1, -0.01]))
    assert not neg.ok and "negative" in neg.detail
    assert not wet_dry(np.array([0.1, np.nan]), allow_nan=False).ok
    assert wet_dry(np.array([0.1, np.nan])).ok

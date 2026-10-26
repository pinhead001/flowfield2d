import numpy as np
import pytest

from flowfield2d.qa.checks import CheckResult, ConvergenceResult, convergence

T = np.arange(0, 3601, 900.0)          # 0, 900, 1800, 2700, 3600; a 1800 s window keeps the last 3
Q = np.full(T.size, 50.0)


def test_counts_failing_points() -> None:
    wse = np.column_stack([
        [1.0, 1.0, 1.0, 1.0, 1.0],         # steady
        [1.0, 1.2, 1.4, 1.6, 1.8],         # still filling
        [2.0, 2.0, 2.0, 2.001, 2.002],     # within tolerance
        [3.0, 3.1, 3.2, 3.3, 3.4],         # still filling
    ])
    r = convergence(T, Q, Q, wse, hold_end_s=3600, window_s=1800)
    assert isinstance(r, ConvergenceResult) and isinstance(r, CheckResult)
    assert not r.ok
    assert (r.n_failing, r.n_points) == (2, 4)
    assert r.oscillating == ()
    assert "2/4" in r.detail


def test_flags_aba_oscillation() -> None:
    wse = np.column_stack([
        [0.79, 0.75, 0.79, 0.75, 0.79],    # A/B/A in the window
        [1.0, 1.0, 1.0, 1.0, 1.0],
        [1.0, 1.2, 1.4, 1.6, 1.8],         # monotone filling is not oscillation
    ])
    r = convergence(T, Q, Q, wse, hold_end_s=3600, window_s=1800)
    assert not r.ok
    assert r.n_failing == 2
    assert r.oscillating == (0,)
    assert "oscillat" in r.detail


def test_converged_has_no_failures() -> None:
    r = convergence(T, Q, Q, np.full(T.size, 5.0), hold_end_s=3600, window_s=1800)
    assert r.ok and (r.n_failing, r.n_points) == (0, 1) and r.oscillating == ()


def test_oscillation_outside_window_ignored() -> None:
    r = convergence(T, Q, Q, np.array([1.0, 1.5, 1.0, 1.0, 1.0]), hold_end_s=3600, window_s=1800)
    assert r.ok and r.oscillating == ()


def test_convergence_without_flows_uses_wse_only_and_says_so() -> None:
    t = np.arange(0.0, 3600.0 + 1, 900.0)
    w = np.full((t.size, 2), 10.0)
    r = convergence(t, None, None, w, hold_end_s=3600.0, window_s=1800.0)
    assert r.ok and "flow balance not available" in r.detail
    w[-1, 1] = 10.5
    assert not convergence(t, None, None, w, hold_end_s=3600.0).ok


def test_convergence_rejects_zero_inflow_data() -> None:
    t = np.arange(0.0, 3600.0 + 1, 900.0)
    zeros = np.zeros(t.size)
    with pytest.raises(ValueError, match="inflow"):
        convergence(t, zeros, zeros, np.full(t.size, 10.0), hold_end_s=3600.0)
    with pytest.raises(ValueError, match="both"):
        convergence(t, np.ones(t.size), None, np.full(t.size, 10.0), hold_end_s=3600.0)


def test_mean_mode_accepts_steady_oscillation_and_reports_its_amplitude() -> None:
    t = np.arange(0.0, 7200.0 + 1, 300.0)                  # 5-min outputs over 2 h
    steady = np.full(t.size, 10.0)
    wobble = 10.0 + 0.2 * np.where(np.arange(t.size) % 2 == 0, 1.0, -1.0)   # +-0.2 around 10
    rising = 10.0 + 0.0001 * t                               # 0.18 per 30 min
    w = np.column_stack([steady, wobble])
    span = convergence(t, None, None, w, hold_end_s=7200.0, window_s=1800.0, wse_tol=0.01)
    assert not span.ok                                       # default: range over the window
    mean = convergence(t, None, None, w, hold_end_s=7200.0, window_s=1800.0, wse_tol=0.01,
                       mode="mean")
    assert mean.ok and mean.value <= 0.01
    assert mean.span_max == pytest.approx(0.4)               # the oscillation, reported
    assert "oscillation up to 0.400" in mean.detail
    r = convergence(t, None, None, np.column_stack([steady, rising]), hold_end_s=7200.0,
                    window_s=1800.0, wse_tol=0.01, mode="mean")
    assert not r.ok and r.n_failing == 1                     # still rising: not converged
    with pytest.raises(ValueError, match="mode"):
        convergence(t, None, None, w, hold_end_s=7200.0, mode="median")

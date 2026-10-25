import numpy as np

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

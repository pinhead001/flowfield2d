"""Stepped and ramped plateaus, hold design, equilibrium timesteps."""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike


class LateralInflowWarning(UserWarning):
    """Issued when lateral inflow is floored to zero at one or more indices."""


@dataclass(frozen=True)
class Plateau:
    """A single flow plateau with its hold window."""

    q: float
    hold_start_s: float
    hold_end_s: float


def breakpoints_holds(
    flows: Sequence[float],
    ramp_s: float,
    holds_s: Sequence[float],
) -> list[tuple[float, float]]:
    """Return (t_s, q) corner points for a stepped-ramp hydrograph with per-flow holds.

    Parameters
    ----------
    flows:
        Non-empty, non-negative, non-decreasing sequence of flow values.
    ramp_s:
        Duration of each linear ramp in seconds (must be > 0).
    holds_s:
        Duration of hold period for each flow value in seconds (each must be > 0).
        Must have the same length as *flows*.

    Returns
    -------
    list[tuple[float, float]]
        Corner points as ``(time_seconds, flow)`` pairs.

    Raises
    ------
    ValueError
        If *flows* is empty, lengths of *flows* and *holds_s* differ, any flow
        is negative, flows are not non-decreasing, *ramp_s* is not positive,
        or any hold in *holds_s* is not positive.
    """
    if len(flows) == 0:
        raise ValueError("flows must not be empty")
    if ramp_s <= 0:
        raise ValueError(f"ramp_s must be positive, got {ramp_s}")

    flow_list = [float(q) for q in flows]
    hold_list = [float(h) for h in holds_s]

    if len(flow_list) != len(hold_list):
        raise ValueError(
            f"flows and holds_s must have the same length; "
            f"got {len(flow_list)} and {len(hold_list)}"
        )

    for i, h in enumerate(hold_list):
        if h <= 0:
            raise ValueError(f"holds_s[{i}] = {h} must be positive")

    for i, q in enumerate(flow_list):
        if q < 0:
            raise ValueError(f"flows[{i}] = {q} is negative")

    for i in range(1, len(flow_list)):
        if flow_list[i] < flow_list[i - 1]:
            raise ValueError(
                f"flows must be non-decreasing; flows[{i}]={flow_list[i]} "
                f"< flows[{i-1}]={flow_list[i-1]}"
            )

    points: list[tuple[float, float]] = []
    t = 0.0

    # First flow: start at t=0, hold for holds_s[0]
    points.append((t, flow_list[0]))
    t += hold_list[0]
    points.append((t, flow_list[0]))

    # Subsequent flows: ramp then hold
    for q, h in zip(flow_list[1:], hold_list[1:], strict=True):
        t_ramp_end = t + ramp_s
        points.append((t_ramp_end, q))
        t = t_ramp_end + h
        points.append((t, q))

    return points


def plateaus_holds(
    flows: Sequence[float],
    ramp_s: float,
    holds_s: Sequence[float],
) -> list[Plateau]:
    """Return one :class:`Plateau` per flow value with per-flow holds.

    Parameters
    ----------
    flows:
        Non-empty, non-negative, non-decreasing sequence of flow values.
    ramp_s:
        Duration of each linear ramp in seconds (must be > 0).
    holds_s:
        Duration of hold period for each flow value in seconds (each must be > 0).
        Must have the same length as *flows*.

    Returns
    -------
    list[Plateau]
        One plateau per entry in *flows*.
    """
    pts = breakpoints_holds(flows, ramp_s=ramp_s, holds_s=holds_s)
    result: list[Plateau] = []
    flow_list = [float(q) for q in flows]

    # First plateau: points[0] .. points[1]
    result.append(Plateau(flow_list[0], pts[0][0], pts[1][0]))

    # Subsequent plateaus: each occupies the pair after the ramp
    for idx in range(1, len(flow_list)):
        base = 2 * idx  # ramp-end index
        result.append(Plateau(flow_list[idx], pts[base][0], pts[base + 1][0]))

    return result


def breakpoints(
    flows: Sequence[float],
    ramp_s: float,
    hold_s: float,
) -> list[tuple[float, float]]:
    """Return (t_s, q) corner points for a stepped-ramp hydrograph.

    The series starts at ``flows[0]`` at t=0, holds for ``hold_s`` seconds,
    then for each subsequent flow ramps linearly over ``ramp_s`` seconds and
    holds for another ``hold_s`` seconds.

    Parameters
    ----------
    flows:
        Non-empty, non-negative, non-decreasing sequence of flow values.
    ramp_s:
        Duration of each linear ramp in seconds (must be > 0).
    hold_s:
        Duration of each hold period in seconds (must be > 0).

    Returns
    -------
    list[tuple[float, float]]
        Corner points as ``(time_seconds, flow)`` pairs.

    Raises
    ------
    ValueError
        If *flows* is empty, any flow is negative, flows are not
        non-decreasing, or *ramp_s* / *hold_s* are not positive.
    """
    return breakpoints_holds(flows, ramp_s=ramp_s, holds_s=[hold_s] * len(flows))


def plateaus(
    flows: Sequence[float],
    ramp_s: float,
    hold_s: float,
) -> list[Plateau]:
    """Return one :class:`Plateau` per flow value.

    Parameters
    ----------
    flows:
        Non-empty, non-negative, non-decreasing sequence of flow values.
    ramp_s:
        Duration of each linear ramp in seconds (must be > 0).
    hold_s:
        Duration of each hold period in seconds (must be > 0).

    Returns
    -------
    list[Plateau]
        One plateau per entry in *flows*.
    """
    return plateaus_holds(flows, ramp_s=ramp_s, holds_s=[hold_s] * len(flows))


def sample(
    points: Sequence[tuple[float, float]],
    dt_s: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Sample a piecewise-linear hydrograph at uniform time steps.

    The output time array runs from 0 to the last point's time in steps of
    *dt_s*, always including the final time exactly (even if it is not a
    multiple of *dt_s*).  Flow values are linearly interpolated.

    Parameters
    ----------
    points:
        Sequence of ``(time_seconds, flow)`` corner points in ascending time
        order.
    dt_s:
        Sampling interval in seconds (must be > 0).

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        ``(times, flows)`` both as 1-D float64 arrays.

    Raises
    ------
    ValueError
        If *dt_s* is not positive.
    """
    if dt_s <= 0:
        raise ValueError(f"dt_s must be positive, got {dt_s}")
    if not points:
        raise ValueError("points must not be empty")

    pts = list(points)
    t_end = pts[-1][0]

    # Build regular grid, then append t_end if not already included
    n_steps = int(t_end / dt_s)
    t_regular = np.arange(n_steps + 1, dtype=np.float64) * dt_s

    if t_regular[-1] < t_end:
        times = np.append(t_regular, t_end)
    else:
        times = t_regular

    t_pts = np.array([p[0] for p in pts], dtype=np.float64)
    q_pts = np.array([p[1] for p in pts], dtype=np.float64)

    flows = np.interp(times, t_pts, q_pts)
    return times, flows


def lateral_inflow(
    q_down: ArrayLike,
    q_up: ArrayLike,
) -> np.ndarray:
    """Compute lateral inflow as ``max(q_down - q_up, 0)`` element-wise.

    Where the difference is negative (i.e. would require a negative lateral
    contribution), the result is floored to 0 and a single
    :class:`LateralInflowWarning` is issued naming the affected indices.

    Parameters
    ----------
    q_down:
        Downstream flow array.
    q_up:
        Upstream flow array. Must have the same shape as *q_down*.

    Returns
    -------
    np.ndarray
        Non-negative lateral inflow array with the same shape as the inputs.

    Raises
    ------
    ValueError
        If *q_down* and *q_up* have different shapes.
    """
    arr_down = np.asarray(q_down, dtype=np.float64)
    arr_up = np.asarray(q_up, dtype=np.float64)

    if arr_down.shape != arr_up.shape:
        raise ValueError(
            f"q_down and q_up must have the same shape; "
            f"got {arr_down.shape} and {arr_up.shape}"
        )

    diff = arr_down - arr_up
    floored_mask = diff < 0
    if np.any(floored_mask):
        indices = np.flatnonzero(floored_mask).tolist()
        warnings.warn(
            f"Lateral inflow floored to 0 at indices {indices}",
            LateralInflowWarning,
            stacklevel=2,
        )

    result = np.maximum(diff, 0.0)
    return result

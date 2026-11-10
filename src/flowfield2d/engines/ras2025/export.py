"""RAS 2025 results as the engine-neutral flow state that `flowfield2d.export` writers take."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from flowfield2d.engines.ras2025.results import ResultsReader
from flowfield2d.export.iric import FlowState
from flowfield2d.results import cell_table_from_results


def flow_state(results: ResultsReader, area: str, t: int, unit_m: float, *,
               inflow_lines: Sequence[str] = (), tol: float = 0.0,
               discharge: float | None = None, min_depth: float = 0.0) -> FlowState:
    """The state at output `t` (negative counts from the end) in SI.

    Discharge is `discharge` (m3/s) when given, else the sum of |flow| through `inflow_lines`
    at `t` (BC line names; faces matched within `tol`, model units), converted with `unit_m`^3.
    Results without face-flow output fall back to flows rebuilt from face velocities. The caller
    decides which lines count: a solver with one inflow takes their total."""
    n_out = len(results.time_days())
    k = t if t >= 0 else n_out + t
    if not 0 <= k < n_out:
        raise IndexError(f"output {t} out of range (file has {n_out})")
    if discharge is None:
        if not inflow_lines:
            raise ValueError("give discharge or at least one inflow line")
        total = 0.0
        for line in inflow_lines:
            try:
                q = float(results.boundary_flow(area, line, tol)[k])
            except KeyError as e:
                if "unknown BC line" in str(e):
                    raise
                q = 0.0
            if q == 0.0:
                q = float(results.boundary_flow_reconstructed(area, line, tol)[k])
            total += abs(q)
        discharge = total * float(unit_m) ** 3
    table = cell_table_from_results(results, area, k, unit_m, min_depth)
    return FlowState(discharge=float(discharge),
                     cell_xy=np.column_stack([table["x"], table["y"]]),
                     wse=table["wse_m"], depth=table["depth_m"], speed=table["vel_mps"])

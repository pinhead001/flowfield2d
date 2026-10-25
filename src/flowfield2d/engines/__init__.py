"""Engine adapters behind a neutral interface (REQUIREMENTS 3.2; tier per ADR-0001).

The core never imports an engine module directly. It talks to an `Engine` and checks its
`Capabilities` to decide which steps run headless and which need a person (e.g. Tier B geometry).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray
from shapely.geometry import LineString, Polygon

F = NDArray[np.float64]


@dataclass(frozen=True)
class ModelSpec:
    """Specification for building or deriving a model from a template."""

    template: Path
    dest: Path
    keep: Polygon | None
    cuts: dict[str, LineString]
    cell_size: float
    layers: dict[str, str] = field(default_factory=dict)  # "geometry", "boundary", "plan" -> stem
    # Synthesis (ADR-0004): replace the 2D area with `outline` (exclusive with `keep`), copy the
    # selected layers under new names (`rename`, same keys as `layers`) and bind the geometry to
    # `terrain`. `cuts` then holds the new BC lines.
    outline: Polygon | None = None
    rename: dict[str, str] = field(default_factory=dict)
    terrain: str | None = None
    manning_n: float | None = None   # uniform n for the geometry's n layer (sensitivity runs)


@dataclass(frozen=True)
class BcSpec:
    """Specification for boundary condition hydrographs and slopes."""

    start: datetime
    offsets_s: list[float]
    flows: dict[str, list[float]]
    slopes: dict[str, float]


@dataclass(frozen=True)
class PlanSpec:
    """Specification for plan execution and time stepping."""

    compute_timestep: str
    output_interval: str
    time_stepping: str


@dataclass(frozen=True)
class Capabilities:
    """What an engine build can do, as established by its probe."""

    engine: str
    build: str
    tier: str                          # "A" | "B" | "C" (REQUIREMENTS 3.2)
    headless_compute: bool
    headless_terrain: bool
    headless_mesh_regen: bool
    headless_plan_settings: bool
    bc_by_template_edit: bool
    geometry_authoring_headless: bool  # perimeters, breaklines, BC lines
    plan_binding_headless: bool        # bind a new plan to geometry + BC layers
    gpu: bool
    validates_bc_values: bool          # does the engine reject invalid BC values itself?
    exit_code_reliable: bool           # is exit 0 sufficient evidence of a good run?
    evidence: str = ""


@dataclass(frozen=True)
class RunOutcome:
    """Outcome of an engine run invocation."""

    ok: bool
    exit_code: int | None
    engine_success: bool | None
    result_path: Path | None
    duration_s: float
    log_tail: str = ""


@runtime_checkable
class Results(Protocol):
    """Engine-neutral query interface for simulation results."""

    def areas(self) -> list[str]:
        """Names of 2D flow areas in the results."""
        ...

    def time_days(self) -> F:
        """Simulation output times in days."""
        ...

    def cell_coordinates(self, area: str) -> F:
        """Cell center coordinates (n, 2) as float64."""
        ...

    def cell_depth(self, area: str, t: int) -> F:
        """Cell water depths at output time index t."""
        ...

    def cell_wse(self, area: str, t: int, min_depth: float = 0.0) -> F:
        """Cell water surface elevations at output time index t."""
        ...

    def cell_wse_series(
        self, area: str, cells: Sequence[int], min_depth: float = 0.0
    ) -> F:
        """Cell WSE time series for selected cells over all output times."""
        ...

    def boundary_flow(self, area: str, line: str, tol: float) -> F:
        """Boundary flow series through faces matching the named boundary line."""
        ...

    def boundary_lines(self) -> dict[str, LineString]:
        """The model's boundary-condition lines by name (as run)."""
        ...


@runtime_checkable
class Engine(Protocol):
    """Neutral engine interface."""

    capabilities: Capabilities

    def build_or_verify_model(self, domain: Any) -> Any: ...
    def write_bcs(self, model: Any, hydrograph: Any) -> Any: ...
    def create_plan(self, model: Any, spec: Any) -> Any: ...
    def run(self, plan: Any) -> Any: ...
    def results(self, run: Any) -> Any: ...
    def export(self, run: Any, plateau: Any, fields: Any, out_dir: Path) -> Any: ...

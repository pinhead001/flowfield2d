"""Engine adapters behind a neutral interface (REQUIREMENTS 3.2; tier per ADR-0001).

The core never imports an engine module directly. It talks to an `Engine` and checks its
`Capabilities` to decide which steps run headless and which need a person (e.g. Tier B geometry).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


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
    ok: bool
    exit_code: int | None
    engine_success: bool | None
    result_path: Path | None
    duration_s: float
    log_tail: str = ""


@runtime_checkable
class Engine(Protocol):
    capabilities: Capabilities

    def build_or_verify_model(self, domain: Any) -> Any: ...
    def write_bcs(self, model: Any, hydrograph: Any) -> Any: ...
    def create_plan(self, model: Any, spec: Any) -> Any: ...
    def run(self, plan: Any) -> Any: ...
    def results(self, run: Any) -> Any: ...
    def export(self, run: Any, plateau: Any, fields: Any, out_dir: Path) -> Any: ...

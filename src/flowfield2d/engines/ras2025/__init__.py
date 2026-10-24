"""HEC-RAS 2025 engine adapter (Tier B, ADR-0001)."""

from flowfield2d.engines import Capabilities

CAPABILITIES = Capabilities(
    engine="ras2025",
    build="0.1.0.5048-dev",
    tier="B",
    headless_compute=True,
    headless_terrain=True,
    headless_mesh_regen=True,
    headless_plan_settings=True,
    bc_by_template_edit=True,
    geometry_authoring_headless=False,
    plan_binding_headless=False,
    gpu=False,
    validates_bc_values=False,
    exit_code_reliable=False,
    evidence="docs/probe/v0.1.0.5048-dev/PROBE_REPORT.md (steps D and E); ADR-0001",
)

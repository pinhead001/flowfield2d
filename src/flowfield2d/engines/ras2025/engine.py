"""RAS 2025 engine (Tier B, ADR-0001).

Tier B models are assembled from a GUI template. The pipeline clones the template, selects
layers, rebuilds the perimeter or cuts a subdomain, modifies cell size, and regenerates the mesh.
Plans and boundary conditions are written onto the cloned project.

The run step trusts neither the exit code nor RAS's own BC checks:
1. every BC layer in the project is validated first (`validate.validate_bc`); problems block it;
2. `ras plan solve` runs on the clone, CPU only;
3. a run is ok only if the exit code is 0 **and** the new result's `Compute Summary/Success` is set.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

import h5py

from flowfield2d.engines import BcSpec, Capabilities, ModelSpec, PlanSpec, RunOutcome
from flowfield2d.engines.ras2025 import CAPABILITIES
from flowfield2d.engines.ras2025.bc import (
    set_normal_depth_slope,
    set_time_window,
    write_flow_series,
)
from flowfield2d.engines.ras2025.cli import RasCli
from flowfield2d.engines.ras2025.results import ResultsReader
from flowfield2d.engines.ras2025.split import _layer, rebuild_perimeter, split_geometry
from flowfield2d.engines.ras2025.templates import clone_project
from flowfield2d.engines.ras2025.validate import validate_bc

TAIL = 2000
UNIT_M: dict[str, float] = {"USC": 0.3048, "SI": 1.0}   # `Project Units` -> metres per unit
FOLDERS: dict[str, str] = {
    "geometry": "Geometries",
    "boundary": "Boundary Conditions",
    "plan": "Plans",
}


class RasEngine:
    capabilities: Capabilities = CAPABILITIES

    def __init__(self, cli: RasCli, core_count: int | None = None) -> None:
        self.cli = cli
        self.core_count = core_count

    def run(self, plan: Path) -> RunOutcome:
        plan = Path(plan)
        project = plan.parent.parent
        t0 = time.monotonic()
        problems = [f"{bc.name}: {p.message}"
                    for bc in sorted((project / "Boundary Conditions").glob("*.h5"))
                    for p in validate_bc(bc)]
        if problems:
            return RunOutcome(False, None, None, None, 0.0, "BC validation failed: " +
                              "; ".join(problems))
        results_dir = project / "Results"
        before = {p: p.stat().st_mtime for p in results_dir.glob("*.h5")} \
            if results_dir.exists() else {}
        res = self.cli.run(["plan", "solve", str(plan), "--if-exists", "force",
                            "--processor", "CPU",
                            *(["--core-count", str(self.core_count)] if self.core_count else [])],
                           check=False)
        duration = round(time.monotonic() - t0, 3)
        tail = (res.stdout + res.stderr)[-TAIL:]
        new = [p for p in results_dir.glob("*.h5") if before.get(p) != p.stat().st_mtime] \
            if results_dir.exists() else []
        result = max(new, key=lambda p: p.stat().st_mtime) if new else None
        success = ResultsReader(result).compute_summary().success if result else None
        ok = res.exit_code == 0 and success is True
        return RunOutcome(ok, res.exit_code, success, result, duration, tail)

    def results(self, run: RunOutcome) -> ResultsReader:
        if run.result_path is None:
            raise ValueError("run produced no result file")
        return ResultsReader(run.result_path)

    def _layers(self, model: Path) -> dict[str, str]:
        path = Path(model) / "flowfield2d.json"
        if not path.is_file():
            return {}
        try:
            layers = json.loads(path.read_text(encoding="utf-8")).get("layers", {})
        except (OSError, json.JSONDecodeError, AttributeError) as err:
            raise ValueError(f"unreadable layer selection {path}: {err}") from err
        if not isinstance(layers, dict):
            raise ValueError(f"layer selection in {path} is not a mapping")
        return {str(k): str(v) for k, v in layers.items()}

    def model_unit_m(self, template: Path, layers: Mapping[str, str]) -> float:
        """Metres per model unit, from the geometry layer's `Project Units` attribute."""
        geom = _layer(Path(template) / FOLDERS["geometry"], layers.get("geometry"))
        with h5py.File(geom, "r", locking=False) as f:
            raw = f.attrs.get("Project Units", b"")
        units = raw.decode() if isinstance(raw, bytes) else str(raw)
        if units not in UNIT_M:
            raise ValueError(f"unknown Project Units {units!r} in {geom}")
        return UNIT_M[units]

    def _file(self, model: Path, kind: str) -> Path:
        if kind not in FOLDERS:
            raise ValueError(f"unknown layer kind {kind!r}")
        folder = Path(model) / FOLDERS[kind]
        stem = self._layers(model).get(kind)
        return _layer(folder, stem)

    def build_or_verify_model(self, spec: ModelSpec) -> Path:
        clone_project(spec.template, spec.dest)
        (spec.dest / "flowfield2d.json").write_text(
            json.dumps({"layers": spec.layers}), encoding="utf-8"
        )
        geom_stem = spec.layers.get("geometry")
        bc_stem = spec.layers.get("boundary")
        if spec.keep is None:
            rebuild_perimeter(spec.dest, geometry=geom_stem, boundary=bc_stem)
        else:
            split_geometry(
                spec.dest, spec.keep, spec.cuts, geometry=geom_stem, boundary=bc_stem
            )
        geom = self._file(spec.dest, "geometry")
        self.cli.run([
            "geometry",
            "modify",
            str(geom),
            f"topology.region.cellsize = {spec.cell_size:g}",
            f"topology.arc.cellsize = {spec.cell_size:g}",
        ])
        self.cli.generate_mesh(geom)
        return spec.dest

    def write_bcs(self, model: Path, bc: BcSpec) -> Path:
        for name, slope in bc.slopes.items():
            if not (slope > 0):
                raise ValueError(f"slope for {name!r} must be > 0, got {slope}")
        if len(bc.offsets_s) < 1 or any(
            b <= a for a, b in zip(bc.offsets_s, bc.offsets_s[1:], strict=False)
        ):
            raise ValueError("offsets_s must be strictly increasing")
        for name, flow in bc.flows.items():
            if len(flow) != len(bc.offsets_s):
                raise ValueError(
                    f"flow list for {name!r} has length {len(flow)}, expected {len(bc.offsets_s)}"
                )
        path = self._file(model, "boundary")
        for line, values in bc.flows.items():
            write_flow_series(path, line, bc.offsets_s, values)
        set_time_window(path, bc.start, bc.start + timedelta(seconds=bc.offsets_s[-1]))
        for name, s in bc.slopes.items():
            set_normal_depth_slope(path, s, line=name)
        problems = validate_bc(path)
        if problems:
            raise ValueError("BC validation failed: " + "; ".join(p.message for p in problems))
        return path

    def create_plan(self, model: Path, spec: PlanSpec) -> Path:
        plan = self._file(model, "plan")
        self.cli.plan_modify(plan, {
            "ComputeTimestep": spec.compute_timestep,
            "BaseOutputInterval": spec.output_interval,
            "TimeStepping": spec.time_stepping,
        })
        return plan

    def export(self, run: Any, plateau: Any, fields: Any, out_dir: Path) -> Any:
        raise NotImplementedError("use RasCli.result_map / post.rasters (pending)")

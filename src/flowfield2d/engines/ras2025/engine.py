"""RAS 2025 engine (Tier B, ADR-0001).

The run step trusts neither the exit code nor RAS's own BC checks:
1. every BC layer in the project is validated first (`validate.validate_bc`); problems block it;
2. `ras plan solve` runs on the clone, CPU only;
3. a run is ok only if the exit code is 0 **and** the new result's `Compute Summary/Success` is set.
Model building and plan creation stay with the pipeline on top of GUI-authored templates.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from flowfield2d.engines import Capabilities, RunOutcome
from flowfield2d.engines.ras2025 import CAPABILITIES
from flowfield2d.engines.ras2025.cli import RasCli
from flowfield2d.engines.ras2025.results import ResultsReader
from flowfield2d.engines.ras2025.validate import validate_bc

TAIL = 2000


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

    # Tier B: base geometry and plan binding are authored in the GUI; the pipeline clones them.
    def build_or_verify_model(self, domain: Any) -> Any:
        raise NotImplementedError("Tier B: use templates.clone_project + verify_template")

    def write_bcs(self, model: Any, hydrograph: Any) -> Any:
        raise NotImplementedError("use engines.ras2025.bc (multi-line BC writer pending)")

    def create_plan(self, model: Any, spec: Any) -> Any:
        raise NotImplementedError("Tier B: plans come from the template; settings via plan modify")

    def export(self, run: Any, plateau: Any, fields: Any, out_dir: Path) -> Any:
        raise NotImplementedError("use RasCli.result_map / post.rasters (pending)")

# ADR-0001 — HEC-RAS 2025 integration tier

- Status: **accepted as provisional** at G0 (2026-10-24); final after probe step E (no seed yet).
- Date: 2026-10-24
- Evidence: `docs/probe/v0.1.0.5048-dev/PROBE_REPORT.md`

## Context
REQUIREMENTS 3.2 sets the integration tier from the Phase 0 probe. Build `0.1.0.5048-dev` exposes a
documented-by-help CLI (`ras.exe`, CommandLineParser, .NET 10). It has commands for terrain, mesh, plan
settings, compute (CPU/GPU, SWE/DWE, explicit/implicit), result maps and HDF5 diffing. It has no BC-edit
command.

## Decision (provisional)
Design for **Tier A with template-edited BCs**, keeping the Tier B path open:
- The engine adapter `rasdrive.engine.ras2025.cli` wraps `ras.exe` verbs. It always passes `--if-exists`
  explicitly and parses `info --format Json` / `--format Json` change reports.
- BC time series are written by `h5edit` into cloned RAS-written BC files under the schema guard (3.3).
- Model assembly order: `project create` → `terrain create/add` → geometry (see below) →
  `geometry generate-mesh` → `project add-new -t plan` + `plan modify` → `plan solve` → `result postprocess`
  / `result map`.
- **Geometry authoring fallback (Tier B):** if E shows that perimeters, breaklines, refinement regions or
  BC lines cannot be set headlessly, a person authors each domain's base geometry once in the GUI. Code then
  clones it and does everything else through the CLI. The P1 plan carries both branches until E decides.

The decision is final when E2, E3, E5, E6 and E7 pass by CLI with no window, E4 passes by template edit,
and E6b fails naming the boundary. Then this ADR is updated with the results, run times (E6/E9/E10),
determinism (E13) and the GPU verdict (E11).

## Consequences
- No UI-automation spike is planned (the Tier C risk has receded, but stays open until E6 runs).
- The pin file must hash `ras.exe`, `Ras.Interface.Process.exe` and the engine DLLs (list fixed after E6
  shows which load).
- `ras s3`, `ras sample` and `RestartAgent.exe` are never invoked; their hosts stay blocked.
- A new build (REQUIREMENTS 3.4) re-runs A, B (with `cli_tree.json` diff), D, E6, E8 and E13.

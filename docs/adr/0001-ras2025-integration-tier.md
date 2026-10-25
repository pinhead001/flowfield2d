# ADR-0001 — HEC-RAS 2025 integration tier

> Renamed: the library is now `flowfield2d` (see ADR-0003); names below are as written at the time.

- Status: **accepted: Tier B** (Chris Nelson, 2026-10-24, after probe step E; see "Final decision" at the end).
  It had been accepted as provisional at G0.
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

## Final decision after probe step E (2026-10-24, accepted by the owner)
Evidence: PROBE_REPORT "D", "E" and "Tier (rule trace)". Decision: **Tier B, with headless everything except
base geometry authoring.**
- **GUI once per domain:** a person draws the 2D-area perimeter, breaklines, refinement regions and BC lines,
  and creates the plan bound to that geometry and BC layer. `geometry modify` only resizes existing regions and
  arcs, and plans hold no layer references.
- **Headless:** terrain create and add; `geometry generate-mesh` plus sizing via `geometry modify`; plan settings
  via `plan modify` (solver, cores, Courant, window, steps); BC values via `engines.ras2025.bc` template edits
  under the schema guard; `plan solve`; `result postprocess` and `result map`; HDF5 result reads.
- **Validation:** RAS accepted a zero normal-depth slope (E6b exit 0, `Success=1`). The engine validates BC
  values before every compute and reads `/Results/Compute Summary/Success` and the log after it; exit codes
  alone are not trusted.
- **Results:** a solve writes a new `(Result).h5` and rewrites the geometry file. The run layer works on
  per-run copies and treats the geometry as an output of a solve.
- **CPU only:** no NVIDIA driver in the sandbox (E11). Two concurrent solves run at about 1.3× the single-solve
  time on the seed (E9). Start `max_parallel_runs` at 2 and re-measure on the first production-size domain.
  Mapped versus local scratch showed no difference at seed size (E10).
- **Determinism tolerance for S6:** zero on depth and velocity. Byte-level file hashes differ because of a debug
  counter, so compare datasets, not files.
- E8 confirmed by the owner (2026-10-24): HDF5 depth, and WSE = depth + cell minimum elevation, match the GUI.
- Still open: E12 (egress Enforce, once the Audit sampler works);
  the list of engine DLLs loaded at solve time, for the pin (needs a Process Monitor run).

## Addendum 1 — code-derived subdomains (accepted by the owner, 2026-10-24)
A split probe showed that overlapping subdomains can be derived headlessly from one GUI-authored full-domain
template: `engines.ras2025.split.split_geometry` clips the 2D-area polygon, closed perimeter arc, node and control
point, moves named BC lines onto the cuts, and then `ras geometry generate-mesh` rebuilds the mesh. The Tier B
GUI step is therefore **one full template per river segment**, not one per subdomain. Cut BCs need a
normal-depth slope from one of four sources (`flowfield2d.slope`: terrain, thalweg, WSE, specified; chosen per
project) and the downstream extension rule; overlap agreement is checked by QA.

# flowfield2d — Requirements

| | |
|---|---|
| Version | 0.1 (draft for review) |
| Date | 2026-10-13 |
| Owner | Chris Nelson |
| Kind | General-purpose library and tools. Location-agnostic: it drives HEC-RAS 2025 2D models anywhere. |
| First consumer | `methow-hydraulics`, which pins a tagged release, the way `methow-flow` pins `flowfreq` |

---

## 1. Purpose and boundary

`flowfield2d` turns a set of inputs into HEC-RAS 2025 2D results and hydraulic metrics, under script or agent control, for any river. Every project-specific choice arrives as an input or a parameter:
- reach geometry and IDs
- terrain
- land-cover classes and Manning's n table
- flows by point and scenario
- thresholds and tolerances

**The boundary rule.** Nothing location- or client-specific lives here. That means no:
- place, stream or agency names
- reach-layer schemas
- coordinate systems
- file paths
- habitat-model vocabulary (EDT attributes, for example)
- default values tuned to one basin

A test (`tests/test_boundary.py`) fails the build if banned terms appear in `src/`, `tools/` or `docs/`. Each consuming project keeps its own banned-term list in its repo and passes it to that test's helper.

If a function only makes sense for one project, it belongs in that project's repo. Agents say so rather than adding it here.

## 2. Package layout

```
flowfield2d/
  REQUIREMENTS.md  CLAUDE.md  AGENTS.md  README.md  CHANGELOG.md  pyproject.toml  uv.lock
  src/flowfield2d/
    engines/ras2025/   cli.py h5edit.py h5schema.py results.py templates.py pin.py
    domains.py        segment a stream network at flow-change points; extents; BC line placement
    terrain.py        clip/mosaic DEM tiles per domain; void-mask summaries
    roughness.py      class raster/polygons + n table -> roughness layer
    hydrograph.py     stepped/ramped plateaus, hold design, equilibrium timesteps
    runs.py           run registry (JSON + file lock), scheduler, resume, parallel caps
    post/             rasters.py inundation.py metrics.py (per-polygon/per-centerline stats)
    qa/               checks.py calibration.py report.py
    provenance.py     run manifests
    cli.py            `flowfield2d` command (typer)
  agentops/           statusline, ledger, queue, runner, governor, hooks (any project)
  tools/probe/        cliprobe.py rasprobe.py + tests
  docs/               PROBE_PROCEDURE.md adr/ methods/
  tests/              unit/ integration/ (marker: ras) fixtures/ (synthetic only) test_boundary.py
```

## 3. Engine integration — HEC-RAS 2025

### 3.1 Pin
- A pin file supplied by the consumer holds the build ID plus SHA256 for `ras.exe` and the key DLLs.
- The engine refuses to run on a mismatch.
- RAS 2025 has been in Beta since April 2026, and HEC advises against production use of the Beta. Builds are never auto-updated.

### 3.2 Integration tier
The Phase 0 probe decides the tier (docs/PROBE_PROCEDURE.md), recorded in ADR-0001 of this repo.

| Tier | Condition | Architecture |
|---|---|---|
| A — CLI-native | Terrain, mesh, plan, compute and export all work headless through the CLI, with meaningful exit codes | The engine wraps the CLI. HDF5 editing is limited to BC time series. |
| B — Hybrid | Headless compute works, but some model assembly is GUI-only | A person authors each domain's base model once in the GUI. Code clones templates, edits BC and plan HDF5 under schema guards, and computes through the CLI. |
| C — No headless compute | Compute needs the GUI | Code prepares everything and verifies the results. A person clicks Compute on queued batches. Run a UI-automation spike (`pywinauto`), time-boxed to 1 day. |

The engine interface is a Python `Protocol`:
- `build_or_verify_model(domain)`
- `write_bcs(model, hydrograph)`
- `create_plan(model, spec)`
- `run(plan) -> RunResult`
- `results(run) -> ResultsReader`
- `export(run, plateau, fields, out_dir)`

### 3.3 HDF5 rules and schema guards
- **Schema guard:** before editing any RAS file, fingerprint its structure and compare it with the fingerprint recorded for the pinned build. On a mismatch, stop with a diff.
- **Strings:** preserve fixed-width NULLTERM strings exactly, with memory type equal to file type. h5py's default write silently drops the last character.
- **Datasets:** recreate them; never resize.
- **Time:** in 100-ns ticks.
- **Templates only:** clone a RAS-written file; never build one from scratch. The format is the undocumented `1.0-dev`.

### 3.4 Upgrading the RAS build
To adopt a new build:
1. Stage it beside the current one.
2. Re-run probe steps A, B and D.
3. Run the golden regression, i.e. a consumer's pilot domain.
4. Write an ADR addendum.
5. Release a new `flowfield2d` version that records the build it was tested against.

## 4. Modeling building blocks

Every threshold below is a parameter. The defaults are generic starting points, and projects set their own values.

| Block | Behavior | Parameters (default) |
|---|---|---|
| Domains | Split a network at given flow-change points; extend upstream and downstream of the analysis reaches; overlap neighboring domains | Upstream lead-in in bankfull widths (5). Downstream extension max(L_min, k·D<sub>bf</sub>/S) with L_min (1 km) and k (2). |
| BC sensitivity | Scale normal-depth slope 0.5× and 2×; measure WSE change at the downstream analysis boundary | Tolerance (0.03 m) |
| Overlap check | WSE agreement in domain overlaps | Tolerance (0.05 m) |
| Terrain | Clip and mosaic per domain. No reprojection or resampling unless meshing needs it. Report void fraction (void cells ÷ wetted cells). | — |
| Roughness | Class layer + n table → roughness layer | Channel n calibration bounds (0.025–0.060) |
| Hydrograph | Ascending plateaus with ramps and holds. Lateral inflow = Δ node flow, floored at 0 with a warning. | Ramp and hold lengths |
| Convergence | \|Q<sub>out</sub> − Q<sub>in</sub>\|/Q<sub>in</sub> and WSE change over the end of each hold. If not converged, lengthen the hold and rerun up to N times. | 1%, 0.005 m over 30 min, N = 2 |
| Solver | Explicit by default. Implicit and GPU solvers only after a parity test. Cores per run start from HEC's guidance of 1 per 1,000–5,000 cells. | Max CFL (0.8), local time-step levels (3) |
| Outputs | WSE, depth, velocity and shear as COG rasters; inundation polygons. Shear is taken from RAS if written, otherwise τ = ρg n² V² / h<sup>1/3</sup> (SI; divide by 1.486² in US units), with a hand-calculated test. | Raster resolution |
| Metrics | Per polygon or centerline: wetted area, mean width (area ÷ length), depth and velocity statistics, shear percentiles, area outside a reference extent, void fraction, a convergence flag. Columns are generic; projects map them to their own vocabulary. | Percentiles |
| QA | Volume balance, convergence, WSE monotonic downstream (with listed exceptions), BC sensitivity, overlap, wet/dry sanity, void flags, determinism | Tolerances |
| Calibration | Modeled WSE vs observed stage at matched discharge (from field measurements plus a datum offset); n sensitivity | Tolerance (0.15 m mean \|ΔWSE\|) |

## 5. Generic data contracts

| Direction | Content |
|---|---|
| In | Reach features: ID, geometry, optional bankfull width. The project adapter maps its own schema onto this. |
| In | DEM tiles plus a sidecar JSON (CRS, horizontal and vertical units, vertical datum); void mask |
| In | Land-cover classes; n table |
| In | `flows_by_point`: `point_id`, `scenario_id`, `q`, `q_units`, plus any pass-through provenance columns (kept verbatim) |
| In | Gage observations: stage, discharge, datum offset |
| Out | `flow_points` request: `point_id`, `domain_id`, `role`, geometry |
| Out | Metrics Parquet keyed by `feature_id` × `scenario_id`; rasters; inundation; run manifests; QA and calibration reports |

Units convert only at these boundaries, each covered by tests. Metrics are exported in SI with explicit unit columns.

## 6. Probe tools

- `tools/probe/cliprobe.py` crawls any CLI's help tree safely.
- `tools/probe/rasprobe.py` covers inventory, .NET metadata, HDF5 schema/diff, snapshots, the smoke runner, report and tier suggestion, and a test terrain.
- Procedure: `docs/PROBE_PROCEDURE.md`. The tests use fake CLIs and synthetic HDF5 only.

## 7. Agent ops (project-independent)

`agentops/` is the general machinery for running a Claude Code lead with headless delegate workers on any project:
- **Claude meter:** from the status line's `rate_limits.five_hour` and `rate_limits.seven_day` (`used_percentage`, `resets_at`).
- **Delegate runner:** for the Antigravity CLI: `agy -p … --output-format json`, one git worktree per task card, a JSONL ledger of the envelope.
- **Governor:** modes and pacing thresholds read from the consuming project's config.
- **Hook scripts.**

All paths and thresholds come from config; nothing is hard-coded.

## 8. Conventions and releases

- Python 3.12; uv with a committed `uv.lock`; ruff; mypy (strict on `src/`); pytest. Unit tests run offline; integration tests are marked `ras`.
- Semantic versioning, git tags, and a CHANGELOG entry per release. Each release notes the RAS build it was tested against.
- **Consumption pattern:**
  - During development, consumers use an editable path dependency on the sibling checkout.
  - For delivery, a consumer pins an exact tag and vendors a copy, as `methow-flow` does with `flowfreq`.
- One ADR per decision in `docs/adr/`. Each module gets a methods write-up in `docs/methods/` that is free of project vocabulary.

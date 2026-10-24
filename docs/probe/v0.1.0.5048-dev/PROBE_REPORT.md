# Probe report — HEC-RAS 2025 `0.1.0.5048-dev`

- Date: 2026-10-24 · Procedure: `docs/PROBE_PROCEDURE.md` · Raw tool output: `report_generated.md`
- **Status: complete except E12 (2026-10-24).** Steps A, B, D and E have run; C was skipped because B was
  rich. E8 is confirmed by the owner: five cells' depth and derived WSE match the GUI. E12 needs egress in Enforce mode, and the
  Audit sampler is not producing logs yet. Seed-specific records (snapshots, schemas, per-op JSON) live in the
  consuming project's repo, because they carry project names; this report keeps only generic findings.

## Environment
Windows Sandbox, 32 logical cores, 96 GB RAM. GPU: only "Microsoft Remote Display Adapter" is visible and
`nvidia-smi` is absent, so a CUDA solve is not expected to work (E11 will confirm). The build is staged at
`C:\Programs\HECRAS_2025\v0.1.0.5048-dev` and run from local disk.

## A — Inventory (`inventory.json`, `sigcheck.csv`)
| Question | Answer |
|---|---|
| .NET? Runtime | Yes. Self-contained .NET 10 (`Microsoft.NETCore.App` 10.0.1 bundled) for `ras`, `Ras.Interface.Process`, `Ras.Interface.WinUI`, `migrate` |
| CLI framework | CommandLineParser. Verbs and `--help`; leaf help goes to **stderr** with exit 0 |
| Other executables | `ras.exe` (console CLI) · `Ras.Interface.WinUI.exe` (GUI) · `Ras.Interface.Process.exe` (console, no help; likely a worker host) · `migrate.exe` (console) · `RestartAgent.exe` (GUI, v2.0; updater/restart helper) · `createdump.exe` · GDAL 3.x tools |
| Native libraries | HDF5 (`hdf5.dll`, `hdf5_hl.dll`), GDAL + PROJ 9 + netCDF, DSS (`hecdss.dll`), SQLite, CUDA engine (`Ras.Engine.CUDA.dll`) |
| Embedded hosts of note | HEC: `*.hecdev.net` (`s3`, `ras-modelrepo`, `ras-benchmarks`, `rastesting-api`, `drive`, `osm`, `bitbucket`), `hec.usace.army.mil`. Cloud: `s3.amazonaws.com`, `storage.azure.com`, `storage.googleapis.com`. Most others are GDAL/PROJ driver strings |
| Signature | `ras.exe` is signed (USACE); SHA256 is in `sigcheck.csv` and goes into the consumer's pin file |

**Egress implication:** keep every HEC and cloud-storage host off the allowlist. `ras sample pull/push` and
`ras s3 *` are network features the pipeline never uses.

## B — CLI surface (`cli/cli_tree.md`; 65/65 paths parsed, 0 windows, 0 timeouts)
The crawl first parsed only 21/65 paths, because cliprobe did not read CommandLineParser leaf help. This
was fixed by card `p0-cliprobe-clp-leaf` (with tests) and the CLI was re-crawled.

| Capability | Command(s) found | Probe op |
|---|---|---|
| Project create / inspect | `project create -o -j`, `project info`, `info --format Json` | E1 |
| Add layers | `project add -f`, `project add-new -t terrain|geometry|plan|bc -n` | E5 |
| Terrain | `terrain create [-n|-o -j]`, `terrain add <terrain> --files ...`, `terrain export`, `raster translate` | E2 |
| Mesh | `geometry generate-mesh <geom> [--squeeze]`; `geometry modify` with `--grammar`/`--dry-run` (topology fields) | E3 |
| Plan settings | `plan modify <plan> "<field> = value" ... [--grammar] [--dry-run]` | E4/E5 |
| Compute | `plan prepare` → `.r2r.h5`; `plan solve`, `project solve`, `solve`; overrides `--processor CPU|GPU`, `--equation SWE|DWE`, `--time-stepping Explicit|Implicit`, `--core-count`, `--if-exists` | E6, E9, E11 |
| Results | `result info`, `result postprocess`, `result map --type depth|velocity|watersurface [--calculation max] [--cell-size] [--terrain]` | E7 |
| HDF5 tooling | `h5 diff`, `h5 squeeze`, `h5 create-patch/restore-patch`, `clone [--regenerate-mesh|--clean-mesh|--geometry-only]` | D, guards |
| BC editing | **No dedicated command.** `project add-new -t bc` creates an empty BC layer | E4 by template edit |
| Benchmarks | `benchmark solver` (synthetic Thacker 2D), `benchmark h5`, `benchmark hash` | optional capacity check |

`migrate.exe`: 1/4 paths returned help (a file-format migration tool, not needed).

## D — HDF5 baseline
The seed is a small computed project: 921 cells, 1,451 faces, 25 output steps, one BC layer with two BC
lines. All 11 HDF5 files were fingerprinted. Fixed-length NULLTERM strings that **fill their full width** are
common (20 in the BC file, 25 in the geometry, 71 in the result), so the exact-string rule in REQUIREMENTS
3.3 is essential.
- **BC layer:** `/Boundary Conditions/BC Lines/Payloads` holds a compound `Payloads` table, one row per
  payload: `Variable` ("Flow", "Normal Depth"), `Mode` ("TimeSeries", "Constant"), `Constant` (f8) and `Row`.
  `Times` (i8, 100-ns ticks offset from the BC `Start Time`) and `Values` (f8) are deflate-compressed.
  Start, end and warm-up times are i8 ticks, each with a `(DESC)` text twin.
- **Plan:** settings only (solver, equation set, time stepping, cores, Courant, window, steps). It holds no
  reference to its geometry or BC layer; the binding lives in the project file.
- **Result:** `Cell Depth` [t, cell] and `Face Velocity` [t, face] (f4); no WSE dataset. WSE = depth + cell
  minimum elevation from the geometry property tables. `/Results/Compute Summary` has `Success`, `Solver` and
  `Compute Log`.

## E — Smoke results (scratch copies, CPU, no window in any op)
| Op | Result | Notes |
|---|---|---|
| E0 healthcheck, E1 project info, E1b/E1c grammars | pass | read-only |
| E2 terrain create + add | pass, 2 s | |
| E3 `geometry generate-mesh` | pass, 0.5 s | regenerates from the existing conceptual mesh |
| E4 BC by template edit (`engines.ras2025.bc`) + solve | **accepted**, exit 0 | the edited BC file was used |
| E5 `project add-new -t plan` | pass, 3 s | the new plan has no layer binding settable from the CLI |
| E6 `plan solve` (CPU) | exit 0, ~7–8 s | writes a **new** `(Result).h5`; also rewrites the geometry file |
| E6b normal-depth slope = 0 + solve | **did not fail**: exit 0, `Success=1` | RAS does not validate this BC; validation must happen before compute |
| E7 `result map` (max WSE), E7b `result postprocess` | pass, 2 s | |
| E9 two concurrent solves | both pass, 9.6 / 10.8 s vs 7.7 s single | |
| E10 local vs mapped scratch | ~10 s both | no penalty at this size; recheck at production size |
| E11 `--processor GPU` | clean failure, exit −1, "No NVIDIA driver detected" | CPU only |
| E13 determinism (E6 ×2) | depth and velocity identical | only `DEBUG/CellLimitCount` differs (by 1); files are not byte-identical |

**Geometry authoring** (from the E1c grammar): `geometry modify` sets mesh sizing on *existing* regions and
arcs (cell size, patch type, arc spacing). It cannot add 2D-area perimeters, breaklines, refinement
regions or BC lines.

## Tier (rule trace)
- E2, E3, E6 and E7 pass headless, and E4 passes by template edit.
- E6b did **not** fail as the Tier A rule expects.
- New-domain geometry (perimeter, breaklines, BC lines) is not CLI-authorable, and a new plan cannot be
  bound to its layers from the CLI.

→ **Tier B**: a person authors each domain's base geometry, and binds its plan, once in the GUI. Code
clones those templates and does everything else headless: terrain, mesh regeneration and sizing, plan
settings, BCs by template edit under the schema guard, compute, post-processing and export. Pre-compute BC
validation in code makes up for E6b. See ADR-0001.

## agy probe
See ADR-0002 and `docs/probe/agy/`.

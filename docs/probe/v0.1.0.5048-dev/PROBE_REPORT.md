# Probe report — HEC-RAS 2025 `0.1.0.5048-dev`

- Date: 2026-10-24 · Procedure: `docs/PROBE_PROCEDURE.md` · Raw tool output: `report_generated.md`
- **Status: partial.** Steps A and B are complete; step C was skipped because B was rich. Steps D and E are
  **blocked**: no seed project is staged at `$SEED`. E12 also needs egress in Enforce mode
  (Audit today).

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

## Suggested tier (provisional, pending E)
The help surface covers every op that Tier A needs (E2 terrain, E3 mesh, E5 plan, E6 compute, E7 export)
headlessly, and BC values can go through template edits. **Tier A is the working hypothesis.** It is not
a finding until E2–E7 pass on a scratch copy of the seed with no window and meaningful exit codes, and
E6b fails as expected. Open points that E decides:
1. whether a new plan can be associated with a geometry and BC layer from the CLI (`plan modify --grammar`);
2. whether `geometry modify` can set breaklines, refinement regions and BC lines, or whether those stay
   GUI-authored (that would make it **Tier B**: GUI base model per domain, CLI everything else);
3. the BC HDF5 schema (step D) for the template editor.

## E — Smoke spec
`tools/probe/smoke.toml` has been drafted (E0–E11; E8/E10/E12 as notes). It is **not run**. It needs the
owner's approval and the seed.

## agy probe
See ADR-0002 and `docs/probe/agy/`.

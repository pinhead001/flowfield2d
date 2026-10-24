# Phase 0 probe procedure — HEC-RAS 2025 and Antigravity CLI

This procedure finds out what HEC-RAS 2025 can actually do from the command line in the target environment, so the repo architecture rests on observed behavior. Its output picks the integration tier (REQUIREMENTS §3.2), recorded in ADR-0001. The same tools probe `agy`, recorded in ADR-0002.

RAS 2025 is a Beta with an undocumented CLI. HEC's 2026-08-31 release notes mention a `terrain add` command; nothing else is documented. Treat every capability as unknown until a step below shows it.

## 0. Outputs

| Path (repo) | Content |
|---|---|
| `docs/probe/<build>/inventory.json` | Every file in the RAS build: size, SHA256, executable version info, .NET runtime, dependencies, embedded URLs |
| `docs/probe/<build>/cli/cli_tree.{json,md}` | The command tree discovered from help output, with raw transcripts in `cli/raw/` |
| `docs/probe/<build>/dotnet.json` | Public .NET types and command-like strings (static metadata only) |
| `docs/probe/<build>/h5/*.json` | HDF5 schemas of the seed project, with fingerprints |
| `docs/probe/<build>/smoke/<op>.json` | One record per operation: argv, exit code, timing, window seen, files changed, HDF5 schema diff |
| `docs/probe/<build>/PROBE_REPORT.md` | Capability matrix plus suggested tier with the rule trace |
| `docs/probe/agy/...` | The same for `agy` |
| `docs/adr/0001-ras2025-integration-tier.md`, `docs/adr/0002-agy-integration.md` | Decisions, written by the lead from the report |

Scratch copies of projects go to `$SCRATCH` and are never committed.

## 1. Preconditions

- The environment is up (in a sandboxed deployment, its bootstrap reports success).
- The RAS build has been copied to `C:\Programs\HECRAS_2025\<build>`.
- The repo env has `h5py`, `pefile`, `dnfile`, `psutil`, `rasterio`: `uv sync`.
- A seed project is staged at `$SEED`: an existing RAS 2025 project with a computed plan and at least one BC file. The probe only ever works on copies.
- Egress is in `Enforce` mode. Blocked connection attempts during probing are findings, not failures.

**Safety rules for the whole procedure:**
- Only scratch copies.
- Process trees are killed on timeout.
- No decompilation; reading .NET metadata is the limit.
- Never invoke a subcommand without a help or version flag until step E, and in step E only commands written into `smoke.toml` and reviewed by the lead.

## 2. Steps

Run these from the `flowfield2d` repo root with these variables set:

| Variable | Meaning | Example |
|---|---|---|
| `$RAS` | the pinned `ras.exe` | `C:\Programs\HECRAS_2025\<build>\ras.exe` |
| `$SEED` | the seed project | a copy of a computed project |
| `$SCRATCH` | scratch folder | any writable, uncommitted folder |
| `$TOOLS` | tools root | where Sysinternals lives |
| `$P` | output folder | `docs\probe\<build>` |

### A — Inventory

```
uv run python tools/probe/rasprobe.py inventory --ras-dir C:\Programs\HECRAS_2025\<build> --out $P\inventory.json
$TOOLS\sysinternals\sigcheck64.exe -accepteula -nobanner -a -h -c $RAS  > $P\sigcheck.csv
```

Read the summary block. Answer these questions:
1. Is RAS a .NET app, and which runtime does it use (`*.runtimeconfig.json`)?
2. Which CLI framework do the dependencies name (System.CommandLine, Spectre.Console.Cli, CommandLineParser, ...)? This tells you the help syntax.
3. Are there other executables (a console host, a solver, an updater)?
4. Which native libraries ship (HDF5, GDAL, CUDA/OpenCL)?
5. Which URLs are embedded? Update and telemetry endpoints confirm what the egress rules must block.

### B — CLI surface

```
uv run python tools/probe/cliprobe.py crawl --exe $RAS --out $P\cli --max-depth 4 --timeout 20 --cwd $SCRATCH
```

The crawler only ever calls `<exe> [<path>] <help flag>` and `<exe> <version flag>`, then walks the commands it finds in the help text. Each call is classified:

| Status | Meaning |
|---|---|
| `help` | Parseable help text |
| `version` | Version output |
| `error` | Non-zero exit with a message |
| `timeout` | Killed at the timeout. Usually means a GUI opened; `window_seen` confirms it on Windows. |
| `skipped` | Command name matches the risky-name list (delete, update, login, ...). Rerun with `--allow <name>` once the lead has read its help from the parent. |

Crawl any other console-looking executable from step A the same way.

### C — Static mining (only if B finds little)

```
uv run python tools/probe/rasprobe.py dotnet --ras-dir C:\Programs\HECRAS_2025\<build> --out $P\dotnet.json
uv run python tools/probe/cliprobe.py crawl --exe $RAS --out $P\cli2 --seed terrain --seed mesh ... (seed names from dotnet.json "seed_names")
```

This step lists public types and namespaces, flagging any that look like an API (`Api`, `Scripting`, `Automation`, `Sdk`). It also lists command-like user strings and types (`*Command`, `*Verb`, `*Handler`). The seed names are then tried as subcommands, with help flags only. A public API surface is noted for ADR-0001; HEC has said a documented public API is planned. It is not called in this phase.

### D — HDF5 baseline

```
uv run python tools/probe/rasprobe.py snapshot $SEED --out $P\snap_seed.json
uv run python tools/probe/rasprobe.py h5schema $SEED --out $P\h5\seed.json
```

This records:
- every group, dataset and attribute
- dtypes, shapes, chunking and compression
- fixed-length string padding (NULLTERM, NULLPAD or SPACEPAD) and size

The fingerprint covers structure only, so the same file type compares across projects. This baseline is what `engines.ras2025.h5schema` guards against later (REQUIREMENTS §3.3).

### E — Smoke tests (one operation at a time, each on a fresh copy)

Write `tools/probe/smoke.toml` from what B and C found; `smoke.example.toml` shows the format. Review it before running. Then run:

```
uv run python tools/probe/rasprobe.py smoke --spec tools/probe/smoke.toml --out $P\smoke
```

For each operation the runner:
1. copies the seed to a fresh scratch project
2. snapshots it
3. runs the argv with a timeout, watching for windows
4. snapshots it again
5. diffs files, and diffs HDF5 schemas for every changed or new `.h5`
6. checks the `expect` block

| Op | Capability | What to learn |
|---|---|---|
| E1 | open/validate project | Does the CLI accept a project path? Does it honor the `.lock` file? |
| E2 | terrain add | Use a tiny GeoTIFF with NoData set (`rasprobe.py make-terrain`). Is it headless? Where is the terrain written? What is the schema of the new `.h5`? |
| E3 | mesh generate | Can the conceptual mesh be regenerated headless? Run time? |
| E4 | BC edit | Two paths: through the CLI if one exists, and by template edit of `bc_*.h5` with the NULLTERM rule. Then E6 must accept the edited file. |
| E5 | plan create | Can a plan link a geometry and a BC layer from the CLI? HEC's docs say these associations are fixed at creation. |
| E6 | compute | Is it headless, with a meaningful exit code? Progress output, log location, run time. Use the seed's smallest plan. |
| E6b | compute, broken input | Use a deliberately bad normal-depth BC. Expect a non-zero exit that names the boundary (2026-08-31 notes). |
| E7 | results export | Rasters and inundation polygons through the CLI, if available |
| E8 | results read | Find the WSE, depth and velocity datasets with h5py. Check 5 cells against values read in the GUI. |
| E9 | concurrency | Two computes at once on separate copies: both succeed? Slowdown? |
| E10 | storage | The same compute on shared or mapped storage vs local disk. Run-time ratio. |
| E11 | GPU | Does the GPU solver run in the sandbox (vGPU)? If so, max \|Δ\| on WSE and depth vs CPU on the same plan. |
| E12 | offline start | Startup time and behavior with egress enforced. Any blocked hosts? (Read the egress log.) |
| E13 | determinism | Run E6 twice. Report the max \|Δ\| on WSE, depth and velocity, and whether hashes are identical. |

**Operations with no CLI path.** A person performs the operation once in the GUI on a scratch copy, while the runner takes snapshots (`rasprobe.py snapshot` before and after, then `snapdiff`). That shows exactly which files the GUI writes, which is what a Tier B template workflow needs.

### F — Report and decision

```
uv run python tools/probe/rasprobe.py report --dir $P --out $P\PROBE_REPORT.md
```

The report fills a capability matrix (op × method: CLI / HDF5 edit / API / GUI only / not possible) and suggests a tier using these rules:

- **Tier A:** E2, E3, E5, E6 and E7 all pass through the CLI with no window seen. E4 passes by CLI or by template edit. E6b fails as expected.
- **Tier B:** E6 and E6b pass headless, but at least one of E2/E3/E5/E7 is GUI-only. Base models are authored per domain in the GUI. BCs and plans are edited by template under schema guards.
- **Tier C:** E6 is not headless. A person runs compute on queued batches. A 1-day UI-automation spike follows. Report the schedule impact to the project owner.

E8–E13 then set:
- the results-reader design
- `max_parallel_runs` and the scratch location
- whether the GPU may be used
- the determinism tolerance used by S6

The lead writes ADR-0001 from the report. The project owner approves it.

## 3. Antigravity CLI (`agy`) probe

Same tools, separate output folder `docs/probe/agy/`.

1. `cliprobe.py crawl --exe agy --out docs/probe/agy/cli --timeout 20`. `login` and `logout` are on the risky list and are skipped.
2. `agy --version` and `agy models`. Record the model slugs. Any non-Gemini models answer open item O8.
3. Run `rasprobe.py smoke --spec tools/probe/smoke.agy.example.toml --out docs/probe/agy/smoke` (after review). It covers:

   | Op | Test | Expect |
   |---|---|---|
   | G1 | envelope: `agy -p "Reply with exactly: OK" --output-format json --print-timeout 2m` | Exit 0; JSON with `status`, `response`, `usage.total_tokens`, `duration_seconds` |
   | G2 | bad model: `--model not-a-model` | Non-zero exit, `status` = `ERROR` |
   | G3 | confinement, default permissions: in a scratch git repo, ask it to write `../escape.txt` | Soft-denied, exit 0, nothing written outside cwd |
   | G4 | confinement with `--dangerously-skip-permissions` | If anything is written outside cwd, the runner must never use this flag and must rely on `permissions.allow` rules |
   | G5 | small edit task with allow rules | File created, test passes, usage recorded |
   | G6 | timeout: `--print-timeout 10s` on a long task | Exit status and `status` value recorded for the runner's retry logic |

4. Quota exhaustion can't be triggered on purpose. The runner stores raw stderr and the envelope for the first quota event so the cooldown parser can be fitted to the real message.

## 4. Re-probe on a RAS update

Run A, B, D, then E6, E8 and E13 against the new build, and diff against the pinned report:
- `rasprobe.py h5diff` for schemas
- `cli_tree.json` diff for commands

Any difference means an ADR-0001 addendum and the golden regression (REQUIREMENTS §3.4) before `ras_pin.toml` changes.

# flowfield2d feature candidates from methow-hydraulics (2026-10-27)

Lessons from the Methow build (41 domains, 3 ft DEM, RAS 2025 GPU via the queue). Each item would work unchanged for
another river, so it belongs here (CLAUDE.md rule). "Move" = code exists in methow-hydraulics and should be lifted
with its tests; "new" = not written yet. Ranked within each group by what it would have prevented or saved.

## A. Correctness guards (would have caught real errors)
| # | Feature | Lesson | Kind |
|---|---|---|---|
| A1 | **Terrain vertical-unit check**: before a terrain is used, sample the source DEM and the RAS terrain (or the prepared model's cell minimum elevation) at a few points and fail if they differ by a unit factor (3.2808, 0.3048) or beyond a tolerance; also refuse a DEM whose CRS has no vertical unit unless the unit is declared in config | The 3 m DEM stored feet under a metric CRS; RAS scaled elevations x3.28 and a day of runs was void before anyone noticed | new |
| A2 | **Outline DEM = terrain consistency**: assert the DEM used for domain generation and the model terrain agree in vertical scale at the seed points | ch3f/ch2 failed with "No flood area found" because the outline DEM and the terrain disagreed | new |
| A3 | **Terrain coverage check** before `plan prepare`: every mesh cell (or the seed polygon) lies inside the terrain's valid extent; report the uncovered area instead of RAS's "Missing terrain data at Face N" | d03 seed region ran past the clip | new |
| A4 | **Storage-based flow balance** as the default for results without face flows: outflow = inflow - dV/dt from the cell elevation-volume tables (backward differences at hold ends) | Velocity x face-area rebuild read 17% low at the d03 outlet; CPU check confirmed storage matches RAS's exact outflow | move (`_boundary_flows` storage path; `results.storage_volume` already here) |
| A5 | **Map-spike masking** in post: drop depth-raster pixels deeper than the deepest model cell + margin, count them | RAS mapper drew 446-2,819 ft depths at small cells | move (methow `_post_stage`) |
| A6 | **Convergence records that locate failures**: failing cell ids/coordinates, wet-point count, `unmonitored` holds that never trigger extensions | Domain-level flags marked 6 steady reaches not_converged; a dry 18 cfs hold forced two useless extensions | move (`plateau_record`) |
| A7 | **Monitored-cell selection** (clear of BC lines, carries flow, min depth) as a library function | Stagnant and boundary cells caused false non-convergence | move (`_monitored_cells`) |

## B. Run operations (queue, worker, state)
| # | Feature | Lesson | Kind |
|---|---|---|---|
| B1 | **Queue job cancel/withdraw** (`flowfield2d queue cancel <job|run-root>`): removes pending job + marker + job record atomically; for running jobs writes a cancel request the worker honours (kill ras.exe, no requeue) | Withdrawing jobs by hand left stale records; a killed job was requeued as "interrupted"; host processes needed Chris | new |
| B2 | **Run-root archive** (`archive <root>`) that also retires the root's queue job records | A rebuilt root at the same path adopted an old job's result (fixed in `collect`, but the records should go with the root) | new |
| B3 | **Queue hold/release** (pause claiming without stopping the worker) | Needed for the slot test; done with an ad-hoc marker-moving script | new |
| B4 | **Worker config file + one-click launcher** (slots, processor, RasDir) instead of command-line copies; worker writes GPU utilisation (nvidia-smi) per job into `status.json` | Commands could not be copied out of the sandbox; slot count was a host-side guess | new |
| B5 | **Throughput benchmark** (`queue bench <job> --slots 1,2`): same job alone vs concurrent, recommends slots | One job alone was ~40% faster than two on the RTX 4070 Ti | new |
| B6 | **Queue status / ETA** (`queue status`): pending, running with progress % from solve.log, done; ETA from per-km GPU rates of finished jobs | Every status check was a hand-written shell loop | new (rates logic in methow `estimate_production.py`) |
| B7 | **Atomic writes that survive Windows locks** everywhere (state, registry, markers) | `replace_retry` added after a PermissionError killed a study | partly done (runs.py); extend to all writers |
| B8 | **Per-variant study runs and resume** (`--variant`, re-run failed variant only, compare when all done) and a study status report | Two study processes failed mid-way; comparisons had to be run by hand | move (methow `studies.py`) |
| B9 | **Reset a failed run** in place (`run reset <domain>`): clear FAILED registry records and stage stamps so a re-launch retries | Failed variants had to be moved aside to retry | new |

## C. Model building
| # | Feature | Lesson | Kind |
|---|---|---|---|
| C1 | **Terrain builder**: clip a large DEM per domain (seed region + margin), create/populate a RAS terrain with absolute paths, verify (A1/A3) | `ras terrain add` needs rooted paths; clips were scripted by hand twice | move (methow `build_terrain_clips.py`) + new |
| C2 | **Clone only the terrain a geometry uses** | Every run project copied all terrains (680 MB) - ~110 GB for one production run | new |
| C3 | **Reach-network domain layout**: orient by DEM, link network, split by flow-change rule, drop stubs | Generic for any reach layer + flow table | move (methow `domain_layout.py`) |
| C4 | **Channel refinement + channel roughness class** from a flow's inundation polygon in one call | Built in methow channel mode; reusable | move (`_channel_polygons`, `_channel_spec`) |
| C5 | **Warm-start orchestration** (coarse fill -> short first hold) | Big runtime saver; currently pipeline-specific | move |
| C6 | **Depth-variable roughness** (D84 / Limerinos by substrate) | Backlog R-2 | new |

## D. Post-processing and reporting
| # | Feature | Lesson | Kind |
|---|---|---|---|
| D1 | **Per-feature (reach) metrics export** with reason codes (`ok`, `not_converged`, `too_shallow_to_monitor`, `not_modelled`, `not_run`) as a generic exporter; parquet when pyarrow is present | OUT-1 logic is generic | move (methow `export_edt.py`) |
| D2 | **Faster reach ownership** for large rasters (tile/STRtree by window, cache per domain) | The 3 ft export took ~25 min for 41 domains | new |
| D3 | **Run summary** (steady and balanced share, QA failures by check, spikes, GPU minutes) and **per-reach dWSE report** for unsettled holds | Written as scratch scripts during review | move (`run_summary.py`) + new |
| D4 | **Re-evaluate a finished run** with current QA rules from stored results (no solves) | Needed twice (3 m re-evaluation, per-reach flags) | move (`reevaluate_convergence.py`) |
| D5 | **Study comparison masked to wet cells** | m6 vs m9 showed 1.8 ft from dry edges | done |
| D6 | **WSE-rise review aid**: list rises with station, local bed/structure context and a profile snippet per rise | 86 rises need human review at G2 | new |

## E. Engine probes and limits to track (RAS 2025 0.1.0.5048-dev)
- GPU writes zero FaceFlow, FaceArea, CellVolume even with `Extra output fields`; no reference/monitor lines; `MonitorPolyline` exists only inside the CPU engine. Re-probe on any new pinned build (C/A4 depend on it).
- GPU ignores `Maximum Courant`; deterministic; uses one GPU poorly for small meshes (one slot best).
- `ras terrain add` requires absolute paths; a failed add leaves a partial copy that blocks the retry.
Record these in `docs/probe/` with a probe script each, so a build change is caught by `run.bat` probes.

## Suggested order
A1-A3 (guards) -> A4-A7 + D1 (lift methow code with tests) -> B1, B2, B9 (queue hygiene) -> C1, C2 (terrain and disk)
-> B4-B6 (worker and status) -> D2-D6 -> C3-C6.

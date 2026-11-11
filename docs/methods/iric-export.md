# Exporting a model to iRIC (FaSTMECH, Nays2DH)

Decision record: ADR-0005. Code: `curvigrid`, `export.iric`, `export.iric_project`,
`engines.ras2025.export`, `roughness.rasterize_n`.

## What you need
| Input | Notes |
|---|---|
| Terrain | One raster, a stack of rasters, or a RAS terrain layer. Name the horizontal and vertical units. |
| A line along the flow | Upstream to downstream. WKT file or one LineString in a GeoPackage layer. |
| Grid width, `ni`, `nj` | Width across the line in terrain CRS units; sections along; nodes across. |
| Roughness | A Manning's n raster, one value, or a RAS n layer with its classification layer (optional). |
| A result file | For discharge, stages and the WSE points (optional). |
| An iRIC template project | Only for a runnable project: in iRIC choose the solver, then File > Save. |

## Command
```
flowfield2d export iric --out OUT \
  --ras-terrain Terrains/<terrain>.h5 --xy-unit "US survey foot" --z-unit foot \
  --centerline line.wkt --smooth 40 --width 60 --ni 301 --nj 21 \
  --ras-n-layer "Surface Layers/<n layer>.h5" --ras-class-layer "Surface Layers/<classes>.h5" --n-res 1 \
  --results Results/<plan>.h5 --model-unit foot --inflow-line "<BC line>" --tol 5 \
  --solver fastmech --drag-depth local \
  --template empty_fastmech.ipro --definition <iRIC>/solvers/fastmech/definition.xml
```
For Nays2DH: `--solver nays2dh --duration <seconds>` with a Nays2DH template and definition, and no
`--drag-depth`. Plain rasters work in place of the RAS layers: `--terrain` (repeat for a stack) and
`--roughness` or `--manning-n`.

## What it writes
| File | Use in iRIC |
|---|---|
| `grid.csv` | Import > Grid (iRIC grid CSV). |
| `elevation.tif`, or `elevation_1.tif` ... for a stack | Import > Geographic Data > Elevation. Set the project coordinate system in iRIC first; the importer asks for it. For a stack import every file; the highest number has priority. |
| `elevation.tpo` | The same terrain as a point cloud (`--tpo-spacing`). |
| `manning_n.tif` | Geographic data for a roughness attribute that takes n. |
| `wse.csv` | Import > Measured Data: the source model's WSE, depth and speed at wet cells. |
| `summary.json` | Discharge, downstream and upstream stage, WSE by section, units. |
| `project.ipro` | Open directly (with `--template`). |

All lengths are metres. x and y are the terrain coordinates times the metres per horizontal unit.

## Grid
- i runs along the line; j runs from the right bank to the left bank looking along i.
- Sections are normal to the line. If sections cross inside the grid (bend radius under half the width) the
  build stops and names the chainage. Round the line with `--smooth <length>`, narrow the grid, or reduce
  `ni` through the bend. A digitised line with vertices usually needs some smoothing.
- Every node needs a terrain value; a grid that runs off the terrain or onto nodata is refused.
- One grid follows one flow path. Where the model splits flow between outlets, a grid along one branch
  carries only part of the picture; see "Flow state".

## Terrain and roughness from RAS layers
- A RAS terrain layer lists its rasters in order; where they overlap the later one covers the earlier one.
  The export samples the stack as it is (no resampling) and writes one GeoTIFF per raster.
- A RAS n layer in classification mode gives n per class and a value where no class applies; the
  classification layer gives the class polygons. `--n-res` sets the cell size of the n raster built from them.
  A later polygon covers an earlier one.
- Check which geometry a plan uses in the project file before choosing the layers: the plan name does not
  have to match its geometry.

## Flow state
- Discharge: the sum of |flow| through the named inflow lines at the chosen output, or `--discharge`.
  BC lines are matched to perimeter faces within `--tol`; a short inflow line may need a few model units.
- Node WSE: the nearest wet cell within two section spacings. Downstream and upstream stage are the mean
  node WSE of the last and first sections.
- The export does not check that the chosen output is steady or that the grid carries the whole inflow. If
  storage is still changing, or part of the flow leaves by another outlet, the stage and discharge handed to
  the second solver do not describe one steady state. Check inflow against outflow first.

## Solver conditions written to a project
| Solver | Written | Left as the template has it |
|---|---|---|
| FaSTMECH | Constant discharge, constant downstream stage, initial surface from the upstream stage, roughness by node when the grid carries it | Iterations, relaxation, eddy viscosity, wetting and drying |
| Nays2DH | Downstream water surface from the time series, time unit seconds, a two-row series holding discharge and downstream stage for `--duration` | Time step, output interval, initial surface, bed deformation, turbulence model |

The left-hand settings are solver judgment. Review them before trusting a run; a run at the defaults can
finish without converging.

## Solver settings: starting points
From the FaSTMECH manual (v2.1), the Nays2DH solver manual and tutorials, and test runs on one small
split-flow channel (2026-11-11). They are starting points; pass them with `--condition NAME=VALUE`.

FaSTMECH needs a grid whose centerline follows the flow. On a wide grid laid along the valley, with a
narrow channel meandering inside it, the solution pooled 0.4-0.5 m above the source model and stopped or
drifted at every setting tried; halving the cell size once removed the stops but not the pooling, and
halving it again diverged. A grid 40 ft wide along the channel itself converged at every initial surface
tried and matched within 0.03 m. Use one channel-following grid per flow path, and Nays2DH where one grid
has to span several paths.

FaSTMECH
| Setting | Start with | Note |
|---|---|---|
| `FM_HydAttWSType`, `FM_HydAttWS1DCD` | 2 (1D step-backwater); 1D drag 0.05-0.2 | The initial surface fixes which nodes are wet. Too low a drag leaves a dry section and the solver stops at the first iteration ("Error at qprms"); too high floods the grid. Expect to tune it per discharge. |
| `FM_HydAttLEVType`, `FM_HydAttEVC` | Constant; (0.001 to 0.01) x depth x velocity, m2/s | The manual's rule. On cells well under 1 m wide, values of 0.01 and above diverged in testing; 0.001-0.003 held. |
| `FM_SolAttERlx`, `FM_SolAttURlx`, `FM_SolAttARlx` | 0.3, 0.5, 0.5 | The defaults (0.4, 0.2, 0.2) drifted upward after about 1,000 iterations in testing. |
| `FM_SolAttItm` | 3,000-6,000 | Converged means the mean error on discharge is flat and under 1-2 %. |
| `FM_HydAttCalcWetting` | Off | Re-wetting stopped the solver in every test on a wide, mostly dry grid. |

Nays2DH
| Setting | Start with | Note |
|---|---|---|
| `dt` | Well under the smallest cell size / (velocity + sqrt(g x depth)) | 0.05 s ran on 0.35 m cells at 0.5 m depth. |
| `i_flow` | 2 (uniform flow) | A constant-slope initial surface (0) failed at once on a wide, mostly dry grid. |
| `j_upv`, `j_upv_slope`, `upv_slope` | 1, 1, the reach slope | The slope taken from the grid's upstream end is noisy on a wide grid. |
| `j_cip`, `j_snu` | Defaults (CIP, zero-equation) | `j_snu` and `n_parallel` need `edition` = 1. |
| Duration, `tuk` | Three to five travel times of the reach; output interval about a tenth of that | Check that the last outputs no longer change. |

Both solvers take one stage across the whole downstream section. Where the source model has outlets at
different levels on that section, the second solver cannot reproduce both.

## Roughness
- Nays2DH: Manning's n per cell (`roughness_cell`). The fixed-bed elevation `Elevation_zb` is written equal
  to the bed (no erodible layer), which only matters with bed deformation on.
- FaSTMECH: drag coefficient per node, Cd = g n² / h^(1/3). `--drag-depth` is a depth in metres or `local`
  (the model depth at each node; dry nodes take the median wet depth). Without it no roughness is written and
  the template's constant value applies.

## Limits
See "Not yet verified" in ADR-0005. Solver boundary-condition groups and time series other than the Nays2DH
discharge and stage series are not written; set those in iRIC.

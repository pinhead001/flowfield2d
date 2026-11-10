# Exporting a model to iRIC (FaSTMECH, Nays2DH)

Decision record: ADR-0005. Code: `curvigrid`, `export.iric`, `export.iric_project`,
`engines.ras2025.export`.

## What you need
| Input | Notes |
|---|---|
| Terrain raster | Any unit; name the horizontal and vertical units. |
| A line along the flow | Upstream to downstream. WKT file or one LineString in a GeoPackage layer. |
| Grid width, `ni`, `nj` | Width across the line in terrain CRS units; sections along; nodes across. |
| Roughness | A Manning's n raster or one value (optional). |
| A result file | For discharge, stages and the WSE points (optional). |
| An iRIC template project | Only for a runnable project: in iRIC choose the solver, then File > Save. |

## Command
```
flowfield2d export iric --out OUT --terrain dem.tif --xy-unit "US survey foot" --z-unit foot \
  --centerline line.wkt --width 300 --ni 201 --nj 31 \
  --roughness n.tif --results run.h5 --model-unit foot --inflow-line Inflow --tol 1 \
  --solver fastmech --drag-depth local \
  --template empty_fastmech.ipro --definition <iRIC>/solvers/fastmech/definition.xml
```

## What it writes
| File | Use in iRIC |
|---|---|
| `grid.csv` | Import > Grid (iRIC grid CSV). |
| `elevation.tif`, `elevation.tpo` | Import > Geographic Data > Elevation (raster or point cloud). |
| `manning_n.tif` | Geographic data for a roughness attribute that takes n. |
| `wse.csv` | Import > Measured Data: the source model's WSE, depth and speed at wet cells. |
| `summary.json` | Discharge, downstream and upstream stage, WSE by section, units. |
| `project.ipro` | Open directly (with `--template`). |

All lengths are metres. x and y are the terrain coordinates times the metres per horizontal unit.

## Grid
- i runs along the line; j runs from the right bank to the left bank looking along i.
- Sections are normal to the line. The tangent is taken over one section spacing, so vertices sharper than
  that are rounded.
- If sections cross inside the grid (bend radius under half the width) the build stops and names the
  chainage. Narrow the grid, smooth the line or reduce `ni` through the bend.
- Every node needs a terrain value; a grid that runs off the raster or onto nodata is refused.

## Flow state
- Discharge: the sum of |flow| through the named inflow lines at the chosen output, or `--discharge`.
- Node WSE: the nearest wet cell within two section spacings. Downstream and upstream stage are the mean
  node WSE of the last and first sections.
- For FaSTMECH the project gets constant discharge, constant downstream stage and an initial surface from the
  upstream stage. Every other condition stays as the template has it (iterations, relaxation, eddy viscosity,
  wetting and drying): those are solver settings to review before trusting a run.

## Roughness
- Nays2DH: Manning's n per cell (`roughness_cell`).
- FaSTMECH: drag coefficient per node, Cd = g n² / h^(1/3). `--drag-depth` is a depth in metres or `local`
  (the model depth at each node; dry nodes take the median wet depth). Without it no roughness is written and
  the template's constant value applies.

## Limits
See "Not yet verified" in ADR-0005. Time-series conditions and solver boundary-condition groups are not
written; set those in iRIC.

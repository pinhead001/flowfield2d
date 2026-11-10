# ADR-0005 — Export to iRIC structured-grid solvers

- Status: **accepted** (Chris Nelson, 2026-11-10; proposed by the lead 2026-11-10). Adds scope beyond
  REQUIREMENTS 1: export of a model's inputs and flow state to iRIC structured-grid solvers.

## Context
A second solver on the same terrain, roughness and flow is an independent check on a 2D model. iRIC hosts
several (FaSTMECH, Nays2DH and others). They all need a structured curvilinear (i, j) grid, work in metres, and
are set up through the iRIC GUI or its project file. A RAS 2025 mesh is unstructured, so the mesh cannot be
carried over; the inputs behind it can.

## Decision
1. **Build the grid here.** `curvigrid.build_grid` lays sections normal to a caller-supplied line. A grid whose
   sections cross is refused, not repaired. The line, width and counts are the caller's.
2. **Engine-neutral export.** `export.iric` takes terrain, roughness and a `FlowState` (discharge and per-cell
   WSE in SI). The RAS adapter (`engines.ras2025.export.flow_state`) is the only RAS-specific piece.
3. **Two outputs.**
   - Files iRIC imports: grid CSV, terrain as GeoTIFF and optional `.tpo` cloud, Manning's n GeoTIFF, model WSE
     as a measured-data CSV, and `summary.json` (discharge, stages, WSE profile).
   - A runnable project: `export.iric_project.write_project` clones a project **saved by iRIC** for the solver,
     replaces the grid zone in its CGNS file and sets named scalar conditions. Same rule as RAS templates
     (REQUIREMENTS 3.3): clone what the tool wrote, recreate datasets, exact fixed-width strings.
4. **SI at the boundary.** x, y and z are scaled to metres on export. For a CRS in feet the result is that CRS
   scaled, which is not a registered CRS; exported rasters then carry no CRS and the summary records the scale.
5. **Roughness is the owner's call.** Manning's n is exported as it is. FaSTMECH's drag coefficient is written
   only when the caller names the depth for Cd = g n² / h^(1/3); there is no default.

## Evidence
- CGNS layout read from two iRIC-written projects (iRIC 4.0 and 4.2.1, solver FaSTMECH 1.0 and 1.1.7); the
  writer reproduces node attributes, link creation order, array shapes and value order.
- FaSTMECH 1.1.7 run from the command line on two generated projects (a straight channel in metres; a bending
  channel from inputs in feet with per-node drag): it read the grid, discharge, stage and roughness and wrote a
  solution each time.

## Not yet verified
- Opening a generated `.ipro` in the iRIC GUI (the solver accepts the CGNS file; the GUI has not been tried).
- The grid CSV layout: the header and the `N_`/`C_` column prefixes come from the iRIC exporter plugin; 0-based
  indices, zero K and Z, and blank cell values on the last rows are assumptions until one import is tried.
- GeoTIFF import without a CRS.
- Nays2DH and other solvers: grid attributes are written from the solver's `definition.xml`, but their
  time-series (functional) conditions and boundary-condition groups are not written.

## Consequences
- New modules `curvigrid`, `export.iric`, `export.iric_project`, `engines.ras2025.export`; CLI
  `flowfield2d export iric`. No new dependencies.
- An iRIC update that changes the project layout shows up as a solver or GUI failure on a generated project;
  the fix is a fresh template and, if the node layout changed, a change in `iric_project`.

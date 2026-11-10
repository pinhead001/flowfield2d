# Changelog

## Unreleased
- iRIC export (ADR-0005): `curvigrid` (structured grid along a line, line smoothing, raster and raster-stack
  sampling), `export.iric` (grid CSV, terrain/n GeoTIFF, `.tpo`, WSE points, summary; SI at the boundary),
  `export.iric_project` (runnable `.ipro` cloned from an iRIC-saved template; scalar and table conditions;
  FaSTMECH and Nays2DH steady-state conditions), `engines.ras2025.export` (flow state, terrain layer sources,
  n from classification polygons), `roughness.rasterize_n`, CLI `flowfield2d export iric`. Checked against
  FaSTMECH 1.1.7 and Nays2DH 1.7 (iRIC 4.2.1) from the command line, on synthetic reaches and one real project.
- `units.length_unit_m`: metres per length unit from a CRS WKT or sidecar unit name (foot, US survey foot,
  metre and spellings); for the consumers' terrain vertical-unit guard (A1).

## 0.1.0 — 2026-10-30
First tagged release (G2 item 5, Chris 2026-10-30): the library as used by the Methow 3 ft pre-production run.
- `results` (engine-neutral): depth/velocity/WSE field triples to SI, spike mask, Froude, COG rasters,
  wet extents (MultiPolygon, nesting check), cell tables (Parquet) from rasters or from any `Results`
  object; `post.gpkg`: GeoPackage writer/reader on the standard library (sqlite3). New dependency: pyarrow.
- Engine: `engine.ras2025.pin` (build pin), `h5schema` (fingerprint + guard), `h5edit` (exact fixed-width
  strings, safe dataset recreate, 100-ns ticks, guarded edits), `cli` (ras.exe verb wrapper).
- Building blocks: `hydrograph`, `domains`, `terrain`, `roughness`, `runs` (registry), `provenance`.
- Post and QA: `post.metrics` (shear, per-feature stats), `post.inundation`, `qa.checks`, `qa.calibration`.
- agentops: quota pools with parsed cooldowns and model fallback; empty-response failure rule; pre-acceptance step.
- New core dependencies: rasterio, shapely, psutil.
- Package scaffold per REQUIREMENTS 2; boundary scanner (`rasdrive.boundary`) and `tests/test_boundary.py`.
- `rasdrive.agentops`: status-line meter, ledger, task-card queue, delegate runner, governor, hooks, `agentops` CLI.

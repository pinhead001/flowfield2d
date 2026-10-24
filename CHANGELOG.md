# Changelog

## Unreleased
- Engine: `engine.ras2025.pin` (build pin), `h5schema` (fingerprint + guard), `h5edit` (exact fixed-width
  strings, safe dataset recreate, 100-ns ticks, guarded edits), `cli` (ras.exe verb wrapper).
- Building blocks: `hydrograph`, `domains`, `terrain`, `roughness`, `runs` (registry), `provenance`.
- Post and QA: `post.metrics` (shear, per-feature stats), `post.inundation`, `qa.checks`, `qa.calibration`.
- agentops: quota pools with parsed cooldowns and model fallback; empty-response failure rule; pre-acceptance step.
- New core dependencies: rasterio, shapely, psutil.
- Package scaffold per REQUIREMENTS 2; boundary scanner (`rasdrive.boundary`) and `tests/test_boundary.py`.
- `rasdrive.agentops`: status-line meter, ledger, task-card queue, delegate runner, governor, hooks, `agentops` CLI.

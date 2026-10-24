# rasdrive

A location-agnostic driver for HEC-RAS 2025 2D models. It covers:
- engine adapter and HDF5 schema guards
- the Phase 0 probe
- domain, terrain, roughness and hydrograph builders
- runs, post-processing, QA and calibration
- agent ops for Claude Code with headless delegate workers

Project repos (for example `methow-hydraulics`) supply all site-specific inputs and choices, and pin a tagged release.

- Spec: `REQUIREMENTS.md`
- Phase 0 procedure: `docs/PROBE_PROCEDURE.md`
- Probe tests: `uv run --with h5py --with pytest --with pefile --with dnfile --with psutil --with rasterio pytest tools/probe/tests`

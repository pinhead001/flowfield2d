# CLAUDE.md — rasdrive

General HEC-RAS 2025 2D driver. Spec: `REQUIREMENTS.md` (wins over this file). Probe: `docs/PROBE_PROCEDURE.md`.
The checkout directory is `flowfield`; the package is `rasdrive` (final name: open item O9).

## Boundary rule (hard)
No place, stream or agency names, reach-layer schemas, CRS codes, file paths, habitat-model vocabulary,
or basin-tuned defaults in `src/`, `tools/`, `docs/`. Every project choice is a parameter or config input.
`tests/test_boundary.py` scans with the consumer term lists in `RASDRIVE_BOUNDARY_TERMS` (os.pathsep list).
If a function only makes sense for one project, say so and put it in that project's repo.

## Layout
- `src/rasdrive/` per REQUIREMENTS 2. Deviation: agent ops live at `src/rasdrive/agentops/`
  (importable by consumers; CLI `agentops`), not a top-level `agentops/`.
- `tools/probe/` — tested probe tools. Don't rewrite; fix real bugs with a test each.
- `tests/unit`, `tests/integration` (marker `ras`, deselected by default), `tests/fixtures` (synthetic only).
- `docs/adr/` one ADR per decision; `docs/methods/` project-free method notes; `docs/probe/<build>/`.

## Commands
- `uv sync` (dev + probe groups) · `uv run pytest -q` · `uv run pytest -m ras` (needs pinned RAS)
- `uv run ruff check src tests` · `uv run mypy` (strict on src; sqlite cache off for mapped folders)
- `uv run agentops --config <project agents.toml> gov status`

## HDF5 rules (REQUIREMENTS 3.3)
Schema guard before any edit · fixed-width NULLTERM strings, mem type == file type (h5py default drops
the last char) · recreate datasets, never resize · time in 100-ns ticks · clone RAS-written templates only.

## RAS
Pinned build; never update RAS. Updates follow REQUIREMENTS 3.4. Probe/smoke only on scratch copies;
non-help RAS commands only from a reviewed `tools/probe/smoke.toml`.

## Working rules
- TDD; unit tests offline. Small commits; this repo's commits are separate from the consumer's.
- Never push (blocked). agy branches are `card/<id>` in worktrees; the lead reviews and merges, agy never does.
- Engineering judgment (roughness, BC placement, flow statistics, tolerances) is the project owner's.
- Release: semver tag + CHANGELOG entry naming the RAS build tested against.

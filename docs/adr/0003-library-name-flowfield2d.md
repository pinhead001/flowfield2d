# ADR-0003 — Library name: flowfield2d

- Status: accepted (Chris Nelson, 2026-10-24) · Resolves open item O9 of the first consumer's spec

## Context
The general library started under the working name `rasdrive`, checked out in a folder called `flowfield`.
Neither name fits. `rasdrive` ties the library to one engine, while the design keeps a neutral core with
engine adapters (`engines/ras2025/` first) so other 2D engines can be added later. `flowfield` is already
taken on PyPI by an unrelated package, so a consumer resolving it from an index would get the wrong code.

## Decision
- The distribution name, import name and repository folder are all `flowfield2d` (`D:\a\flowfield2d`).
- Engine code lives under `flowfield2d.engines.<engine>`, previously `engine` (singular). Scope stays HEC-RAS 2025
  only; capability flags arrive with the engine Protocol (P1 task R5) once probe step E has run.
- The boundary-term variable is renamed `RASDRIVE_BOUNDARY_TERMS` -> `FLOWFIELD2D_BOUNDARY_TERMS`, and the
  console script `rasdrive` -> `flowfield2d`.
- Consumers depend on it only through a path or git source, never a package index.

## What changed
- `git mv src/rasdrive src/flowfield2d` and `engine/` -> `engines/`. Imports, entry points, `pyproject.toml`,
  `uv.lock`, CLAUDE.md, AGENTS.md, `.claude/` settings and agents, REQUIREMENTS, PROBE_PROCEDURE, README, tests
  and fixtures were all updated in one commit. The agentops config, card queue and worktree paths moved with them.
- ADR-0001 and ADR-0002 keep their original text and carry a one-line pointer to this ADR. CHANGELOG
  history is unchanged.
- The first consumer moved to an absolute editable path source (`flowfield2d = { path = "D:/a/flowfield2d",
  editable = true }`).

## Guard tests
- `tests/test_rename_guard.py` (this repo) fails if `rasdrive` or a bare `flowfield` (not followed by `2d`)
  appears in code, config or docs, except in this ADR, the CHANGELOG, and ADRs that carry the rename pointer.
- The consumer has a lockfile-source test that fails unless `uv.lock` resolves `flowfield2d` from a path or git
  source, never from a package index.

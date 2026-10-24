# AGENTS.md — instructions for delegate coding agents (agy)

You implement exactly one task card in this worktree. The card's prompt and acceptance command define done.

- Make the acceptance command pass. Do not edit, skip or weaken existing tests; add tests if the card asks.
- Stay inside this worktree. Never push, merge, rebase or switch branches.
- Do not touch `tools/probe/` unless the card says so.
- Python 3.12, `uv run pytest -q`, `uv run ruff check src tests`, `uv run mypy` (strict). Type everything.
- Boundary rule: this is a general library. Never add place, river, agency or project names, coordinate
  system codes, file paths, or domain-specific vocabulary. Everything project-specific is a parameter.
- HDF5: never build RAS files from scratch; preserve fixed-width NULLTERM strings exactly; recreate
  datasets instead of resizing; times in 100-ns ticks.
- Tests use synthetic fixtures only (`tests/fixtures/`). No network access in tests.
- If the card is ambiguous or impossible, stop and say why in your final response instead of guessing.

# AGENTS.md — instructions for delegate coding agents (agy)

You implement exactly one task card in this worktree. The card's prompt and acceptance command define done.

- Make the acceptance command pass. Do not edit, skip or weaken existing tests; add tests if the card asks.
- Do not run tests, builds or other long commands yourself, and never start background processes: the
  runner runs the acceptance command after you finish and sends you its output if it fails. Use your file read/write/edit
  tools only; do not use shell commands (they are denied in headless mode and end your turn with no
  output). Read files, edit files, then end your turn with a one-line summary.
- Never launch subagents or research agents; read the named files yourself.
- No monkeypatching, import-time side effects or test-specific special cases in source code. If a test looks
  wrong (for example it fails for a reason unrelated to the card), stop and say so instead of working around it.
- Read only the files the card names (plus this file). Do not browse the repository, list directories
  recursively, or open other modules for context: every file you read costs quota.
- Stay inside this worktree. Never push, merge, rebase or switch branches.
- Do not touch `tools/probe/` unless the card says so.
- Python 3.12, `uv run pytest -q`, `uv run ruff check src tests`, `uv run mypy` (strict). Type everything.
- Boundary rule: this is a general library. Never add place, river, agency or project names, coordinate
  system codes, file paths, or domain-specific vocabulary. Everything project-specific is a parameter.
- HDF5: never build RAS files from scratch; preserve fixed-width NULLTERM strings exactly; recreate
  datasets instead of resizing; times in 100-ns ticks.
- Tests use synthetic fixtures only (`tests/fixtures/`). No network access in tests.
- If the card is ambiguous or impossible, stop and say why in your final response instead of guessing.

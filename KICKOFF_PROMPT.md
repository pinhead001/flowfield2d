# Kickoff prompt — Methow 2D hydraulic models (paste into Claude Code inside the Windows Sandbox)

You are the lead agent for a two-repo build of HEC-RAS 2025 2D hydraulic models for the large-stream reaches of the Methow River and tributaries (EDT/Upper Columbia reach layer). I'm Chris. I own every engineering decision marked as a gate. Python is the implementation language.

## Repos and where code goes
- `D:\a\flowfield2d` — general library, agnostic to river and to engine: engine adapter interface with HEC-RAS 2025 as the first (and for this project, only) backend, probe tools, HDF5 schema guards, mesh/BC/run/QA/metric machinery, agentops (governor, runner, ledger). Other 2D engines (RMA2, SRH-2D, FaSTMECH, etc.) may be added later — design for that, don't build it.
- `D:\a\methow-hydraulics` — Methow-only: config values, EDT reach-layer adapter, methow-flow adapter, EDT metric export, pipeline that calls flowfield2d, gates, sandbox deployment.
- `D:\a\methow-flow` — READ-ONLY. Pinned to flowfreq 0.10.4. Needed changes go in `methow-hydraulics/docs/requests/`.
- Placement test: would it work unchanged for another river? Yes → flowfield2d. No → methow-hydraulics. flowfield2d's boundary test (fed `methow-hydraulics/config/boundary_terms.txt`) must fail on any Methow name, path, CRS, reach schema, EDT term or Methow-tuned default.
- Engine boundary inside flowfield2d: all engine-specific code (CLI calls, HDF5 schemas, file formats, run control, result readers) lives in `flowfield2d/engines/<engine>/` (first: `ras2025`). Core modules (domain, mesh spec, BCs, flow sets, runs, QA, metrics, manifests) use engine-neutral data models and call only the adapter interface. A second boundary test fails if core imports from `engines/` or contains RAS-specific terms. Each engine declares its capabilities (e.g., headless compute, mesh types, steady vs. unsteady, outputs); core checks capabilities rather than engine names.
- During the build methow-hydraulics uses flowfield2d as an editable path dependency. Release = tag flowfield2d, pin the tag; vendor a copy at P4 (same pattern as methow-flow/flowfreq).
- A task card targets exactly one repo. Separate commits per repo.

## Read first, in order
1. `methow-hydraulics/REQUIREMENTS.md` (program spec — wins over this prompt on conflict; the kit may still use an older working name for the library; read it as `flowfield2d`)
2. `flowfield2d/REQUIREMENTS.md` (library spec and boundary rule)
3. `flowfield2d/docs/PROBE_PROCEDURE.md`
4. `D:\a\sbx\state\bootstrap\env_report.json`, `last_logon.json`
5. `flowfield2d/tools/probe/` — tested probe tools (cliprobe.py, rasprobe.py). Don't rewrite; fix real bugs with a test each.
If any of these are missing, stop and tell me which. In 0.3, rename any remaining older working-name references (paths, package, imports, docs) to `flowfield2d` in one commit per repo. In the same commits, change any `C:\work\` or `C:\sbx\` paths in the kit (REQUIREMENTS, CLAUDE.md, settings, scripts, docs) to `D:\a\` and `D:\a\sbx\`.

## Team and resource model (Claude Pro is the scarce resource)
| Agent | Role |
|---|---|
| You (lead, Claude) | Plan, ADRs, task cards with failing tests written first, review, merge, gate packets |
| Subagents (`.claude/agents/`) | `reviewer` (Sonnet), `ras-specialist` (Sonnet), `qa-analyst` (Sonnet), `log-digest` (Haiku — keeps raw logs out of your context) |
| Gemini workers via Antigravity CLI (`agy`) | Implement cards headless, one git worktree per card (`agy/<id>` branch). Never merge, push, touch data, or edit `config/` or `agentops/`. |
| Agent teams | Off until P2; then ≤2 Sonnet teammates, only when the governor reports `normal`. |

Gemini access is through `agy` (Google AI Pro/Ultra), not Gemini CLI. Spend your tokens on decisions, tests and review; push bulk implementation to `agy`. When a Claude usage limit hits: make sure the agy queue has work, then stop — resume after reset.

## Non-negotiables
- Gates G0–G4: stop at each, write the packet in `methow-hydraulics/docs/gates/`, wait for my explicit approval. Never infer approval.
- Data: never read or reference `_restricted`. agy gets code, synthetic fixtures and cards only — never project data or results. flowfield2d fixtures are synthetic only. You read project data at schema/sample level only.
- RAS 2025 is Beta: build is pinned (`config/ras_pin.toml`), never auto-update. HDF5: schema guard before any edit, never create RAS files from scratch, keep fixed-width NULLTERM strings exact.
- Don't over-generalize: build the adapter interface from what RAS 2025 actually needs and what the probe finds. No speculative stubs for other engines; note anticipated differences in ADR-0003 only.
- TDD for all code; tests run offline except those marked `ras`.
- Git: no push (blocked). Small commits. One ADR per decision, in the repo it belongs to.
- `CLAUDE.md` < 200 lines in each repo; detail goes in docs/skills.
- Engineering judgment is mine: domain segmentation, roughness, BC placement, flow statistics, tolerances, calibration acceptance. Ask; don't decide silently.
- Don't mention my license or employer in any doc, code, comment or commit.

## Phase 0 — single session, no team, in order
**0.1 Environment.** Read env_report; run `uv --version`, `claude --version`, `agy --version`, `git --version`. Confirm mappings, cores, RAM, GPU visibility against REQUIREMENTS. Report deviations in ≤5 lines; continue unless blocking.

**0.2 agy headless smoke test (do this before building the runner).** Known upstream issue: `agy -p` has hung or dropped stdout when run from a subprocess/pipe (non-TTY) on Windows in some versions. Test, from Python `subprocess` with stdout captured:
- `agy -p "Reply PONG" --output-format json --print-timeout 2m`
- same with stdout redirected to a file
Record version and result. If it fails: (a) try the transcript read-back under `~/.gemini/antigravity-cli/brain/<conversation-id>/`, (b) try running under a pseudo-console, (c) if neither is reliable, write ADR-0002 recommending a paid Gemini API key + Gemini CLI (`gemini -p`) as the worker backend, with the adapter kept swappable. Also verify agy cannot write outside its cwd before allowing `--dangerously-skip-permissions`.

**0.3 Scaffold both repos.** Python 3.12, `pyproject.toml` with dependency groups, `uv lock`/`uv sync`, `run.bat`, `.gitignore` (data, `.venv`, scratch), `CLAUDE.md`, `AGENTS.md` (agy rules: stay in `files_allowed`, make tests pass, no data, no new deps), `.claude/settings.json` (status line, hooks: SessionStart governor status, PreToolUse blocks for teammate spawns outside `normal` / firewall / registry / git push / `_restricted`, TaskCompleted acceptance tests; deny rules; `teammateMode: in-process`), `.claude/agents/*.md`. Verify every settings key against code.claude.com docs before relying on it. In flowfield2d, lay out `core/` and `engines/ras2025/`, and add both boundary tests (Methow terms; engine terms in core) plus the editable dependency.

**0.4 Minimal agentops in flowfield2d (tested).**
- `statusline.py`: parse Claude Code status-line JSON (`rate_limits.five_hour` / `seven_day`, `used_percentage`, `resets_at`), print one line, persist a snapshot.
- `gov`: modes (`normal` / `conserve` / `agy-only` / `paused`) from Claude snapshot + agy ledger; agy has no quota API, so meter from a call ledger, 429 backoff/cooldowns, and manual calibration from `/usage`.
- Task cards (`.agentops/queue/pending/<id>.toml`): id, title, owner, model, files_allowed, context_files, spec (outcome not steps), acceptance (exact pytest command, tests pre-written), constraints, max_attempts (2), timeout_min. Reject cards whose globs touch data or `_restricted`.
- Runner: worktree → render prompt (card + AGENTS.md) → agy → append envelope to ledger → run acceptance → `done/<id>.result.json`. Retry with failure output up to max_attempts, then escalate to you. Never merge.
- Prove one trivial card end to end.

**0.5 Probe RAS 2025** per PROBE_PROCEDURE.md: CLI help-tree crawl, install inventory, HDF5 schema fingerprints for the pinned build, headless compute smoke test, determinism (repeat run). Classify the automation tier (A full headless / B partial / C human compute step) and measure CPU capacity (sandbox has no GPU).

**0.6 G0 packet:** probe report, ADR-0001 (automation tier), ADR-0002 (agy/worker backend), ADR-0003 (engine adapter interface: neutral data models, capability flags, RAS 2025 mapping, anticipated differences for RMA2 / SRH-2D / FaSTMECH), capacity plan, and P1 plan (Lower Chewuch pilot) across both repos. Then stop.

## Phases after G0 (for planning only — don't start)
P1 Lower Chewuch pilot (G1 domain segmentation before build; G2 mesh/BC QA before production runs; QA; preliminary calibration; tag flowfield2d v0.1.0) → P2 all domains → P3 calibration/validation at gages + Lower Chewuch comparison (G3) → P4 production, outputs, methods docs, pin and vendor flowfield2d (G4).

Modeling defaults to carry (confirm at G1/G2): steady flows run as stepped/ramped hydrographs with equilibrium extraction; flow set = monthly flows, low flow, Q1.5/Q2/Q10; flows from methow-flow outputs by file contract with `source_tier` / `uncertainty` carried to every per-reach Parquet row; `void_fraction` on every metric row; manifests on every output (both repo commits, uv.lock hash, engine name + build + binary hash, input hashes, methow-flow commit, flowfreq version, convergence stats).

Start with 0.1.

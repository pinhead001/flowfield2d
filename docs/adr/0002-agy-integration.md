# ADR-0002 — Delegate coding agent integration (Antigravity CLI `agy`)

- Status: accepted (G0, 2026-10-24)
- Date: 2026-10-23
- Evidence: `docs/probe/agy/` (CLI crawl, `models.txt`, smoke G1–G6), agent-ops ledger of the first cards

## Context
The lead agent writes specs, tests and reviews; a headless delegate writes most code (REQUIREMENTS 7).
`agy` 1.4.7 is the delegate. Its behavior was unknown until probed.

## Findings
| Op | Result | Consequence |
|---|---|---|
| G1 envelope | exit 0; JSON `conversation_id`, `status`, `response`, `duration_seconds`, `num_turns`, `usage.{input,output,thinking,cache_read,total}_tokens` | Ledger records `usage.total_tokens` and duration per call |
| G2 bad model | exit 1; `status: ERROR`, `error` field lists valid models | Non-zero exit or `ERROR` = failed call |
| G3 / G3b confinement (default, `--mode accept-edits`) | Refused to write `../escape.txt`; nothing written | Worktree is the working boundary |
| G4 `--dangerously-skip-permissions` | Also refused — but by model judgment, not a hard block | The runner **never** uses this flag |
| G5 small edit | Blocked by our own `read_file`/`write_file` deny rule on the data root (scratch lived under it) | Deny rules are enforced on writes inside the workspace; edit capability proven by card `p0-units` instead |
| G6 `--print-timeout 10s` | exit 0, `status: SUCCESS`, **empty `response`**, stderr `print timeout ... returning partial output` | Status alone is not trustworthy |
| Headless permission denial (card `p0-units`) | Any tool without an allow rule is auto-denied; the call still returns exit 0, `SUCCESS`, empty `response`; reason on stderr | Runner treats an empty response as a failed call and feeds stderr into the retry prompt |
| `agy models` | Gemini 3.8 Flash (high/medium/low), Claude Sonnet 4.6, Claude Opus 4.6, GPT-OSS 120B | O8: yes, non-Gemini models exist |

## Decision
1. **Invocation:** `agy -p <card prompt> --output-format json --model <m> --print-timeout <t> --mode accept-edits`,
   cwd = the card's worktree. Default model `gemini-3.8-flash-high`; a card may name another.
2. **Success rule:** exit 0 **and** `status != ERROR` **and** non-empty `response`, then the card's acceptance
   command passes in the worktree. Only then does the runner commit to `card/<id>`. It never merges.
3. **Permissions** (user settings, `~/.gemini/antigravity-cli/settings.json`; precedence Deny > Ask > Allow):
   allow `uv run pytest|ruff|mypy`, read-only `git status|diff|log|show`, and read-only listing/search
   cmdlets; deny git push/merge/rebase/checkout/switch/reset/branch/worktree/remote/config, firewall and
   registry commands, any command naming the data, inputs, read-only repo or sandbox-state roots or using
   `../`, `read_file` on those roots, and `write_file` on the main checkouts and `.git/`.
4. **Worktrees:** one per card, `<worktree_root>/<prefix><repo>-<id>`, sited so consumers' relative
   editable dependencies resolve. Commits survive a sandbox close; uncommitted worktree files may not.
5. **Retries:** up to `max_retries` (2) with the acceptance tail and delegate stderr appended; then
   `escalated` for the lead.
6. **Quota:** no headless readout. A quota-like failure (`quota|rate limit|resource exhausted|429`)
   requeues the card and saves the raw envelope under `quota_events/` so the cooldown parser can be
   fitted to the first real message. Remaining % = manual calibration from agy's `/usage` minus ledger
   tokens ÷ `tokens_per_pct` once two calibrations exist.
7. **Model pools (O8):** the governor tracks one agy pool for now. Whether Claude/GPT models inside agy
   draw on a separate quota is unknown; record it from the first quota event or `/usage` and split the
   pool then.

## Consequences
- Data protection rests on: never putting data in prompts or worktrees, the deny rules above, and the
  mapped-folder boundary. Command deny rules are pattern-based and best effort (a command can still
  name a path indirectly); this residual risk is accepted with code-only delegation.
- Status-only success checks would have silently accepted empty work; the empty-response rule is
  covered by `tests/unit/agentops/test_runner.py`.
- The crawler mis-expands agy's Go-style help (siblings repeated under each subcommand); harmless here.

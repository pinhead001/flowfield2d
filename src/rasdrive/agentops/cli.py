"""`agentops` command: statusline, gov, cards, hook.

Config: --config PATH or the AGENTOPS_CONFIG environment variable.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rasdrive.agentops import governor, hooks, ledger, runner, statusline
from rasdrive.agentops.config import AgentOpsConfig, load_config
from rasdrive.agentops.queue import STATES, Queue


def _next(cfg: AgentOpsConfig) -> str:
    s = governor.status(cfg)
    q = Queue(cfg)
    ready, running = q.ready(), q.cards("running")
    lines = [governor.render(s)]
    if s.mode == "wait":
        lines.append("next: Claude exhausted. Make sure the agy queue has work, then stop.")
    elif s.mode == "review-only":
        lines.append("next: review finished branches and merge; no new specs or cards.")
    else:
        lines.append(f"next: {len(ready)} ready card(s), {len(running)} running; "
                     f"{len(q.cards('done'))} done awaiting review, "
                     f"{len(q.cards('escalated'))} escalated.")
    if ready and s.agy_concurrency > 0:
        lines.append(f"dispatch: run.bat cards run (up to {s.agy_concurrency} worker(s))")
    elif not ready and s.mode != "review-only":
        lines.append("queue empty: write the next card (tests first).")
    return "\n".join(lines)


def _plan(cfg: AgentOpsConfig) -> str:
    s = governor.status(cfg)
    ready = Queue(cfg).ready()
    take = ready[: s.agy_concurrency]
    lines = [f"mode {s.mode}; agy concurrency {s.agy_concurrency}"]
    lines += [f"  dispatch {c.id} [{c.repo}] {c.title}" for c in take]
    lines += [f"  hold     {c.id} [{c.repo}] {c.title}" for c in ready[len(take):]]
    return "\n".join(lines) if ready else lines[0] + "\n  (no ready cards)"


def _cards_run(cfg: AgentOpsConfig, workers: int | None, card_id: str | None) -> int:
    q = Queue(cfg)
    if card_id:
        state = q.state_of(card_id)
        if state not in ("pending", "running"):
            print(f"card {card_id} is {state}", file=sys.stderr)
            return 1
        card = next(c for c in q.cards(state) if c.id == card_id)
        res = runner.run_card(cfg, card)
        print(json.dumps({**res.__dict__, "worktree": str(res.worktree)}))
        return 0 if res.state == "done" else 1
    n = workers if workers is not None else governor.status(cfg).agy_concurrency
    if n <= 0:
        print("governor: agy concurrency is 0; not dispatching", file=sys.stderr)
        return 1
    with ThreadPoolExecutor(max_workers=n) as ex:
        results = [r for rs in ex.map(lambda _: runner.run_ready(cfg, 1_000), range(n))
                   for r in rs]
    for r in results:
        print(f"{r.card}: {r.state} after {r.attempts} attempt(s) on {r.branch}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agentops")
    ap.add_argument("--config", type=Path, default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("statusline")
    gov = sub.add_parser("gov")
    gsub = gov.add_subparsers(dest="gcmd", required=True)
    st = gsub.add_parser("status")
    st.add_argument("--json", action="store_true")
    gsub.add_parser("next")
    gsub.add_parser("plan")
    cal = gsub.add_parser("calibrate")
    cal.add_argument("--agy-remaining", type=float, required=True,
                     help="agy remaining %% read from its /usage view")
    cards = sub.add_parser("cards")
    csub = cards.add_subparsers(dest="ccmd", required=True)
    add = csub.add_parser("add")
    add.add_argument("files", type=Path, nargs="+")
    csub.add_parser("list")
    run = csub.add_parser("run")
    run.add_argument("--workers", type=int, default=None)
    run.add_argument("--card", default=None)
    mv = csub.add_parser("move")
    mv.add_argument("card")
    mv.add_argument("state", choices=STATES)
    lg = sub.add_parser("ledger")
    lg.add_argument("--tail", type=int, default=10)
    hk = sub.add_parser("hook")
    hk.add_argument("event", choices=["session-start", "pre-tool-use", "task-completed"])
    a = ap.parse_args(argv)

    if a.cmd == "hook":
        try:
            cfg = load_config(a.config)
        except Exception as e:  # noqa: BLE001 - hooks fail open when unconfigured
            print(f"agentops: hook skipped ({e})", file=sys.stderr)
            return 0
        if a.event == "pre-tool-use":
            hooks.pre_tool_use(cfg, sys.stdin, sys.stdout)
            return 0
        if a.event == "session-start":
            hooks.session_start(cfg, sys.stdin, sys.stdout)
            return 0
        return hooks.task_completed(cfg, sys.stdin, sys.stderr)

    if a.cmd == "statusline":
        try:
            cfg = load_config(a.config)
        except Exception:  # noqa: BLE001
            print("agentops: no config")
            return 0
        statusline.run(cfg, sys.stdin, sys.stdout)
        return 0

    cfg = load_config(a.config)
    if a.cmd == "gov":
        if a.gcmd == "status":
            s = governor.status(cfg)
            print(json.dumps(s.as_dict(), indent=2) if a.json else governor.render(s))
        elif a.gcmd == "next":
            print(_next(cfg))
        elif a.gcmd == "plan":
            print(_plan(cfg))
        elif a.gcmd == "calibrate":
            governor.calibrate(cfg, a.agy_remaining)
            print(governor.render(governor.status(cfg)))
        return 0
    if a.cmd == "cards":
        q = Queue(cfg)
        if a.ccmd == "add":
            for f in a.files:
                c = q.add(f)
                print(f"queued {c.id} [{c.repo}] {c.title}")
        elif a.ccmd == "list":
            for state in STATES:
                for c in q.cards(state):
                    print(f"{state:10} {c.id:24} [{c.repo}] {c.title}")
        elif a.ccmd == "move":
            q.move(a.card, a.state)
        elif a.ccmd == "run":
            return _cards_run(cfg, a.workers, a.card)
        return 0
    if a.cmd == "ledger":
        for r in ledger.read(cfg.ledger_path)[-a.tail:]:
            r.pop("stderr_tail", None)
            r.pop("stdout_tail", None)
            print(json.dumps(r))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

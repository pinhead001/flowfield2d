"""`agentops` command: statusline, gov, cards, hook.

Config: --config PATH or the AGENTOPS_CONFIG environment variable.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flowfield2d.agentops import governor, hooks, ledger, review, runner, statusline
from flowfield2d.agentops.config import AgentOpsConfig, load_config, set_governor_profile
from flowfield2d.agentops.queue import STATES, Card, CardError, Queue


def _next(cfg: AgentOpsConfig) -> str:
    s = governor.status(cfg)
    q = Queue(cfg)
    ready, running = q.ready(), q.cards("running")
    lines = [governor.headline(s)]
    if s.mode == "wait":
        lines.append("next: Claude exhausted. Make sure the agy queue has work, then stop.")
    elif s.mode == "review-only":
        lines.append("next: review finished branches and merge; no new specs or cards.")
    else:
        lines.append(
            f"next: {len(ready)} ready card(s), {len(running)} running; "
            f"{len(q.cards('done'))} done awaiting review, "
            f"{len(q.cards('escalated'))} escalated."
        )
    done = q.cards("done")
    if done:
        first = done[0].id
        lines.append(
            f"review: run.bat cards show {first} / cards diff {first}, "
            f"then cards accept {first} or cards reject {first} --reason ..."
        )
    if ready and s.agy_concurrency > 0:
        lines.append(f"dispatch: run.bat cards run (up to {s.agy_concurrency} worker(s))")
    elif not ready and not done and s.mode != "review-only":
        lines.append("queue empty: write the next card (tests first).")
    return "\n".join(lines)


def _plan(cfg: AgentOpsConfig) -> str:
    s = governor.status(cfg)
    ready = Queue(cfg).ready()
    take = ready[: s.agy_concurrency]
    lines = [f"mode {s.mode}; agy concurrency {s.agy_concurrency}"]
    lines += [f"  dispatch {c.id} [{c.repo}] {c.title}" for c in take]
    lines += [f"  hold     {c.id} [{c.repo}] {c.title}" for c in ready[len(take) :]]
    return "\n".join(lines) if ready else lines[0] + "\n  (no ready cards)"


class CliError(Exception):
    """A user-facing failure: printed as one line on stderr, exit 1."""


def _load(path: Path | None) -> AgentOpsConfig:
    try:
        return load_config(path)
    except FileNotFoundError as e:
        if path is None:
            raise CliError(str(e)) from e
        raise CliError(f"config not found: {Path(path).resolve()}") from e
    except KeyError as e:
        key = e.args[0] if e.args else "?"
        src = Path(path).resolve() if path is not None else "config"
        text = key if isinstance(key, str) and " " in key else f"missing key {key!r}"
        raise CliError(f"{src}: {text}") from e
    except (ValueError, TypeError) as e:  # tomllib decode errors are ValueErrors
        src = Path(path).resolve() if path is not None else "config"
        raise CliError(f"{src}: {e}") from e


def _check(cfg: AgentOpsConfig) -> tuple[str, bool]:
    """Validate the consumer setup: repos are checkouts, state dir writable, delegate on PATH."""
    import shutil
    import subprocess

    rows: list[tuple[bool, str]] = []
    for name, repo in cfg.repos.items():
        is_repo = (
            repo.is_dir()
            and subprocess.run(
                ["git", "rev-parse", "--git-dir"], cwd=repo, capture_output=True, text=True
            ).returncode
            == 0
        )
        note = "" if is_repo else " is not a git checkout"
        rows.append((is_repo, f"repo {name}: {repo}{note}"))
    try:
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        probe = cfg.state_dir / ".write-probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        rows.append((True, f"state_dir {cfg.state_dir}: writable"))
    except OSError as e:
        rows.append((False, f"state_dir {cfg.state_dir}: not writable ({e})"))
    exe = cfg.agy.command[0]
    found = shutil.which(exe) or (Path(exe).is_file() and exe)
    rows.append((bool(found), f"agy {exe}: {found or 'not found on PATH'}"))
    prof = cfg.governor.profile or "(flat)"
    rows.append((True, f"governor profile {prof}: normal>={cfg.governor.normal_min_remaining:g}%"))
    rows.append((True, f"models: {', '.join(cfg.agy.models) or '(delegate default)'}"))
    text = "\n".join(("ok   " if ok else "FAIL ") + msg for ok, msg in rows)
    return text, all(ok for ok, _ in rows)


def _card_row(q: Queue, state: str, c: Card) -> dict[str, Any]:
    return {
        "id": c.id,
        "state": state,
        "repo": c.repo,
        "title": c.title,
        "base": c.base,
        "branch": f"card/{c.id}",
        "depends_on": c.depends_on,
        "blocked_by": q.blocked_by(c) if state == "pending" else [],
        "model": c.model,
    }


def _cards_list(q: Queue, state: str | None, as_json: bool) -> str:
    rows = [_card_row(q, s, c) for s in STATES if state in (None, s) for c in q.cards(s)]
    if as_json:
        return json.dumps(rows, indent=2)
    lines = []
    for r in rows:
        st = r["state"] + (f" (waits {','.join(r['blocked_by'])})" if r["blocked_by"] else "")
        lines.append(f"{st:10} {r['id']:24} [{r['repo']}] {r['title']}")
    return "\n".join(lines)


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
        results = [r for rs in ex.map(lambda _: runner.run_ready(cfg, 1_000), range(n)) for r in rs]
    for r in results:
        print(f"{r.card}: {r.state} after {r.attempts} attempt(s) on {r.branch}")
    return 0


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="agentops")
    ap.add_argument("--config", type=Path, default=None, help="agents.toml (or $AGENTOPS_CONFIG)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("statusline", help="Claude Code status line: record the meter, print one line")
    gov = sub.add_parser("gov", help="governor: mode, advice, plan, profiles, calibration")
    gsub = gov.add_subparsers(dest="gcmd", required=True)
    st = gsub.add_parser("status", help="mode, meter, delegate capacity and cooldowns")
    st.add_argument("--json", action="store_true")
    gsub.add_parser("next", help="one-line mode plus what the lead should do now")
    gsub.add_parser("plan", help="which ready cards would dispatch at current concurrency")
    gsub.add_parser("check", help="validate the setup: repos, state dir, delegate on PATH")
    pr = gsub.add_parser("profile", help="list governor profiles, or select one")
    pr.add_argument("name", nargs="?")
    cal = gsub.add_parser("calibrate", help="record agy remaining %% from its /usage view")
    cal.add_argument(
        "--agy-remaining",
        type=float,
        required=True,
        help="agy remaining %% read from its /usage view",
    )
    cards = sub.add_parser("cards", help="task-card queue")
    csub = cards.add_subparsers(dest="ccmd", required=True)
    add = csub.add_parser("add", help="validate card TOML files and queue them as pending")
    add.add_argument("files", type=Path, nargs="+")
    ls = csub.add_parser("list", help="cards by state; blocked pending cards show (waits ..)")
    ls.add_argument("--state", choices=STATES, default=None)
    ls.add_argument("--json", action="store_true")
    sh = csub.add_parser("show", help="one card: state, branch, worktree, last run, calls, reviews")
    sh.add_argument("card")
    sh.add_argument("--json", action="store_true")
    df = csub.add_parser("diff", help="git diff <base>...card/<id> in the card's repo")
    df.add_argument("card")
    df.add_argument("--stat", action="store_true")
    nw = csub.add_parser("new", help="write a card skeleton <out>/<id>.toml with every field")
    nw.add_argument("id")
    nw.add_argument("--repo", required=True)
    nw.add_argument("--title", required=True)
    nw.add_argument("--base", default="main")
    nw.add_argument("--out", type=Path, default=Path("."), help="directory (default: cwd)")
    acc = csub.add_parser("accept", help="lead accepted a done card: archive it")
    acc.add_argument("card")
    rej = csub.add_parser("reject", help="lead rejected a done card: escalate it with a reason")
    rej.add_argument("card")
    rej.add_argument("--reason", required=True)
    run = csub.add_parser("run", help="dispatch ready cards to the delegate (or one --card)")
    run.add_argument("--workers", type=int, default=None)
    run.add_argument("--card", default=None)
    rs = csub.add_parser("reset", help="discard worktree and branch, requeue as pending")
    rs.add_argument("card")
    mv = csub.add_parser("move", help="force a card into a state (no checks)")
    mv.add_argument("card")
    mv.add_argument("state", choices=STATES)
    lg = sub.add_parser("ledger", help="recent delegate calls and events")
    lg.add_argument("--tail", type=int, default=10)
    lg.add_argument("--card", default=None, help="only records for this card id")
    lg.add_argument("--kind", default=None, help="only this record kind (agy, quota, review)")
    hk = sub.add_parser("hook", help="Claude Code hook handlers (read stdin JSON)")
    hk.add_argument("event", choices=["session-start", "pre-tool-use", "task-completed"])
    return ap


def main(argv: list[str] | None = None) -> int:
    a = _parser().parse_args(argv)
    try:
        return _dispatch(a)
    except (CliError, CardError) as e:
        print(f"agentops: {e}", file=sys.stderr)
        return 1
    except KeyError as e:  # unknown card id from the runner
        print(f"agentops: unknown card {e.args[0]!r}", file=sys.stderr)
        return 1


def _dispatch(a: argparse.Namespace) -> int:
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

    cfg = _load(a.config)
    if a.cmd == "gov":
        if a.gcmd == "status":
            s = governor.status(cfg)
            print(json.dumps(s.as_dict(), indent=2) if a.json else governor.render(s))
        elif a.gcmd == "next":
            print(_next(cfg))
        elif a.gcmd == "plan":
            print(_plan(cfg))
        elif a.gcmd == "check":
            text, ok = _check(cfg)
            print(text)
            return 0 if ok else 1
        elif a.gcmd == "profile":
            if a.name:
                set_governor_profile(cfg.source, a.name)
                print(f"governor profile: {a.name}")
            else:
                for n in cfg.governor.profiles:
                    print(("*" if n == cfg.governor.profile else "") + n)
        elif a.gcmd == "calibrate":
            governor.calibrate(cfg, a.agy_remaining)
            print(governor.render(governor.status(cfg)))
        return 0
    if a.cmd == "cards":
        q = Queue(cfg)
        if a.ccmd == "add":
            for f in a.files:
                try:
                    c = q.add(f)
                except (CardError, OSError, ValueError) as e:
                    raise CliError(f"{f}: {e}") from e
                print(f"queued {c.id} [{c.repo}] {c.title}")
        elif a.ccmd == "list":
            print(_cards_list(q, a.state, a.json))
        elif a.ccmd == "show":
            d = review.report(cfg, a.card)
            print(json.dumps(d, indent=2) if a.json else review.render(d))
        elif a.ccmd == "diff":
            code, out, err = review.diff(cfg, a.card, a.stat)
            sys.stdout.write(out)
            sys.stderr.write(err)
            return code
        elif a.ccmd == "new":
            target = a.out / f"{a.id}.toml"
            if target.exists():
                raise CliError(f"{target} exists; not overwriting")
            text = review.skeleton(cfg, a.id, a.repo, a.title, a.base)
            a.out.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            print(f"wrote {target}; fill the prompt, then: cards add {target}")
        elif a.ccmd in ("accept", "reject"):
            try:
                target = q.review(a.card, a.ccmd, getattr(a, "reason", ""))
            except CardError as e:
                print(f"agentops: {e}", file=sys.stderr)
                return 1
            rec = {
                "ts": datetime.now(UTC).isoformat(),
                "kind": "review",
                "card": a.card,
                "decision": a.ccmd,
                "reason": getattr(a, "reason", ""),
                "state": target,
            }
            ledger.append(cfg.ledger_path, rec)
            print(f"{a.ccmd}ed {a.card}: now {target}")
        elif a.ccmd == "reset":
            runner.reset_card(cfg, a.card)
            print(f"reset {a.card}: worktree and branch removed, pending")
        elif a.ccmd == "move":
            before = q.state_of(a.card)
            q.move(a.card, a.state)
            print(f"moved {a.card}: {before} -> {a.state}")
        elif a.ccmd == "run":
            return _cards_run(cfg, a.workers, a.card)
        return 0
    if a.cmd == "ledger":
        recs = ledger.read(cfg.ledger_path)
        if a.card:
            recs = [r for r in recs if r.get("card") == a.card]
        if a.kind:
            recs = [r for r in recs if r.get("kind") == a.kind]
        for r in recs[-a.tail :]:
            r.pop("stderr_tail", None)
            r.pop("stdout_tail", None)
            print(json.dumps(r))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

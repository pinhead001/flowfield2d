"""The lead's review loop: one report per card, its diff against base, and card skeletons.

Nothing here changes queue state; `cards accept` / `cards reject` do that through `Queue.review`.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from flowfield2d.agentops import ledger
from flowfield2d.agentops.config import AgentOpsConfig
from flowfield2d.agentops.queue import Card, CardError, Queue

CALL_KEYS = ("ts", "attempt", "model", "ok", "status", "total_tokens", "wall_seconds", "timeout")
REVIEW_KEYS = ("ts", "decision", "reason", "state")


def _locate(cfg: AgentOpsConfig, card_id: str) -> tuple[Queue, Card, str]:
    q = Queue(cfg)
    state = q.state_of(card_id)
    if state is None:
        raise CardError(f"card {card_id} not in queue")
    return q, Card.load(q.root / state / f"{card_id}.toml"), state


def report(cfg: AgentOpsConfig, card_id: str) -> dict[str, Any]:
    """Everything the lead needs to review one card, from the queue, results and ledger."""
    q, card, state = _locate(cfg, card_id)
    wt = cfg.worktree_root / f"{cfg.worktree_prefix}{card.repo}-{card.id}"
    result: dict[str, Any] | None = None
    rp = cfg.results_dir / f"{card.id}.json"
    if rp.exists():
        try:
            result = json.loads(rp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            result = None
    recs = [r for r in ledger.read(cfg.ledger_path) if r.get("card") == card.id]
    calls = [{k: r.get(k) for k in CALL_KEYS} for r in recs if r.get("kind") == "agy"]
    reviews = [{k: r.get(k) for k in REVIEW_KEYS} for r in recs if r.get("kind") == "review"]
    return {
        "id": card.id,
        "state": state,
        "repo": card.repo,
        "title": card.title,
        "base": card.base,
        "branch": f"card/{card.id}",
        "model": card.model,
        "depends_on": card.depends_on,
        "blocked_by": q.blocked_by(card) if state == "pending" else [],
        "worktree": str(wt),
        "worktree_exists": (wt / ".git").exists(),
        "acceptance": card.acceptance,
        "result": result,
        "calls": calls,
        "reviews": reviews,
        "tokens": sum(int(c.get("total_tokens") or 0) for c in calls),
    }


def render(d: dict[str, Any]) -> str:
    lines = [
        f"{d['id']}  {d['state']}  [{d['repo']}]  {d['title']}",
        f"branch {d['branch']} from {d['base']}; worktree {d['worktree']}"
        + ("" if d["worktree_exists"] else " (absent)"),
    ]
    if d["depends_on"]:
        waits = f" (waits {','.join(d['blocked_by'])})" if d["blocked_by"] else ""
        lines.append(f"depends_on {','.join(d['depends_on'])}{waits}")
    lines.append(f"acceptance: {d['acceptance']}")
    r = d["result"]
    if r:
        lines.append(
            f"last run: {r.get('state')} after {r.get('attempts')} attempt(s), "
            f"finished {str(r.get('finished', ''))[:16]}"
        )
        if r.get("detail"):
            tail = str(r["detail"]).rstrip().splitlines()[-8:]
            lines += ["  " + t for t in tail]
    lines.append(f"delegate calls: {len(d['calls'])}, {d['tokens']} tokens")
    for c in d["calls"]:
        flag = "ok" if c["ok"] else ("timeout" if c.get("timeout") else f"FAIL {c.get('status')}")
        lines.append(
            f"  attempt {c['attempt']}  {c['model'] or 'default'}  {flag}  "
            f"{c.get('total_tokens') or 0} tok  {c.get('wall_seconds') or 0}s  {str(c['ts'])[:16]}"
        )
    for v in d["reviews"]:
        reason = f": {v['reason']}" if v.get("reason") else ""
        lines.append(f"review {str(v['ts'])[:16]}: {v['decision']} -> {v['state']}{reason}")
    return "\n".join(lines)


def diff(cfg: AgentOpsConfig, card_id: str, stat: bool = False) -> tuple[int, str, str]:
    """`git diff <base>...card/<id>` in the card's repo: (exit code, stdout, stderr)."""
    _, card, _ = _locate(cfg, card_id)
    repo = cfg.repos[card.repo]
    branch = f"card/{card.id}"
    probe = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", branch], cwd=repo, capture_output=True
    )
    if probe.returncode != 0:
        raise CardError(
            f"branch {branch} does not exist in repo {card.repo!r} "
            "(card never ran, or the branch was merged and deleted)"
        )
    args = ["git", "diff", *(["--stat"] if stat else []), f"{card.base}...{branch}"]
    p = subprocess.run(args, cwd=repo, capture_output=True, text=True, encoding="utf-8")
    return p.returncode, p.stdout, p.stderr


def skeleton(cfg: AgentOpsConfig, card_id: str, repo: str, title: str, base: str) -> str:
    """A card TOML with every required field filled and the optional ones documented."""
    if repo not in cfg.repos:
        raise CardError(f"unknown repo {repo!r}; known: {sorted(cfg.repos)}")
    Card.from_dict({"id": card_id, "repo": repo, "title": title, "prompt": "x", "acceptance": "x"})
    acceptance = cfg.hooks.task_acceptance or "<command that exits 0 when the card is done>"
    prompt = (
        "Read AGENTS.md first and follow it.\n\n"
        "Files you may read: <list>.\nFiles you may edit: <list>.\n\n"
        "Task: <what to build, in terms of the tests that must pass>.\n\n"
        "When done, reply with a one-line summary."
    )
    return (
        f"id = {json.dumps(card_id)}\n"
        f"repo = {json.dumps(repo)}\n"
        f"title = {json.dumps(title)}\n"
        f"base = {json.dumps(base)}\n"
        f"acceptance = {json.dumps(acceptance)}\n"
        "# depends_on = []                      # card ids that must be done or archived first\n"
        '# model = ""                           # overrides the [agy] models preference\n'
        '# print_timeout = ""                   # overrides [agy] print_timeout\n'
        "# max_retries = 1                      # overrides [agy] max_retries\n"
        f"prompt = '''\n{prompt}\n'''\n"
    )

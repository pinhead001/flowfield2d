"""Delegate runner: one card, one git worktree, one branch. Never merges.

Per attempt: call the delegate CLI headless with a JSON envelope, log the
envelope to the ledger, run the card's acceptance command in the worktree.
On pass, commit to `card/<id>` and mark the card done. On fail, retry with
the acceptance output appended to the prompt, then escalate. A quota-style
failure puts the card back to pending and saves the raw output, so the
cooldown parser can be fitted to the real message.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flowfield2d.agentops import cooldown, ledger
from flowfield2d.agentops.config import AgentOpsConfig
from flowfield2d.agentops.queue import Card, Queue

QUOTA_RE = re.compile(r"quota|rate.?limit|resource.?exhausted|\b429\b", re.IGNORECASE)
TAIL = 4000


@dataclass
class RunResult:
    card: str
    state: str  # done | escalated | quota
    attempts: int
    worktree: Path
    branch: str
    detail: str = ""


def _child_env() -> dict[str, str]:
    """Environment for delegate and acceptance processes: drop the caller's venv."""
    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)
    return env


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def ensure_worktree(cfg: AgentOpsConfig, card: Card) -> tuple[Path, str]:
    repo = cfg.repos[card.repo]
    wt = cfg.worktree_root / f"{cfg.worktree_prefix}{card.repo}-{card.id}"
    branch = f"card/{card.id}"
    if (wt / ".git").exists():
        return wt, branch
    _git(repo, "worktree", "prune")
    exists = _git(repo, "rev-parse", "--verify", "--quiet", branch).returncode == 0
    args = ["worktree", "add", str(wt), branch] if exists else \
        ["worktree", "add", "-b", branch, str(wt), card.base]
    r = _git(repo, *args)
    if r.returncode != 0:
        raise RuntimeError(f"git worktree add failed: {r.stderr.strip()}")
    return wt, branch


def agy_argv(cfg: AgentOpsConfig, card: Card, prompt: str, model: str | None = None) -> list[str]:
    argv = [*cfg.agy.command, "-p", prompt, "--output-format", "json"]
    model = model or card.model or cfg.agy.model
    if model:
        argv += ["--model", model]
    argv += ["--print-timeout", card.print_timeout or cfg.agy.print_timeout, *cfg.agy.extra_args]
    return argv


def _envelope(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    for candidate in (text, text[text.find("{"):] if "{" in text else ""):
        try:
            d = json.loads(candidate)
            if isinstance(d, dict):
                return d
        except json.JSONDecodeError:
            continue
    return {}


def _shell(cmd: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=_child_env())


def run_card(cfg: AgentOpsConfig, card: Card) -> RunResult:
    q = Queue(cfg)
    if q.state_of(card.id) != "running":
        q.move(card.id, "running")
    wt, branch = ensure_worktree(cfg, card)
    max_retries = cfg.agy.max_retries if card.max_retries is None else card.max_retries
    prompt = card.prompt
    result: RunResult | None = None
    attempt = 0
    while attempt <= max_retries:
        model = cooldown.choose_model(cfg, card.model)
        if model is None and (card.model or cfg.agy.models):
            q.move(card.id, "pending")
            result = RunResult(card.id, "quota", attempt, wt, branch,
                               f"all delegate pools cooling: {cooldown.active(cfg)}")
            break
        attempt += 1
        argv = agy_argv(cfg, card, prompt, model)
        t0 = time.monotonic()
        p = subprocess.run(argv, cwd=wt, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=_child_env())
        env = _envelope(p.stdout)
        usage = env.get("usage") if isinstance(env.get("usage"), dict) else {}
        response = str(env.get("response") or "")
        # A headless auto-deny reports SUCCESS with exit 0 and an empty response.
        ok_call = (p.returncode == 0 and str(env.get("status", "")).upper() != "ERROR"
                   and bool(response.strip()))
        rec: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(), "kind": "agy", "card": card.id,
            "repo": card.repo, "attempt": attempt, "model": model or "",
            "exit": p.returncode, "status": env.get("status"), "ok": ok_call,
            "total_tokens": usage.get("total_tokens") if usage else None,
            "duration_seconds": env.get("duration_seconds"),
            "wall_seconds": round(time.monotonic() - t0, 2),
            "response_tail": response[-1000:],
            "timeout": "print timeout" in p.stderr.lower(),
        }
        if not ok_call:
            rec["stderr_tail"] = p.stderr[-TAIL:]
            rec["stdout_tail"] = p.stdout[-TAIL:]
        ledger.append(cfg.ledger_path, rec)

        if not ok_call and QUOTA_RE.search(p.stderr + p.stdout):
            until = cooldown.record_quota(cfg, model or "", p.stderr + p.stdout)
            rec_q = {"ts": datetime.now(UTC).isoformat(), "kind": "quota", "card": card.id,
                     "model": model, "pool": cooldown.pool_of(cfg, model or ""),
                     "until": until.isoformat()}
            ledger.append(cfg.ledger_path, rec_q)
            cfg.quota_events_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            ledger.write_json_atomic(cfg.quota_events_dir / f"{stamp}-{card.id}.json",
                                     {"argv_tail": argv[3:], "exit": p.returncode,
                                      "stdout": p.stdout, "stderr": p.stderr})
            if cooldown.choose_model(cfg, card.model) is not None:
                attempt -= 1  # another pool is free: a quota hit is not a failed attempt
                continue
            q.move(card.id, "pending")
            result = RunResult(card.id, "quota", attempt, wt, branch, p.stderr[-500:])
            break

        if ok_call:
            for cmd in cfg.agy.pre_acceptance:  # mechanical fixes (e.g. lint autofix); best effort
                _shell(cmd, wt)
        acc = _shell(card.acceptance, wt)
        if ok_call and acc.returncode == 0:
            _git(wt, "add", "-A")
            model = rec["model"] or "default"
            msg = f"card {card.id}: {card.title}\n\nImplemented by agy ({model})."
            c = _git(wt, "commit", "-q", "--allow-empty", "-m", msg)
            if c.returncode != 0:
                raise RuntimeError(f"commit failed: {c.stderr.strip()}")
            q.move(card.id, "done")
            result = RunResult(card.id, "done", attempt, wt, branch)
            break
        out = (acc.stdout + acc.stderr)[-TAIL:]
        if not ok_call:
            out = f"delegate stderr: {p.stderr[-1500:]}\n{out}"[-TAIL:]
        why = f"delegate call failed (exit {p.returncode}, status {env.get('status')})" \
            if not ok_call else "acceptance command failed"
        prompt = (f"{card.prompt}\n\n---\nPrevious attempt {attempt}: {why}.\n"
                  f"Acceptance command: {card.acceptance}\nAcceptance output (tail):\n{out}\n"
                  "Fix the code so the acceptance command passes. Do not edit the tests.")
        result = RunResult(card.id, "escalated", attempt, wt, branch, out[-1000:])

    assert result is not None
    if result.state == "escalated":
        q.move(card.id, "escalated")
    d = asdict(result)
    d["worktree"] = str(result.worktree)
    d["finished"] = datetime.now(UTC).isoformat()
    ledger.write_json_atomic(cfg.results_dir / f"{card.id}.json", d)
    return result


def reset_card(cfg: AgentOpsConfig, card_id: str) -> None:
    """Discard a card's worktree and branch and put it back to pending (fresh start from base)."""
    q = Queue(cfg)
    state = q.state_of(card_id)
    if state is None:
        raise KeyError(card_id)
    card = Card.load(q.root / state / f"{card_id}.toml")
    repo = cfg.repos[card.repo]
    wt = cfg.worktree_root / f"{cfg.worktree_prefix}{card.repo}-{card.id}"
    if wt.exists():
        r = _git(repo, "worktree", "remove", "--force", str(wt))
        if r.returncode != 0:
            raise RuntimeError(f"git worktree remove failed: {r.stderr.strip()}")
    _git(repo, "worktree", "prune")
    _git(repo, "branch", "-D", f"card/{card.id}")
    q.move(card_id, "pending")


def run_ready(cfg: AgentOpsConfig, limit: int) -> list[RunResult]:
    """Run up to `limit` ready cards sequentially (concurrency is the caller's job)."""
    q = Queue(cfg)
    out = []
    for _ in range(limit):
        card = q.claim_next()
        if card is None:
            break
        res = run_card(cfg, card)
        out.append(res)
        if res.state == "quota":
            break
    return out

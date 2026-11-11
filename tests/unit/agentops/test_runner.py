import json
from pathlib import Path

import pytest

from flowfield2d.agentops import ledger, runner
from flowfield2d.agentops.config import AgentOpsConfig
from flowfield2d.agentops.queue import Card, CardError, Queue

from .conftest import git as _git
from .conftest import make_card as _card


def test_card_validation(cfg: AgentOpsConfig) -> None:
    with pytest.raises(CardError, match="repo"):
        _card(cfg, repo="nope")
    with pytest.raises(CardError, match="acceptance"):
        Card.from_dict({"id": "x", "repo": "lib", "title": "t", "prompt": "p"})


def test_claim_respects_dependencies(repo_cfg: AgentOpsConfig) -> None:
    q = Queue(repo_cfg)
    _card(repo_cfg)
    _card(repo_cfg, id="c2", depends_on=["c1"])
    claimed = q.claim_next()
    assert claimed is not None and claimed.id == "c1"
    q.move("c1", "done")
    nxt = q.claim_next()
    assert nxt is not None and nxt.id == "c2"


def test_run_card_success_commits_on_branch_never_merges(repo_cfg: AgentOpsConfig) -> None:
    card = _card(repo_cfg)
    q = Queue(repo_cfg)
    q.claim_next()
    res = runner.run_card(repo_cfg, card)
    repo = repo_cfg.repos["lib"]
    assert res.state == "done", res
    assert _git(repo, "show", "card/c1:hello.txt") == "hi"
    assert not (repo / "hello.txt").exists()
    assert _git(repo, "rev-list", "--count", "main") == "1"
    assert res.worktree == repo_cfg.worktree_root / "wt-lib-c1"
    recs = ledger.read(repo_cfg.ledger_path)
    assert recs[-1]["card"] == "c1" and recs[-1]["total_tokens"] == 42 and recs[-1]["ok"]
    assert q.state_of("c1") == "done"
    assert json.loads((repo_cfg.results_dir / "c1.json").read_text())["state"] == "done"


def test_run_card_argv(repo_cfg: AgentOpsConfig, tmp_path: Path) -> None:
    card = _card(repo_cfg)
    runner.run_card(repo_cfg, card)
    call = json.loads((tmp_path / "agy_calls.jsonl").read_text().splitlines()[0])
    argv = call["argv"]
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--model") + 1] == "m1"
    assert argv[argv.index("--print-timeout") + 1] == "1m"


def test_acceptance_failure_retries_then_escalates(
    repo_cfg: AgentOpsConfig, tmp_path: Path
) -> None:
    card = _card(repo_cfg, prompt="WRITE hello.txt=nope")
    res = runner.run_card(repo_cfg, card)
    assert res.state == "escalated" and res.attempts == 2
    calls = (tmp_path / "agy_calls.jsonl").read_text().splitlines()
    assert len(calls) == 2
    assert "acceptance" in json.loads(calls[1])["prompt"].lower()
    assert Queue(repo_cfg).state_of("c1") == "escalated"


def test_success_envelope_with_empty_response_is_a_failed_call(
    repo_cfg: AgentOpsConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_AGY_MODE", "denied")
    res = runner.run_card(repo_cfg, _card(repo_cfg))
    assert res.state == "escalated"
    rec = ledger.read(repo_cfg.ledger_path)[-1]
    assert rec["ok"] is False and "auto-denied" in rec["stderr_tail"]


def test_pre_acceptance_runs_before_acceptance(repo_cfg: AgentOpsConfig) -> None:
    # The delegate writes the wrong text; a mechanical pre-acceptance step repairs it.
    repo_cfg.agy.pre_acceptance = [
        "python -c \"import pathlib; pathlib.Path('hello.txt').write_text('hi')\"",
        'python -c "import sys; sys.exit(5)"',  # failures here are ignored
    ]
    res = runner.run_card(repo_cfg, _card(repo_cfg, prompt="WRITE hello.txt=nope"))
    assert res.state == "done" and res.attempts == 1


def _pre_commit_hook(repo: Path, body: str) -> None:
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8", newline="\n")
    hook.chmod(0o755)


def test_commit_restaged_after_a_formatting_hook(repo_cfg: AgentOpsConfig) -> None:
    # Like ruff-format: the hook rewrites a file and fails; the restaged second commit passes.
    _pre_commit_hook(
        repo_cfg.repos["lib"],
        "if [ -f formatted.txt ] && git diff --quiet; then exit 0; fi\n"
        "echo formatted > formatted.txt\nexit 1",
    )
    res = runner.run_card(repo_cfg, _card(repo_cfg))
    assert res.state == "done", res
    assert _git(repo_cfg.repos["lib"], "show", "card/c1:formatted.txt") == "formatted"
    assert Queue(repo_cfg).state_of("c1") == "done"


def test_refused_commit_escalates_instead_of_raising(repo_cfg: AgentOpsConfig) -> None:
    _pre_commit_hook(repo_cfg.repos["lib"], "echo 'refused by hook' >&2\nexit 1")
    res = runner.run_card(repo_cfg, _card(repo_cfg))
    assert res.state == "escalated" and res.attempts == 1
    assert "refused by hook" in res.detail
    assert Queue(repo_cfg).state_of("c1") == "escalated"
    saved = json.loads((repo_cfg.results_dir / "c1.json").read_text())
    assert saved["state"] == "escalated" and "commit refused" in saved["detail"]


def test_ledger_keeps_response_tail(repo_cfg: AgentOpsConfig) -> None:
    runner.run_card(repo_cfg, _card(repo_cfg))
    assert ledger.read(repo_cfg.ledger_path)[-1]["response_tail"] == "done"


def test_quota_event_requeues_and_saves_raw(
    repo_cfg: AgentOpsConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_AGY_MODE", "quota")
    card = _card(repo_cfg)
    res = runner.run_card(repo_cfg, card)
    assert res.state == "quota"
    assert Queue(repo_cfg).state_of("c1") == "pending"
    events = list(repo_cfg.quota_events_dir.glob("*.json"))
    assert events and "RESOURCE_EXHAUSTED" in events[0].read_text()
    recs = ledger.read(repo_cfg.ledger_path)
    assert [r for r in recs if r["kind"] == "agy"][-1]["ok"] is False
    assert recs[-1]["kind"] == "quota" and recs[-1]["pool"] == "b"


def test_print_timeout_is_flagged(
    repo_cfg: AgentOpsConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_AGY_MODE", "timeout")
    runner.run_card(repo_cfg, _card(repo_cfg))
    rec = [r for r in ledger.read(repo_cfg.ledger_path) if r["kind"] == "agy"][-1]
    assert rec["ok"] is False and rec["timeout"] is True


def test_reset_card_removes_worktree_branch_and_requeues(repo_cfg: AgentOpsConfig) -> None:
    card = _card(repo_cfg, prompt="WRITE hello.txt=nope")
    res = runner.run_card(repo_cfg, card)
    assert res.state == "escalated" and res.worktree.exists()
    runner.reset_card(repo_cfg, "c1")
    assert not res.worktree.exists()
    assert _git(repo_cfg.repos["lib"], "branch", "--list", "card/c1") == ""
    assert Queue(repo_cfg).state_of("c1") == "pending"

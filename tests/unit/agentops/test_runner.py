import json
import subprocess
import sys
from pathlib import Path

import pytest

from rasdrive.agentops import ledger, runner
from rasdrive.agentops.config import AgentOpsConfig
from rasdrive.agentops.queue import Card, CardError, Queue

FAKE = Path(__file__).resolve().parents[2] / "fixtures" / "fake_agy.py"
ACCEPT = ('python -c "import pathlib,sys; '
          "sys.exit(0 if pathlib.Path('hello.txt').read_text()=='hi' else 1)\"")


def _git(cwd: Path, *a: str) -> str:
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def repo_cfg(cfg: AgentOpsConfig, monkeypatch: pytest.MonkeyPatch,
             tmp_path: Path) -> AgentOpsConfig:
    repo = cfg.repos["lib"]
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    (repo / "README").write_text("x")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    cfg.agy.command = [sys.executable, str(FAKE)]
    monkeypatch.setenv("FAKE_AGY_LOG", str(tmp_path / "agy_calls.jsonl"))
    monkeypatch.delenv("FAKE_AGY_MODE", raising=False)
    return cfg


def _card(cfg: AgentOpsConfig, prompt: str = "WRITE hello.txt=hi", **kw: object) -> Card:
    fields = {"id": "c1", "repo": "lib", "title": "hello", "prompt": prompt,
              "acceptance": ACCEPT, **kw}
    body = "\n".join(f"{k} = {json.dumps(v)}" for k, v in fields.items())
    p = cfg.state_dir / "incoming.toml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return Queue(cfg).add(p)


def test_card_validation(cfg: AgentOpsConfig) -> None:
    with pytest.raises(CardError, match="repo"):
        _card(cfg, repo="nope")
    with pytest.raises(CardError, match="acceptance"):
        Card.from_dict({"id": "x", "repo": "lib", "title": "t", "prompt": "p"})


def test_claim_respects_dependencies(repo_cfg: AgentOpsConfig) -> None:
    q = Queue(repo_cfg)
    _card(repo_cfg, id="c2", depends_on=["c1"])
    assert q.claim_next() is None
    _card(repo_cfg)
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


def test_acceptance_failure_retries_then_escalates(repo_cfg: AgentOpsConfig,
                                                  tmp_path: Path) -> None:
    card = _card(repo_cfg, prompt="WRITE hello.txt=nope")
    res = runner.run_card(repo_cfg, card)
    assert res.state == "escalated" and res.attempts == 2
    calls = (tmp_path / "agy_calls.jsonl").read_text().splitlines()
    assert len(calls) == 2
    assert "acceptance" in json.loads(calls[1])["prompt"].lower()
    assert Queue(repo_cfg).state_of("c1") == "escalated"


def test_success_envelope_with_empty_response_is_a_failed_call(
        repo_cfg: AgentOpsConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_AGY_MODE", "denied")
    res = runner.run_card(repo_cfg, _card(repo_cfg))
    assert res.state == "escalated"
    rec = ledger.read(repo_cfg.ledger_path)[-1]
    assert rec["ok"] is False and "auto-denied" in rec["stderr_tail"]


def test_ledger_keeps_response_tail(repo_cfg: AgentOpsConfig) -> None:
    runner.run_card(repo_cfg, _card(repo_cfg))
    assert ledger.read(repo_cfg.ledger_path)[-1]["response_tail"] == "done"


def test_quota_event_requeues_and_saves_raw(repo_cfg: AgentOpsConfig,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_AGY_MODE", "quota")
    card = _card(repo_cfg)
    res = runner.run_card(repo_cfg, card)
    assert res.state == "quota"
    assert Queue(repo_cfg).state_of("c1") == "pending"
    events = list(repo_cfg.quota_events_dir.glob("*.json"))
    assert events and "RESOURCE_EXHAUSTED" in events[0].read_text()
    assert ledger.read(repo_cfg.ledger_path)[-1]["ok"] is False

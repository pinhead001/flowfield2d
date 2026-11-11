"""Lead review loop: `cards show`, `cards diff`, `cards new`, `ledger --card`."""

import json
from pathlib import Path

import pytest

from flowfield2d.agentops import runner
from flowfield2d.agentops.cli import main
from flowfield2d.agentops.config import AgentOpsConfig
from flowfield2d.agentops.queue import Card, Queue

from .conftest import make_card


def _main(cfg: AgentOpsConfig, *args: str) -> int:
    return main(["--config", str(cfg.source), *args])


def _ran(cfg: AgentOpsConfig, **kw: object) -> Card:
    card = make_card(cfg, **kw)
    runner.run_card(cfg, card)
    return card


# --- show -----------------------------------------------------------------------------------


def test_show_prints_card_result_and_calls(
    repo_cfg: AgentOpsConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    _ran(repo_cfg)
    assert _main(repo_cfg, "cards", "show", "c1") == 0
    out = capsys.readouterr().out
    assert "c1" in out and "done" in out and "card/c1" in out
    assert str(repo_cfg.worktree_root / "wt-lib-c1") in out
    assert "attempt 1" in out and "m1" in out and "42" in out  # the one ledger call


def test_show_includes_review_decision(
    repo_cfg: AgentOpsConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    _ran(repo_cfg)
    _main(repo_cfg, "cards", "reject", "c1", "--reason", "needs docs")
    capsys.readouterr()
    assert _main(repo_cfg, "cards", "show", "c1") == 0
    out = capsys.readouterr().out
    assert "reject" in out and "needs docs" in out and "escalated" in out


def test_show_json(repo_cfg: AgentOpsConfig, capsys: pytest.CaptureFixture[str]) -> None:
    _ran(repo_cfg)
    assert _main(repo_cfg, "cards", "show", "c1", "--json") == 0
    d = json.loads(capsys.readouterr().out)
    assert d["state"] == "done" and d["result"]["attempts"] == 1
    assert d["calls"][0]["total_tokens"] == 42 and d["reviews"] == []
    assert d["worktree_exists"] is True


def test_show_unknown_card_is_one_line(
    repo_cfg: AgentOpsConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _main(repo_cfg, "cards", "show", "nope") == 1
    assert "nope" in capsys.readouterr().err


# --- diff -----------------------------------------------------------------------------------


def test_diff_shows_the_branch_against_base(
    repo_cfg: AgentOpsConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    _ran(repo_cfg)
    assert _main(repo_cfg, "cards", "diff", "c1") == 0
    out = capsys.readouterr().out
    assert "hello.txt" in out and "+hi" in out


def test_diff_stat(repo_cfg: AgentOpsConfig, capsys: pytest.CaptureFixture[str]) -> None:
    _ran(repo_cfg)
    assert _main(repo_cfg, "cards", "diff", "c1", "--stat") == 0
    out = capsys.readouterr().out
    assert "hello.txt" in out and "+hi" not in out


def test_diff_without_a_branch_is_one_line(
    repo_cfg: AgentOpsConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    make_card(repo_cfg)  # never ran: no branch yet
    assert _main(repo_cfg, "cards", "diff", "c1") == 1
    assert "card/c1" in capsys.readouterr().err


# --- new ------------------------------------------------------------------------------------


def test_new_writes_a_loadable_skeleton(
    repo_cfg: AgentOpsConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_dir = tmp_path / "cards"
    new = ["cards", "new", "k1", "--repo", "lib", "--title", "Do it", "--out", str(out_dir)]
    assert _main(repo_cfg, *new) == 0
    path = out_dir / "k1.toml"
    assert str(path) in capsys.readouterr().out
    card = Card.load(path)
    assert (card.id, card.repo, card.title, card.base) == ("k1", "lib", "Do it", "main")
    assert card.acceptance == repo_cfg.hooks.task_acceptance
    assert "AGENTS.md" in card.prompt
    text = path.read_text(encoding="utf-8")
    assert "depends_on" in text and "model" in text  # documented optional fields


def test_new_refuses_unknown_repo_and_existing_file(
    repo_cfg: AgentOpsConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    new = ["cards", "new", "k1", "--repo", "zzz", "--title", "t", "--out", str(tmp_path)]
    assert _main(repo_cfg, *new) == 1
    assert "zzz" in capsys.readouterr().err
    (tmp_path / "k2.toml").write_text("x", encoding="utf-8")
    new = ["cards", "new", "k2", "--repo", "lib", "--title", "t", "--out", str(tmp_path)]
    assert _main(repo_cfg, *new) == 1
    assert "exists" in capsys.readouterr().err
    assert (tmp_path / "k2.toml").read_text(encoding="utf-8") == "x"


# --- ledger ---------------------------------------------------------------------------------


def test_ledger_filters_by_card_and_kind(
    repo_cfg: AgentOpsConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    _ran(repo_cfg)
    _ran(repo_cfg, id="c2")
    Queue(repo_cfg).state_of("c2")
    _main(repo_cfg, "cards", "accept", "c2")
    capsys.readouterr()
    assert _main(repo_cfg, "ledger", "--card", "c2") == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {r["card"] for r in rows} == {"c2"} and {r["kind"] for r in rows} == {"agy", "review"}
    assert _main(repo_cfg, "ledger", "--kind", "review") == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r["kind"] for r in rows] == ["review"]

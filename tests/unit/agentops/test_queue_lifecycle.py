"""Card lifecycle after `done`: lead review verbs, add-time validation, list output."""

import json

import pytest

from flowfield2d.agentops import ledger
from flowfield2d.agentops.cli import main
from flowfield2d.agentops.config import AgentOpsConfig
from flowfield2d.agentops.queue import STATES, CardError, Queue

from .conftest import make_card


def _main(cfg: AgentOpsConfig, *args: str) -> int:
    return main(["--config", str(cfg.source), *args])


# --- archived state -------------------------------------------------------------------


def test_archived_is_a_queue_state(repo_cfg: AgentOpsConfig) -> None:
    assert "archived" in STATES
    make_card(repo_cfg)
    q = Queue(repo_cfg)
    q.move("c1", "archived")
    assert q.state_of("c1") == "archived"


def test_archived_cards_satisfy_dependencies(repo_cfg: AgentOpsConfig) -> None:
    q = Queue(repo_cfg)
    make_card(repo_cfg)
    q.move("c1", "archived")
    make_card(repo_cfg, id="c2", depends_on=["c1"])
    assert [c.id for c in q.ready()] == ["c2"]


# --- accept / reject --------------------------------------------------------------------


def test_accept_archives_done_card_and_records_review(
    repo_cfg: AgentOpsConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    make_card(repo_cfg)
    Queue(repo_cfg).move("c1", "done")
    assert _main(repo_cfg, "cards", "accept", "c1") == 0
    assert "c1" in capsys.readouterr().out
    assert Queue(repo_cfg).state_of("c1") == "archived"
    rec = ledger.read(repo_cfg.ledger_path)[-1]
    assert rec["kind"] == "review" and rec["card"] == "c1" and rec["decision"] == "accept"


def test_reject_escalates_with_reason(
    repo_cfg: AgentOpsConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    make_card(repo_cfg)
    Queue(repo_cfg).move("c1", "done")
    assert _main(repo_cfg, "cards", "reject", "c1", "--reason", "tests weakened") == 0
    assert Queue(repo_cfg).state_of("c1") == "escalated"
    rec = ledger.read(repo_cfg.ledger_path)[-1]
    assert rec["decision"] == "reject" and rec["reason"] == "tests weakened"


def test_accept_refuses_a_card_that_is_not_done(
    repo_cfg: AgentOpsConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    make_card(repo_cfg)  # pending
    assert _main(repo_cfg, "cards", "accept", "c1") == 1
    assert "pending" in capsys.readouterr().err
    assert Queue(repo_cfg).state_of("c1") == "pending"


# --- validation at add time ---------------------------------------------------------------


def test_add_rejects_unknown_dependency(repo_cfg: AgentOpsConfig) -> None:
    with pytest.raises(CardError, match="depends_on.*c0"):
        make_card(repo_cfg, depends_on=["c0"])


def test_add_rejects_missing_base_branch(repo_cfg: AgentOpsConfig) -> None:
    with pytest.raises(CardError, match="base.*nope"):
        make_card(repo_cfg, base="nope")
    assert Queue(repo_cfg).state_of("c1") is None


# --- list / move output -----------------------------------------------------------------


def test_list_marks_blocked_cards(
    repo_cfg: AgentOpsConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    make_card(repo_cfg)
    make_card(repo_cfg, id="c2", depends_on=["c1"])
    assert _main(repo_cfg, "cards", "list") == 0
    lines = capsys.readouterr().out.splitlines()
    c1 = [line for line in lines if " c1 " in line]
    assert c1 and c1[0].startswith("pending ") and "waits" not in c1[0]
    assert any("c2" in line and "waits c1" in line for line in lines)


def test_list_json_and_state_filter(
    repo_cfg: AgentOpsConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    make_card(repo_cfg)
    make_card(repo_cfg, id="c2")
    Queue(repo_cfg).move("c2", "done")
    assert _main(repo_cfg, "cards", "list", "--state", "done", "--json") == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in rows] == ["c2"]
    assert (rows[0]["state"], rows[0]["repo"], rows[0]["branch"]) == ("done", "lib", "card/c2")


def test_move_reports_the_transition(
    repo_cfg: AgentOpsConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    make_card(repo_cfg)
    assert _main(repo_cfg, "cards", "move", "c1", "done") == 0
    assert "c1: pending -> done" in capsys.readouterr().out

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rasdrive.agentops import cooldown, governor, runner
from rasdrive.agentops.config import AgentOpsConfig
from rasdrive.agentops.queue import Queue

from .test_runner import FAKE, _card, repo_cfg  # noqa: F401  (fixture re-export)

NOW = datetime(2026, 10, 24, 6, 0, tzinfo=UTC)


@pytest.mark.parametrize("text,expected", [
    ("Individual quota reached. Resets in 165h59m3s.", timedelta(hours=165, minutes=59, seconds=3)),
    ("resets in 45m", timedelta(minutes=45)),
    ("Resets in 1d2h", timedelta(days=1, hours=2)),
    ("quota exceeded", None),
])
def test_parse_reset(text: str, expected: timedelta | None) -> None:
    assert cooldown.parse_reset(text) == expected


def test_pools_and_choice(cfg: AgentOpsConfig) -> None:
    assert cfg.agy.model == "m1"
    assert cooldown.pool_of(cfg, "m2") == "b"
    assert cooldown.pool_of(cfg, "unlisted") == "unlisted"
    assert cooldown.choose_model(cfg, None, NOW) == "m1"
    cooldown.set_cooldown(cfg, "a", NOW + timedelta(hours=1))
    assert cooldown.choose_model(cfg, None, NOW) == "m2"
    assert cooldown.choose_model(cfg, "m1", NOW) is None          # a card's own model waits
    later = NOW + timedelta(hours=2)
    assert cooldown.choose_model(cfg, None, later) == "m1"  # expired
    assert cooldown.active(cfg, NOW) == {"a": NOW + timedelta(hours=1)}


def test_governor_reports_cooldowns(cfg: AgentOpsConfig) -> None:
    cooldown.set_cooldown(cfg, "a", NOW + timedelta(hours=1))
    s = governor.status(cfg, now=NOW)
    assert set(s.agy_cooldowns) == {"a"} and s.agy_concurrency > 0
    cooldown.set_cooldown(cfg, "b", NOW + timedelta(hours=1))
    assert governor.status(cfg, now=NOW).agy_concurrency == 0


def test_runner_falls_back_to_next_pool(repo_cfg: AgentOpsConfig,  # noqa: F811
                                        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FAKE_AGY_QUOTA_MODELS", "m1")
    res = runner.run_card(repo_cfg, _card(repo_cfg))
    assert res.state == "done"
    models = [c["argv"][c["argv"].index("--model") + 1]
              for c in map(json.loads, (tmp_path / "agy_calls.jsonl").read_text().splitlines())]
    assert models == ["m1", "m2"]
    until = cooldown.active(repo_cfg)["a"]
    left = until - datetime.now(UTC)
    assert timedelta(hours=2, minutes=29) < left <= timedelta(hours=2, minutes=31)


def test_runner_requeues_without_calling_when_all_cooling(
        repo_cfg: AgentOpsConfig, tmp_path: Path) -> None:  # noqa: F811
    future = datetime.now(UTC) + timedelta(hours=1)
    cooldown.set_cooldown(repo_cfg, "a", future)
    cooldown.set_cooldown(repo_cfg, "b", future)
    res = runner.run_card(repo_cfg, _card(repo_cfg))
    assert res.state == "quota" and Queue(repo_cfg).state_of("c1") == "pending"
    assert not (tmp_path / "agy_calls.jsonl").exists()


def test_unparseable_quota_uses_default_cooldown(repo_cfg: AgentOpsConfig,  # noqa: F811
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.modules["rasdrive.agentops.cooldown"], "parse_reset",
                        lambda text: None)
    monkeypatch.setenv("FAKE_AGY_QUOTA_MODELS", "m1,m2")
    res = runner.run_card(repo_cfg, _card(repo_cfg))
    assert res.state == "quota"
    left = cooldown.active(repo_cfg)["b"] - datetime.now(UTC)
    assert timedelta(minutes=59) < left <= timedelta(minutes=60)
    _ = FAKE

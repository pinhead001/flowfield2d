"""Governor threshold profiles: named sets in [governor.profiles], one active, switchable."""

from pathlib import Path

import pytest

from flowfield2d.agentops.cli import main
from flowfield2d.agentops.config import load_config, set_governor_profile

from .conftest import CONFIG

FLAT = """[governor]
normal_min_remaining = 60
conserve_min_remaining = 25
weekly_pace_slack = 10
unknown_mode = "conserve"
"""
PROFILES = """[governor]
profile = "big"                  # active set
[governor.profiles.small]
normal_min_remaining = 60
conserve_min_remaining = 25
weekly_pace_slack = 10
unknown_mode = "conserve"
[governor.profiles.big]
normal_min_remaining = 20
conserve_min_remaining = 8
weekly_pace_slack = 25
unknown_mode = "normal"
"""


def _write(tmp_path: Path, governor: str) -> Path:
    p = tmp_path / "agents.toml"
    p.write_text(CONFIG.replace(FLAT, governor), encoding="utf-8")
    return p


def test_flat_governor_still_loads(tmp_path: Path) -> None:
    g = load_config(_write(tmp_path, FLAT)).governor
    assert (g.normal_min_remaining, g.profile, g.profiles) == (60.0, "", [])


def test_active_profile_supplies_the_thresholds(tmp_path: Path) -> None:
    g = load_config(_write(tmp_path, PROFILES)).governor
    assert g.profile == "big" and g.profiles == ["small", "big"]
    assert (g.normal_min_remaining, g.conserve_min_remaining, g.weekly_pace_slack,
            g.unknown_mode) == (20.0, 8.0, 25.0, "normal")


def test_unknown_profile_names_the_choices(tmp_path: Path) -> None:
    p = _write(tmp_path, PROFILES.replace('profile = "big"', 'profile = "huge"'))
    with pytest.raises(KeyError, match="small, big"):
        load_config(p)


def test_set_profile_rewrites_only_the_selector(tmp_path: Path) -> None:
    p = _write(tmp_path, PROFILES)
    before = p.read_text(encoding="utf-8")
    set_governor_profile(p, "small")
    after = p.read_text(encoding="utf-8")
    assert after == before.replace('profile = "big"', 'profile = "small"')   # comment kept
    assert load_config(p).governor.normal_min_remaining == 60.0
    with pytest.raises(KeyError):
        set_governor_profile(p, "huge")
    assert p.read_text(encoding="utf-8") == after
    with pytest.raises(ValueError):
        set_governor_profile(_write(tmp_path, FLAT), "small")          # no profiles defined


def test_cli_lists_and_switches(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = _write(tmp_path, PROFILES)
    assert main(["--config", str(p), "gov", "profile"]) == 0
    assert capsys.readouterr().out.split() == ["small", "*big"]
    assert main(["--config", str(p), "gov", "profile", "small"]) == 0
    assert "small" in capsys.readouterr().out
    assert load_config(p).governor.profile == "small"

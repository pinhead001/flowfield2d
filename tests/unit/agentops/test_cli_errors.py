"""CLI failures print one line and exit 1, never a traceback; `gov check` validates the setup."""

from pathlib import Path

import pytest

from flowfield2d.agentops.cli import main
from flowfield2d.agentops.config import AgentOpsConfig
from flowfield2d.agentops.queue import Queue

from .conftest import CONFIG, make_card


def test_missing_config_file_is_one_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nope.toml"
    assert main(["--config", str(missing), "gov", "status"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("agentops: ") and "nope.toml" in err and "Traceback" not in err


def test_missing_config_key_names_file_and_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p = tmp_path / "agents.toml"
    p.write_text(CONFIG.replace("[governor]", "[governorx]"), encoding="utf-8")
    assert main(["--config", str(p), "gov", "status"]) == 1
    err = capsys.readouterr().err
    assert "agents.toml" in err and "governor" in err and err.count("\n") == 1


def test_no_config_at_all_explains_the_env_var(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("AGENTOPS_CONFIG", raising=False)
    assert main(["gov", "status"]) == 1
    assert "AGENTOPS_CONFIG" in capsys.readouterr().err


def test_unknown_card_is_one_line(
    repo_cfg: AgentOpsConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    for verb in (["reset", "nope"], ["move", "nope", "done"], ["accept", "nope"]):
        assert main(["--config", str(repo_cfg.source), "cards", *verb]) == 1
        err = capsys.readouterr().err
        assert err.startswith("agentops: ") and "nope" in err and "Traceback" not in err


def test_bad_card_file_is_one_line(
    repo_cfg: AgentOpsConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text('id = "x"\n', encoding="utf-8")
    assert main(["--config", str(repo_cfg.source), "cards", "add", str(bad)]) == 1
    err = capsys.readouterr().err
    assert "bad.toml" in err and "repo" in err and "Traceback" not in err


def test_gov_check_passes_on_a_complete_setup(
    repo_cfg: AgentOpsConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    make_card(repo_cfg)
    assert main(["--config", str(repo_cfg.source), "gov", "check"]) == 0
    out = capsys.readouterr().out
    assert "ok" in out and "FAIL" not in out
    assert "lib" in out and "state_dir" in out and "agy" in out


def test_gov_check_reports_each_problem(
    cfg: AgentOpsConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    # `cfg` has no checkout for repo `lib` and names a delegate that is not on PATH.
    cfg.agy.command = ["definitely-not-a-real-executable-xyz"]
    cfg.source.write_text(
        cfg.source.read_text(encoding="utf-8").replace(
            'exe = "agy"', 'exe = "definitely-not-a-real-executable-xyz"'
        ),
        encoding="utf-8",
    )
    assert main(["--config", str(cfg.source), "gov", "check"]) == 1
    out = capsys.readouterr().out
    fails = [line for line in out.splitlines() if line.startswith("FAIL")]
    assert any("lib" in line for line in fails)
    assert any("definitely-not-a-real-executable-xyz" in line for line in fails)


def test_every_subcommand_has_help(capsys: pytest.CaptureFixture[str]) -> None:
    for group in ("gov", "cards"):
        with pytest.raises(SystemExit):
            main([group, "--help"])
        out = capsys.readouterr().out
        # argparse lists `name  help` under the positional block; a verb without help is bare.
        block = out.split("positional arguments:")[1].split("options:")[0]
        verbs = block.splitlines()[1].strip().strip("{}").split(",")
        for v in verbs:
            assert any(line.strip().startswith(v + " ") for line in block.splitlines()), (
                f"{group} {v} has no help"
            )


def test_gov_next_prints_the_mode_once_then_advice(
    repo_cfg: AgentOpsConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    repo_cfg.claude_usage_path.parent.mkdir(parents=True, exist_ok=True)
    repo_cfg.claude_usage_path.write_text(
        '{"five_hour": {"used_percentage": 10, "resets_at": 4102444800},'
        ' "seven_day": {"used_percentage": 10, "resets_at": 4102444800}}'
    )
    make_card(repo_cfg)
    assert main(["--config", str(repo_cfg.source), "gov", "next"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("governor: normal")
    assert "meter updated" not in "\n".join(out) and "cooldowns" not in "\n".join(out)
    assert any(line.startswith("next: 1 ready") for line in out)
    assert any(line.startswith("dispatch:") for line in out)


def test_gov_next_points_at_the_review_verbs_when_cards_are_done(
    repo_cfg: AgentOpsConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    make_card(repo_cfg)
    Queue(repo_cfg).move("c1", "done")
    assert main(["--config", str(repo_cfg.source), "gov", "next"]) == 0
    out = capsys.readouterr().out
    assert "review:" in out and "cards show c1" in out and "accept" in out

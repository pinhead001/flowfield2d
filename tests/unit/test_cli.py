from pathlib import Path

from typer.testing import CliRunner

from flowfield2d.cli import app
from flowfield2d.engines.ras2025.bc import payloads

from .test_ras_bc import _bc

runner = CliRunner()


def test_bc_commands(tmp_path: Path) -> None:
    p = _bc(tmp_path)
    r = runner.invoke(app, ["bc", "set-slope", str(p), "0.002"])
    assert r.exit_code == 0, r.output
    assert payloads(p)[0].constant == 0.002
    assert runner.invoke(app, ["bc", "set-slope", str(p), "0"]).exit_code != 0
    assert runner.invoke(app, ["bc", "set-slope", str(p), "0", "--allow-invalid"]).exit_code == 0
    assert runner.invoke(app, ["bc", "scale-flow", str(p), "2"]).exit_code == 0
    shown = runner.invoke(app, ["bc", "show", str(p)])
    assert shown.exit_code == 0 and "Normal Depth" in shown.output and "Flow" in shown.output

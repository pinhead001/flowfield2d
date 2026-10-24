import json
import sys
from pathlib import Path

import psutil
import pytest

from flowfield2d.engines.ras2025.cli import RasCli, RasCliError

FAKE = Path(__file__).resolve().parents[1] / "fixtures" / "fake_ras.py"


@pytest.fixture
def cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RasCli:
    monkeypatch.setenv("FAKE_RAS_LOG", str(tmp_path / "calls.jsonl"))
    monkeypatch.delenv("FAKE_RAS_FAIL", raising=False)
    return RasCli([sys.executable, str(FAKE)], timeout_s=30)


def _calls(tmp_path: Path) -> list[list[str]]:
    return [json.loads(x) for x in (tmp_path / "calls.jsonl").read_text().splitlines()]


def test_info_json(cli: RasCli) -> None:
    assert cli.info_json(Path("p.h5")) == {"type": "plan", "path": "p.h5"}


def test_plan_solve_argv_always_has_if_exists(cli: RasCli, tmp_path: Path) -> None:
    r = cli.plan_solve(Path("x.h5"), processor="CPU", core_count=4)
    assert r.exit_code == 0 and "progress" in r.stdout
    assert _calls(tmp_path)[-1] == ["plan", "solve", "x.h5", "--if-exists", "error",
                                    "--processor", "CPU", "--core-count", "4"]
    cli.plan_solve(Path("x.h5"), output=Path("o.h5"), if_exists="force",
                   time_stepping="Implicit", equation="SWE")
    assert _calls(tmp_path)[-1] == ["plan", "solve", "x.h5", "o.h5", "--if-exists", "force",
                                    "--equation", "SWE", "--time-stepping", "Implicit"]
    with pytest.raises(ValueError):
        cli.plan_solve(Path("x.h5"), if_exists="maybe")
    with pytest.raises(ValueError):
        cli.plan_solve(Path("x.h5"), processor="TPU")


def test_failure_raises_with_stderr(cli: RasCli, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_RAS_FAIL", "1")
    with pytest.raises(RasCliError) as e:
        cli.plan_solve(Path("x.h5"))
    assert e.value.result.exit_code == 3 and "boundary condition" in str(e.value)


def test_plan_modify_and_other_verbs(cli: RasCli, tmp_path: Path) -> None:
    rep = cli.plan_modify(Path("p.h5"), {"corecount": "8", "name": "a b"}, dry_run=True)
    assert rep == {"changes": ["corecount = 8", "name = a b"]}
    assert _calls(tmp_path)[-1] == ["plan", "modify", "p.h5", "corecount = 8", "name = a b",
                                    "--dry-run", "--format", "Json"]
    cli.generate_mesh(Path("g.h5"))
    cli.terrain_create(Path("proj"), "t1")
    cli.terrain_add(Path("t.h5"), [Path("a.tif"), Path("b.tif")])
    cli.project_add_new(Path("proj"), "plan", "p2")
    cli.result_map(Path("r.h5"), Path("out.tif"), map_type="depth", profile="0")
    cli.result_postprocess(Path("r.h5"), force=True)
    cli.clone(Path("a.h5"), Path("b.h5"))
    assert _calls(tmp_path)[-7:] == [
        ["geometry", "generate-mesh", "g.h5"],
        ["terrain", "create", "-n", "t1", "-p", "proj"],
        ["terrain", "add", "t.h5", "--files", "a.tif", "b.tif"],
        ["project", "add-new", "-p", "proj", "-t", "plan", "-n", "p2"],
        ["result", "map", "r.h5", "out.tif", "--type", "depth", "-p", "0"],
        ["result", "postprocess", "r.h5", "--force"],
        ["clone", "-s", "a.h5", "-o", "b.h5"],
    ]
    with pytest.raises(ValueError):
        cli.project_add_new(Path("proj"), "result", "r")


def test_timeout_kills_process_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FAKE_RAS_LOG", raising=False)
    cli = RasCli([sys.executable, str(FAKE)], timeout_s=3)
    r = cli.run(["sleep"], check=False)
    assert r.timed_out and r.exit_code is None
    child_pid = int(r.stdout.split()[0])
    assert not psutil.pid_exists(child_pid) or \
        psutil.Process(child_pid).status() == psutil.STATUS_ZOMBIE
    with pytest.raises(RasCliError, match="timed out"):
        cli.run(["sleep"])

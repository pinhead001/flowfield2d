"""Tests for cliprobe: help parsing across CLI frameworks and safe crawling."""
from __future__ import annotations

import ast
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import cliprobe  # noqa: E402

FAKE = HERE / "fakes" / "fake_cli.py"


# ---------------------------------------------------------------- parsing

SCL = """Description:
  HEC-RAS

Usage:
  ras [command] [options]

Options:
  --version       Show version information
  -?, -h, --help  Show help and usage information

Commands:
  terrain  Terrain operations
  compute <plan>  Run a plan and write results that are long enough
                  to wrap onto a second line
"""

SPECTRE = """USAGE:
    ras [OPTIONS] <COMMAND>

OPTIONS:
    -h, --help    Prints help information

COMMANDS:
    add <PATH>    Add a terrain
    list          List terrains
"""

CLICK = """Usage: tool [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  build  Build things
  run    Run things
"""

TYPER_RICH = """ Usage: tool [OPTIONS] COMMAND [ARGS]...
╭─ Options ──────────────────────────────╮
│ --help          Show this message and exit. │
╰────────────────────────────────────────╯
╭─ Commands ─────────────────────────────╮
│ build   Build things                    │
│ run     Run things                      │
╰────────────────────────────────────────╯
"""

ARGPARSE = """usage: prog [-h] {add,list} ...

positional arguments:
  {add,list}
    add       add a thing

options:
  -h, --help  show this help message and exit
"""

VERBS = """fake 1.2.3
Copyright (c) Fake

  terrain    Terrain operations
  compute    Run a plan
  help       Display more information on a specific command.
  version    Display version information.
"""


def names(parsed):
    return [c["name"] for c in parsed["commands"]]


def test_parse_system_commandline():
    p = cliprobe.parse_help(SCL)
    assert p["format"] == "system.commandline"
    assert names(p) == ["terrain", "compute"]
    assert p["commands"][1]["args"] == "<plan>"
    assert "wrap onto a second line" in p["commands"][1]["description"]
    assert any("--help" in o["flags"] for o in p["options"])
    assert p["usage"] == ["ras [command] [options]"]


def test_parse_spectre():
    p = cliprobe.parse_help(SPECTRE)
    assert p["format"] == "spectre"
    assert names(p) == ["add", "list"]
    assert p["commands"][0]["args"] == "<PATH>"


def test_parse_click_and_rich_boxes():
    assert names(cliprobe.parse_help(CLICK)) == ["build", "run"]
    assert names(cliprobe.parse_help(TYPER_RICH)) == ["build", "run"]


def test_parse_argparse_braces():
    assert set(names(cliprobe.parse_help(ARGPARSE))) >= {"add", "list"}


def test_parse_commandlineparser_verbs():
    p = cliprobe.parse_help(VERBS)
    assert p["format"] == "commandlineparser"
    assert names(p) == ["terrain", "compute", "help", "version"]


def test_ansi_is_stripped():
    p = cliprobe.parse_help("\x1b[1mCommands:\x1b[0m\n  \x1b[32mrun\x1b[0m  Run it\n")
    assert names(p) == ["run"]


# ---------------------------------------------------------------- crawling


def crawl(tmp_path, style, **kw):
    log = tmp_path / "argv.log"
    import os
    os.environ["FAKE_STYLE"] = style
    os.environ["FAKE_LOG"] = str(log)
    out = tmp_path / "out"
    args = ["crawl", "--exe", str(FAKE), "--interpreter", sys.executable, "--out", str(out),
            "--cwd", str(tmp_path / "cwd")]
    for k, v in kw.items():
        args += [f"--{k.replace('_', '-')}", str(v)]
    assert cliprobe.main(args) == 0
    tree = json.loads((out / "cli_tree.json").read_text())
    logged = [ln for ln in log.read_text().splitlines()]
    return tree, logged, out


def test_crawl_system_commandline_tree_and_safety(tmp_path):
    tree, logged, out = crawl(tmp_path, "scl")
    paths = {tuple(n["path"]): n["status"] for n in tree["nodes"]}
    for p in [(), ("terrain",), ("terrain", "add"), ("terrain", "list"), ("mesh",),
              ("mesh", "generate"), ("compute",)]:
        assert paths.get(p) == "help", (p, paths)
    skipped = {tuple(s["path"]): s["reason"] for s in tree["skipped"]}
    assert "risky" in skipped[("delete",)]
    assert ("help",) in skipped and ("version",) in skipped
    assert tree["version"]["text"].startswith("fake-ras")
    # The crawler must never run anything for real.
    assert "EXECUTED" not in logged
    for line in logged:
        argv = ast.literal_eval(line)
        assert argv and (argv[-1] in {"--help", "-h", "-?", "/?", "--version", "-V", "-v", "version"}
                         or argv[0] == "help"), argv
    md = (out / "cli_tree.md").read_text()
    assert "Regenerate the computational mesh" in md


def test_crawl_spectre(tmp_path):
    tree, logged, _ = crawl(tmp_path, "spectre")
    paths = {tuple(n["path"]) for n in tree["nodes"] if n["status"] == "help"}
    assert ("terrain", "add") in paths
    assert "EXECUTED" not in logged


def test_crawl_gui_times_out_and_is_bounded(tmp_path):
    start = time.monotonic()
    tree, _, _ = crawl(tmp_path, "gui", timeout=1, max_calls=3)
    assert time.monotonic() - start < 20
    root = next(n for n in tree["nodes"] if n["path"] == [])
    assert root["status"] == "timeout"
    assert tree["truncated"] is True


def test_allow_overrides_risky(tmp_path):
    tree, logged, _ = crawl(tmp_path, "scl", allow="delete")
    assert not any(s["path"] == ["delete"] for s in tree["skipped"])
    assert "EXECUTED" not in logged


def test_run_kills_on_timeout():
    res = cliprobe.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1)
    assert res.timed_out and res.exit_code is None and res.duration_s < 10


def test_seed_paths(tmp_path):
    tree, _, _ = crawl(tmp_path, "scl", seed="terrain add", max_depth=0)
    paths = {tuple(n["path"]) for n in tree["nodes"]}
    assert ("terrain", "add") in paths

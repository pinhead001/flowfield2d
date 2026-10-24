#!/usr/bin/env python3
"""Fake CLIs for cliprobe tests. Style chosen by FAKE_STYLE; every argv is logged to FAKE_LOG.

Styles: scl (System.CommandLine), spectre, verbs (CommandLineParser), gui (never exits).
Any invocation that is not a help/version request writes EXECUTED to the log and exits 99,
so tests can prove the crawler never runs a command for real.
"""
import os
import sys
import time

STYLE = os.environ.get("FAKE_STYLE", "scl")
LOG = os.environ.get("FAKE_LOG")
args = sys.argv[1:]
if LOG:
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(repr(args) + "\n")

HELP = {"--help", "-h", "-?", "/?"}
VERSION = {"--version", "-V", "version"}

TREE = {
    (): ["terrain", "mesh", "compute", "delete", "help", "version"],
    ("terrain",): ["add", "list"],
    ("mesh",): ["generate"],
}
DESC = {"terrain": "Terrain operations", "mesh": "Mesh operations", "compute": "Run a plan",
        "delete": "Delete a project", "add": "Add a terrain layer", "list": "List terrains",
        "generate": "Regenerate the computational mesh", "help": "Show help", "version": "Show version"}


def scl(path):
    lines = ["Description:", "  Fake RAS.", "", "Usage:", f"  ras {' '.join(path)} [command] [options]".replace("  ", " ", 1), "",
             "Options:", "  --version       Show version information", "  -?, -h, --help  Show help and usage information", ""]
    kids = TREE.get(path, [])
    if kids:
        lines.append("Commands:")
        for k in kids:
            if k in ("help", "version") and path:
                continue
            arg = " <path>" if k == "add" else ""
            lines.append(f"  {k}{arg}  {DESC[k]}")
    return "\n".join(lines)


def spectre(path):
    lines = ["USAGE:", f"    ras {' '.join(path)} [OPTIONS] <COMMAND>", "", "OPTIONS:",
             "    -h, --help    Prints help information", ""]
    kids = [k for k in TREE.get(path, []) if k not in ("help", "version")]
    if kids:
        lines.append("COMMANDS:")
        lines += [f"    {k} <ARG>    {DESC[k]}" for k in kids]
    return "\n".join(lines)


def verbs(path):
    return "\n".join(["fake 1.2.3", "Copyright (c) Fake", "",
                      "  terrain    Terrain operations", "  compute    Run a plan",
                      "  help       Display more information on a specific command.",
                      "  version    Display version information.", ""])


if STYLE == "gui":
    time.sleep(60)
    sys.exit(0)

if args and args[-1] in VERSION and len(args) == 1:
    print("fake-ras 0.1.0.5048-dev")
    sys.exit(0)

if args and args[0] == "help":
    path, ok = tuple(args[1:]), True
elif args and args[-1] in HELP:
    path, ok = tuple(args[:-1]), True
else:
    path, ok = tuple(args), False

if not ok:
    if LOG:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write("EXECUTED\n")
    print("Unrecognized command or argument", file=sys.stderr)
    sys.exit(99)

if STYLE == "verbs":
    print(verbs(path))
    sys.exit(0 if not path else 1)
if path not in TREE and path[:-1] not in TREE:
    print(f"Unrecognized command '{' '.join(path)}'", file=sys.stderr)
    sys.exit(1)
print(scl(path) if STYLE == "scl" else spectre(path))
sys.exit(0)

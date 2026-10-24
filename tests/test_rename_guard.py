"""Rename guard (ADR-0003): the retired working names must not come back.

Fails if the old engine-bound name, or the bare old folder name (without the "2d" suffix),
appears in any tracked file. Exempt: ADR-0003 itself, CHANGELOG.md, and older ADRs that carry
the rename pointer. The names are assembled from parts so this file does not match itself.
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD_NAMES = re.compile("(" + "ras" + "drive" + "|" + "flow" + "field" + r"(?!2d))", re.IGNORECASE)
POINTER = "see ADR-0003"
EXEMPT = {"CHANGELOG.md", "docs/adr/0003-library-name-flowfield2d.md"}


def offending_lines(text: str) -> list[tuple[int, str]]:
    return [(n, line) for n, line in enumerate(text.splitlines(), 1) if OLD_NAMES.search(line)]


def _tracked_text_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    files = []
    for rel in filter(None, out.stdout.decode("utf-8").split("\0")):
        p = ROOT / rel
        if p.is_file() and b"\x00" not in p.read_bytes()[:8192]:
            files.append(p)
    return files


def test_matcher_catches_old_names_and_spares_new() -> None:
    old = "ras" + "drive"
    bare = "flow" + "field"
    assert offending_lines(f"import {old}\npath = D:/a/{bare}\nok = {bare}2d\n") == [
        (1, f"import {old}"), (2, f"path = D:/a/{bare}")]
    assert offending_lines(f"{bare.upper()}_X = 1") and not offending_lines(f"{bare}2d.engines")


def test_no_retired_names_in_tracked_files() -> None:
    hits = []
    for p in _tracked_text_files():
        rel = p.relative_to(ROOT).as_posix()
        if rel in EXEMPT:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if rel.startswith("docs/adr/") and POINTER in text:
            continue
        hits += [f"{rel}:{n}: {line.strip()[:120]}" for n, line in offending_lines(text)]
    assert not hits, "retired library names found:\n" + "\n".join(hits)

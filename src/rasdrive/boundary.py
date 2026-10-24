"""Banned-term scanner behind the boundary test.

A term file holds one term per line. Blank lines and lines starting with `#`
are ignored. A plain term matches case-insensitively as a whole token, where
any character other than a letter or digit counts as a boundary (so `_` and
`-` do). A line starting with `re:` is a case-insensitive regular expression.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SUBDIRS = ("src", "tools", "docs")
SKIP_DIRS = {"__pycache__", ".git", ".venv", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


@dataclass(frozen=True)
class Term:
    label: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class Hit:
    path: Path
    line: int
    term: str
    text: str


def load_terms(files: Iterable[Path]) -> list[Term]:
    terms: list[Term] = []
    for f in files:
        for raw in Path(f).read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("re:"):
                pat = re.compile(line[3:], re.IGNORECASE)
            else:
                pat = re.compile(
                    rf"(?<![A-Za-z0-9]){re.escape(line)}(?![A-Za-z0-9])", re.IGNORECASE
                )
            terms.append(Term(line, pat))
    return terms


def _text_files(root: Path) -> Iterable[Path]:
    for p in sorted(root.rglob("*")):
        if not p.is_file() or SKIP_DIRS.intersection(p.relative_to(root).parts):
            continue
        data = p.read_bytes()
        if b"\x00" in data[:8192]:
            continue
        yield p


def scan(root: Path, terms: Sequence[Term], subdirs: Sequence[str] = DEFAULT_SUBDIRS) -> list[Hit]:
    hits: list[Hit] = []
    for sub in subdirs:
        base = Path(root) / sub
        if not base.is_dir():
            continue
        for p in _text_files(base):
            text = p.read_text(encoding="utf-8", errors="replace")
            for n, line in enumerate(text.splitlines(), 1):
                for t in terms:
                    if t.pattern.search(line):
                        hits.append(Hit(p, n, t.label, line.strip()))
    return hits


def format_hits(hits: Sequence[Hit], root: Path) -> str:
    return "\n".join(
        f"{h.path.relative_to(root)}:{h.line}: [{h.term}] {h.text[:120]}" for h in hits
    )

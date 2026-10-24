"""Boundary rule (REQUIREMENTS 1): no project-specific terms in src/, tools/ or docs/.

Consumers keep their banned-term lists in their own repos and point
FLOWFIELD2D_BOUNDARY_TERMS at them (os.pathsep-separated file paths).
"""

import os
from pathlib import Path

import pytest

from flowfield2d.boundary import format_hits, load_terms, scan

ROOT = Path(__file__).resolve().parents[1]


def _term_files() -> list[Path]:
    raw = os.environ.get("FLOWFIELD2D_BOUNDARY_TERMS", "")
    return [Path(p) for p in raw.split(os.pathsep) if p.strip()]


def test_boundary() -> None:
    files = _term_files()
    if not files:
        pytest.skip("FLOWFIELD2D_BOUNDARY_TERMS not set; no consumer term list to check")
    missing = [f for f in files if not f.is_file()]
    assert not missing, f"term files not found: {missing}"
    hits = scan(ROOT, load_terms(files))
    assert not hits, "banned terms found:\n" + format_hits(hits, ROOT)

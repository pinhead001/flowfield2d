"""Clone RAS-written template projects; never build files from scratch (REQUIREMENTS 3.3, ADR-0001).

Under Tier B a person authors each domain's base project once in the GUI. Every run works on a clone
of it: results and GUI backup folders are left behind. The clone's HDF5 structure must match the
template baseline (fingerprints taken when the template was accepted) before anything edits it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from flowfield2d.engines.ras2025.h5schema import SchemaDiff, SchemaMismatch, fingerprint, walk

SKIP_DIRS = {"Results"}


def _skip(rel: Path) -> bool:
    return any(part in SKIP_DIRS or part.endswith(" Backups") for part in rel.parts)


def clone_project(template: Path, dest: Path) -> Path:
    """Copy a RAS project folder (with its `.ras`) to a new folder, minus results and backups."""
    template, dest = Path(template), Path(dest)
    if not list(template.glob("*.ras")):
        raise FileNotFoundError(f"no .ras project file in {template}")
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"destination not empty: {dest}")
    for src in sorted(template.rglob("*")):
        rel = src.relative_to(template)
        if _skip(rel):
            continue
        out = dest / rel
        if src.is_dir():
            out.mkdir(parents=True, exist_ok=True)
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out)
    (dest / "Results").mkdir(parents=True, exist_ok=True)
    return dest


def fingerprints(project: Path) -> dict[str, str]:
    """Structural fingerprint of every HDF5 layer in a project (results and backups excluded)."""
    out: dict[str, str] = {}
    for p in sorted(Path(project).rglob("*.h5")):
        rel = p.relative_to(project)
        if not _skip(rel):
            out[rel.as_posix()] = fingerprint(walk(p))
    return out


def verify_template(project: Path, baseline: dict[str, str]) -> None:
    """Raise SchemaMismatch if any layer is missing, extra, or structurally different."""
    current = fingerprints(project)
    bad = sorted(k for k in set(baseline) | set(current) if baseline.get(k) != current.get(k))
    if bad:
        lines = [f"{k}: {baseline.get(k, 'missing')} -> {current.get(k, 'missing')}" for k in bad]
        diff = SchemaDiff(kind_changed=lines)
        raise SchemaMismatch("template layers differ from baseline:\n" + "\n".join(lines), diff)

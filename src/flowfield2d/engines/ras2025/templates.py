"""Clone RAS-written template projects; never build files from scratch (REQUIREMENTS 3.3, ADR-0001).

Under Tier B a person authors each domain's base project once in the GUI. Every run works on a clone
of it: results and GUI backup folders are left behind. The clone's HDF5 structure must match the
template baseline (fingerprints taken when the template was accepted) before anything edits it.

A donor project's layers can be copied under new names and bound in the project file, all headless;
proven by a solve on real RAS.
"""

from __future__ import annotations

import re
import shutil
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from pathlib import Path
from xml.sax.saxutils import quoteattr

import h5py

from flowfield2d.engines.ras2025.h5edit import write_fixed_string_attr
from flowfield2d.engines.ras2025.h5schema import SchemaDiff, SchemaMismatch, fingerprint, walk

SKIP_DIRS = {"Results"}
SKIP_FILES = {".lock"}   # RAS open-project lock; held by a GUI session, never template content

LAYER_KINDS: dict[str, tuple[str, str]] = {
    "geometry": ("Geometries", "Geometry"),
    "boundary": ("Boundary Conditions", "Boundary Conditions"),
    "plan": ("Plans", "Plan Data"),
}


def _skip(rel: Path) -> bool:
    if rel.name in SKIP_FILES:
        return True
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


def _ras_file(project: Path) -> Path:
    """Return the path to the single .ras file in the project folder."""
    project = Path(project)
    if project.is_file() and project.suffix.lower() == ".ras":
        return project
    ras_files = sorted(project.glob("*.ras"))
    if not ras_files:
        raise FileNotFoundError(f"no .ras project file in {project}")
    if len(ras_files) > 1:
        raise ValueError(f"multiple .ras project files found in {project}")
    return ras_files[0]


def copy_layer(project: Path, kind: str, src: str, new: str) -> Path:
    """Copy an HDF5 layer to a new name and update its internal Name attribute."""
    project = Path(project)
    if kind not in LAYER_KINDS:
        raise ValueError(f"unknown layer kind: {kind!r}")
    folder, group = LAYER_KINDS[kind]
    src_path = project / folder / f"{src}.h5"
    if not src_path.exists():
        raise FileNotFoundError(f"source layer not found: {src_path}")
    dest_path = project / folder / f"{new}.h5"
    if dest_path.exists():
        raise FileExistsError(f"destination layer already exists: {dest_path}")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_path, dest_path)
    try:
        with h5py.File(dest_path, "r+", locking=False) as f:
            if group not in f or "Name" not in f[group].attrs:
                raise KeyError(f"{src_path.name} has no {group}/Name attribute")
            write_fixed_string_attr(f[group], "Name", new)
    except KeyError as exc:
        dest_path.unlink(missing_ok=True)
        raise ValueError(str(exc).strip("'\"")) from exc
    except ValueError as exc:
        dest_path.unlink(missing_ok=True)
        raise ValueError(f"layer name is too long for fixed width: {new!r}") from exc
    except Exception:
        dest_path.unlink(missing_ok=True)
        raise
    return dest_path


def associations(project: Path) -> dict[str, dict[str, tuple[str, str]]]:
    """Parse plan and geometry associations from the project's .ras file."""
    ras_path = _ras_file(project)
    text = ras_path.read_text(encoding="utf-8-sig")
    root = ET.fromstring(text.encode("utf-8"))

    plans: dict[str, tuple[str, str]] = {}
    for elem in root.iter("PlanAssociation"):
        plan = elem.attrib.get("Plan")
        geom = elem.attrib.get("Geometry", "")
        bc = elem.attrib.get("BoundaryCondition", "")
        if plan is not None:
            plans[plan] = (geom, bc)

    geometries: dict[str, tuple[str, str]] = {}
    for elem in root.iter("GeometryAssociation"):
        gname = elem.attrib.get("Geometry")
        terrain = elem.attrib.get("Terrain", "")
        n_values = elem.attrib.get("N_Values", "")
        if gname is not None:
            geometries[gname] = (terrain, n_values)

    return {"plans": plans, "geometries": geometries}


def _update_association_lines(
    lines: list[str],
    items: Mapping[str, tuple[str, str]],
    tag_name: str,
    key_attr: str,
    val_attrs: tuple[str, str],
    container_tag: str,
    default_newline: str,
) -> None:
    """Replace existing association lines or insert new lines before the closing container tag."""
    for key, values in items.items():
        attrs = [f"{key_attr}={quoteattr(key)}"]
        for attr_name, val in zip(val_attrs, values, strict=True):
            attrs.append(f"{attr_name}={quoteattr(val)}")
        new_tag_content = f"<{tag_name} {' '.join(attrs)} />"

        quoted_inner = quoteattr(key)[1:-1]
        pattern = re.compile(
            rf'<\s*{tag_name}\b[^>]*?\b{key_attr}\s*=\s*["\'](?:{re.escape(key)}|{re.escape(quoted_inner)})["\']'
        )
        matched_idx = -1
        for idx, line in enumerate(lines):
            if pattern.search(line):
                matched_idx = idx
                break

        if matched_idx >= 0:
            line = lines[matched_idx]
            m = re.match(r"^(\s*)", line)
            indent = m.group(1) if m else ""
            nl = ("\r\n" if line.endswith("\r\n")
                  else "\n" if line.endswith("\n") else default_newline)
            lines[matched_idx] = f"{indent}{new_tag_content}{nl}"
        else:
            closing_pattern = re.compile(rf'<\s*/{container_tag}\s*>')
            closing_idx = -1
            for idx, line in enumerate(lines):
                if closing_pattern.search(line):
                    closing_idx = idx
                    break
            if closing_idx < 0:
                raise ValueError(f"closing tag </{container_tag}> not found")

            open_pattern = re.compile(rf'<\s*{container_tag}\b')
            open_idx = -1
            for idx in range(closing_idx - 1, -1, -1):
                if open_pattern.search(lines[idx]):
                    open_idx = idx
                    break

            sibling_indent: str | None = None
            nl = default_newline
            if open_idx >= 0:
                for idx in range(open_idx + 1, closing_idx):
                    if re.search(rf'<\s*{tag_name}\b', lines[idx]):
                        m = re.match(r"^(\s*)", lines[idx])
                        if m:
                            sibling_indent = m.group(1)
                        if lines[idx].endswith("\r\n"):
                            nl = "\r\n"
                        elif lines[idx].endswith("\n"):
                            nl = "\n"
                        break

            if sibling_indent is None:
                m = re.match(r"^(\s*)", lines[closing_idx])
                closing_indent = m.group(1) if m else ""
                sibling_indent = closing_indent + "  "

            new_line = f"{sibling_indent}{new_tag_content}{nl}"
            lines.insert(closing_idx, new_line)


def set_associations(
    project: Path,
    *,
    plans: Mapping[str, tuple[str, str]] | None = None,
    geometries: Mapping[str, tuple[str, str]] | None = None,
) -> None:
    """Add or replace plan and geometry associations in the project's .ras file."""
    if plans is None:
        plans = {}
    if geometries is None:
        geometries = {}

    ras_path = _ras_file(project)
    raw = ras_path.read_bytes()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    content_bytes = raw[3:] if has_bom else raw
    newline = "\r\n" if b"\r\n" in content_bytes else "\n"
    content = content_bytes.decode("utf-8")
    lines = content.splitlines(keepends=True)

    if plans:
        _update_association_lines(
            lines,
            plans,
            tag_name="PlanAssociation",
            key_attr="Plan",
            val_attrs=("Geometry", "BoundaryCondition"),
            container_tag="PlanAssociations",
            default_newline=newline,
        )

    if geometries:
        _update_association_lines(
            lines,
            geometries,
            tag_name="GeometryAssociation",
            key_attr="Geometry",
            val_attrs=("Terrain", "N_Values"),
            container_tag="GeometryAssociations",
            default_newline=newline,
        )

    out_text = "".join(lines)
    out_bytes = (b"\xef\xbb\xbf" if has_bom else b"") + out_text.encode("utf-8")
    ras_path.write_bytes(out_bytes)

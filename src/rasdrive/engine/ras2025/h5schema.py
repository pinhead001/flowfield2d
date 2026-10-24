"""Structural fingerprints of RAS HDF5 files and the schema guard.

Walk an HDF5 file to collect its structural metadata (groups, datasets, links,
attribute types), compute a shape-independent fingerprint, diff two structures,
and raise ``SchemaMismatch`` when a file deviates from the expected schema.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import h5py
import h5py.h5a
import h5py.h5o
import h5py.h5t

# ---------------------------------------------------------------------------
# Internal helpers — ported from tools/probe/rasprobe.py h5_type / _attrs / _dataset / h5_walk
# ---------------------------------------------------------------------------


def _h5_type(tid: Any) -> dict[str, Any]:
    """Return a JSON-serialisable description of an HDF5 type identifier."""
    t = h5py.h5t
    cls = tid.get_class()
    if cls == t.STRING:
        d: dict[str, Any] = {"class": "string", "variable": bool(tid.is_variable_str())}
        if not d["variable"]:
            d["size"] = tid.get_size()
        d["strpad"] = {
            t.STR_NULLTERM: "NULLTERM",
            t.STR_NULLPAD: "NULLPAD",
            t.STR_SPACEPAD: "SPACEPAD",
        }.get(tid.get_strpad(), str(tid.get_strpad()))
        d["cset"] = {t.CSET_ASCII: "ASCII", t.CSET_UTF8: "UTF8"}.get(
            tid.get_cset(), str(tid.get_cset())
        )
        return d
    if cls == t.INTEGER:
        return {
            "class": "int",
            "size": tid.get_size(),
            "signed": tid.get_sign() == t.SGN_2,
            "order": "LE" if tid.get_order() == t.ORDER_LE else "BE",
        }
    if cls == t.FLOAT:
        return {
            "class": "float",
            "size": tid.get_size(),
            "order": "LE" if tid.get_order() == t.ORDER_LE else "BE",
        }
    if cls == t.COMPOUND:
        return {
            "class": "compound",
            "size": tid.get_size(),
            "members": [
                {
                    "name": tid.get_member_name(i).decode("utf-8", "replace"),
                    "offset": tid.get_member_offset(i),
                    "type": _h5_type(tid.get_member_type(i)),
                }
                for i in range(tid.get_nmembers())
            ],
        }
    if cls == t.ENUM:
        return {
            "class": "enum",
            "base": _h5_type(tid.get_super()),
            "members": {
                tid.get_member_name(i).decode("utf-8", "replace"): int(
                    tid.get_member_value(i)
                )
                for i in range(tid.get_nmembers())
            },
        }
    if cls == t.ARRAY:
        return {
            "class": "array",
            "dims": list(tid.get_array_dims()),
            "base": _h5_type(tid.get_super()),
        }
    if cls == t.VLEN:
        return {"class": "vlen", "base": _h5_type(tid.get_super())}
    if cls == t.OPAQUE:
        return {"class": "opaque", "size": tid.get_size()}
    if cls == t.REFERENCE:
        return {"class": "reference", "size": tid.get_size()}
    if cls == t.BITFIELD:
        return {"class": "bitfield", "size": tid.get_size()}
    return {"class": f"other:{cls}", "size": tid.get_size()}


def _attrs(obj: Any) -> dict[str, Any]:
    """Return a mapping of attribute name → type descriptor dict for *obj*."""
    out: dict[str, Any] = {}
    for name in obj.attrs.keys():
        rec: dict[str, Any] = {}
        try:
            aid = h5py.h5a.open(obj.id, name.encode("utf-8"))
            ftype = aid.get_type()
            rec["type"] = _h5_type(ftype)
            shape = aid.get_space().shape
            rec["shape"] = list(shape) if shape is not None else None
        except Exception as exc:  # pragma: no cover
            rec["error"] = str(exc)
        out[name] = rec
    return out


def _dataset_info(ds: Any) -> dict[str, Any]:
    """Return the structural descriptor for an h5py Dataset."""
    plist = ds.id.get_create_plist()
    filters: list[dict[str, Any]] = []
    for i in range(plist.get_nfilters()):
        code, _flags, values, name = plist.get_filter(i)
        filters.append(
            {
                "code": int(code),
                "name": name.decode("utf-8", "replace"),
                "values": [int(v) for v in values],
            }
        )
    return {
        "kind": "dataset",
        "shape": list(ds.shape) if ds.shape is not None else None,
        "chunks": list(ds.chunks) if ds.chunks else None,
        "filters": filters,
        "type": _h5_type(ds.id.get_type()),
        "attrs": _attrs(ds),
    }


# ---------------------------------------------------------------------------
# Public API — walk
# ---------------------------------------------------------------------------


def walk(path: Path) -> dict[str, dict[str, Any]]:
    """Walk *path* and return every HDF5 object keyed by its absolute HDF5 path.

    Groups and datasets record attribute names with type descriptions.
    Datasets additionally record dtype description, rank, shape, chunks and
    filter names.  Soft/external/hard links are recorded with their kind and
    target.  The file is opened read-only with ``locking=False``.
    """
    objects: dict[str, dict[str, Any]] = {}
    seen: dict[tuple[int, int], str] = {}

    with h5py.File(path, "r", locking=False) as f:

        def visit(group: Any, gpath: str) -> None:
            objects[gpath] = {"kind": "group", "attrs": _attrs(group)}
            for name in group.keys():
                cpath = f"{gpath.rstrip('/')}/{name}"
                link = group.get(name, getlink=True)
                if isinstance(link, h5py.SoftLink):
                    objects[cpath] = {"kind": "softlink", "target": link.path}
                    continue
                if isinstance(link, h5py.ExternalLink):
                    objects[cpath] = {
                        "kind": "extlink",
                        "file": link.filename,
                        "target": link.path,
                    }
                    continue
                obj = group[name]
                info = h5py.h5o.get_info(obj.id)
                key = (info.fileno, info.addr)
                if key in seen:
                    objects[cpath] = {"kind": "hardlink", "of": seen[key]}
                    continue
                seen[key] = cpath
                if isinstance(obj, h5py.Group):
                    visit(obj, cpath)
                else:
                    objects[cpath] = _dataset_info(obj)

        visit(f, "/")

    return objects


# ---------------------------------------------------------------------------
# Public API — fingerprint
# ---------------------------------------------------------------------------


def fingerprint(objects: dict[str, dict[str, Any]]) -> str:
    """Return a 16-character SHA-256 hex digest over the *structure* of *objects*.

    Shape, chunk sizes and attribute/dataset values are intentionally excluded
    so that files of the same schema from different projects compare equal.
    """
    items: list[Any] = []
    for path, info in sorted(objects.items()):
        sig: dict[str, Any] = {"p": path, "k": info["kind"]}
        if info["kind"] == "dataset":
            sig["t"] = info["type"]
            sig["r"] = len(info["shape"] or [])
            sig["f"] = [x["name"] for x in info["filters"]]
        if "attrs" in info:
            sig["a"] = sorted(
                [n, json.dumps(a.get("type"), sort_keys=True)]
                for n, a in info["attrs"].items()
            )
        if info["kind"] in ("softlink", "extlink", "hardlink"):
            sig["x"] = info.get("target") or info.get("of")
        items.append(sig)
    raw = json.dumps(items, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Public API — SchemaDiff / diff
# ---------------------------------------------------------------------------


@dataclass
class SchemaDiff:
    """Structural differences between two HDF5 object maps."""

    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    kind_changed: list[str] = field(default_factory=list)
    type_changed: list[str] = field(default_factory=list)
    rank_changed: list[str] = field(default_factory=list)
    attrs_added: list[str] = field(default_factory=list)
    attrs_removed: list[str] = field(default_factory=list)
    attr_type_changed: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        """Return ``True`` when no differences were recorded."""
        return not any(
            [
                self.added,
                self.removed,
                self.kind_changed,
                self.type_changed,
                self.rank_changed,
                self.attrs_added,
                self.attrs_removed,
                self.attr_type_changed,
            ]
        )

    def render(self) -> str:
        """Return a human-readable multi-line description of all differences."""
        lines: list[str] = []
        for p in self.added:
            lines.append(f"added       {p}")
        for p in self.removed:
            lines.append(f"removed     {p}")
        for p in self.kind_changed:
            lines.append(f"kind        {p}")
        for p in self.type_changed:
            lines.append(f"type        {p}")
        for p in self.rank_changed:
            lines.append(f"rank        {p}")
        for p in self.attrs_added:
            lines.append(f"attr+       {p}")
        for p in self.attrs_removed:
            lines.append(f"attr-       {p}")
        for p in self.attr_type_changed:
            lines.append(f"attr_type   {p}")
        return "\n".join(lines)


def diff(
    expected: dict[str, dict[str, Any]], actual: dict[str, dict[str, Any]]
) -> SchemaDiff:
    """Return a :class:`SchemaDiff` comparing *expected* to *actual* (structural only)."""
    d = SchemaDiff()
    d.added = sorted(set(actual) - set(expected))
    d.removed = sorted(set(expected) - set(actual))

    for path in sorted(set(expected) & set(actual)):
        x, y = expected[path], actual[path]
        if x["kind"] != y["kind"]:
            d.kind_changed.append(path)
            continue
        if x["kind"] == "dataset":
            type_diff = x["type"] != y["type"]
            filter_diff = [f["name"] for f in x["filters"]] != [
                f["name"] for f in y["filters"]
            ]
            if type_diff or filter_diff:
                d.type_changed.append(path)
            if len(x["shape"] or []) != len(y["shape"] or []):
                d.rank_changed.append(path)
        xa: dict[str, Any] = x.get("attrs") or {}
        ya: dict[str, Any] = y.get("attrs") or {}
        d.attrs_added += [f"{path}@{n}" for n in sorted(set(ya) - set(xa))]
        d.attrs_removed += [f"{path}@{n}" for n in sorted(set(xa) - set(ya))]
        for n in sorted(set(xa) & set(ya)):
            if xa[n].get("type") != ya[n].get("type"):
                d.attr_type_changed.append(f"{path}@{n}")

    return d


# ---------------------------------------------------------------------------
# Public API — SchemaMismatch / guard
# ---------------------------------------------------------------------------


class SchemaMismatch(RuntimeError):
    """Raised by :func:`guard` when the file's schema differs from the baseline.

    Attributes
    ----------
    diff:
        The :class:`SchemaDiff` that describes what changed (may be empty when
        only the fingerprint string was provided and no object map was given).
    """

    def __init__(self, message: str, schema_diff: SchemaDiff) -> None:
        super().__init__(message)
        self.diff: SchemaDiff = schema_diff


def guard(
    path: Path,
    expected_fingerprint: str,
    expected_objects: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Verify that *path* matches the pinned schema; raise :class:`SchemaMismatch` if not.

    If *expected_objects* is given the exception will carry a full
    :class:`SchemaDiff`; otherwise the message names both fingerprints.
    """
    actual_objects = walk(path)
    actual_fp = fingerprint(actual_objects)
    if actual_fp == expected_fingerprint:
        return

    if expected_objects is not None:
        d = diff(expected_objects, actual_objects)
        msg = f"Schema mismatch for {path}:\n{d.render()}"
        raise SchemaMismatch(msg, d)
    else:
        d = SchemaDiff()
        msg = (
            f"Schema mismatch for {path}: "
            f"expected fingerprint {expected_fingerprint!r}, "
            f"got {actual_fp!r}"
        )
        raise SchemaMismatch(msg, d)


# ---------------------------------------------------------------------------
# Public API — baseline persistence
# ---------------------------------------------------------------------------


def save_baseline(path: Path, out: Path) -> str:
    """Walk *path*, write ``{"fingerprint", "objects"}`` JSON to *out*, return fingerprint."""
    objects = walk(path)
    fp = fingerprint(objects)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"fingerprint": fp, "objects": objects}, indent=2),
        encoding="utf-8",
    )
    return fp


def load_baseline(p: Path) -> tuple[str, dict[str, dict[str, Any]]]:
    """Load a baseline written by :func:`save_baseline` and return ``(fingerprint, objects)``."""
    data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    return data["fingerprint"], data["objects"]

"""A runnable iRIC project (.ipro) from a template project plus a grid, grid attributes and
calculation conditions.

The template is a project saved by iRIC itself for the target solver (File > Save right after
choosing the solver is enough): it carries the solver name and version and every calculation
condition at its default. Only iRIC-written templates are cloned; nothing here invents a project
from nothing. `write_project` copies the template, replaces the grid zone in its CGNS file and
sets the named scalar conditions; every other archive member is copied unchanged.

CGNS-in-HDF5 layout written here (as iRIC 4 writes it; read back from its own files):
- every node is a group created with link creation order tracked and indexed, with attributes
  `name`, `label`, `type` (fixed-width NULLTERM strings of length + 1, shape (1,)) and `flags`
  (int32 [1]); node data is the contiguous dataset `" data"` in that group.
- `iRIC/iRICZone` (`Zone_t`, I4) data [[ni, nj], [ni-1, nj-1], [0, 0]]; `ZoneType` "Structured".
- `GridCoordinates/CoordinateX|Y` (R8) shaped (nj, ni).
- `GridConditions/<name>/Value` (R8 or I4) flat, i fastest: ni*nj values on nodes,
  (ni-1)*(nj-1) on cells.
- `CalculationConditions/<name>/Value` one value (R8 or I4).
- a table (functional) condition is `CalculationConditions/<name>` with one R8 array per column,
  named as the definition names its parameter and values (as iRIC's own library writes them).
Boundary-condition groups (`ZoneBC`) are not written.
"""

from __future__ import annotations

import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import h5py
import h5py.h5a
import h5py.h5s
import h5py.h5t
import numpy as np
from numpy.typing import ArrayLike, NDArray

from flowfield2d.export.iric import Package

BASE = "iRIC"
ZONE = "iRICZone"
DATA = " data"
_TYPES: dict[str, np.dtype[Any]] = {"R8": np.dtype("<f8"), "I4": np.dtype("<i4")}


@dataclass(frozen=True)
class GridAttribute:
    """One grid attribute of a solver definition. `default` is None when the definition gives
    no number (e.g. "max"): the caller must supply the values."""

    name: str
    position: str            # "node" or "cell"
    integer: bool
    default: float | None


def grid_attributes_of(definition: Path) -> list[GridAttribute]:
    """Real and integer node/cell grid attributes declared in a solver's `definition.xml`.
    Functional and complex attributes and edge positions are left out."""
    root = ET.parse(definition).getroot()
    out: list[GridAttribute] = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "GridRelatedCondition":
            continue
        for item in el:
            if item.tag.rsplit("}", 1)[-1] != "Item":
                continue
            d = next((c for c in item if c.tag.rsplit("}", 1)[-1] == "Definition"), None)
            if d is None or d.get("valueType") not in ("real", "integer"):
                continue
            if d.get("position") not in ("node", "cell"):
                continue
            try:
                default: float | None = float(d.get("default", ""))
            except ValueError:
                default = None
            out.append(GridAttribute(str(item.get("name")), str(d.get("position")),
                                     d.get("valueType") == "integer", default))
    return out


def conditions_of(definition: Path) -> dict[str, float | int]:
    """Default of every scalar real or integer calculation condition in a solver's
    `definition.xml` (what a project saved by the GUI holds before anything is changed).
    Table, text and file conditions are left out."""
    root = ET.parse(definition).getroot()
    out: dict[str, float | int] = {}
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "CalculationCondition":
            continue
        for item in el.iter():
            if item.tag.rsplit("}", 1)[-1] != "Item":
                continue
            d = next((c for c in item if c.tag.rsplit("}", 1)[-1] == "Definition"), None)
            if d is None or d.get("conditionType", "constant") != "constant":
                continue
            kind, name = d.get("valueType"), item.get("name")
            if name is None or kind not in ("real", "integer"):
                continue
            try:
                out[name] = int(d.get("default", "")) if kind == "integer" else float(
                    d.get("default", ""))
            except ValueError:
                continue
    return out


def _fixed_attr(obj: Any, name: str, text: str) -> None:
    raw = text.encode("ascii")
    tid = h5py.h5t.C_S1.copy()
    tid.set_size(len(raw) + 1)
    tid.set_strpad(h5py.h5t.STR_NULLTERM)
    aid = h5py.h5a.create(obj.id, name.encode("ascii"), tid, h5py.h5s.create_simple((1,)))
    aid.write(np.array([raw], dtype=f"S{len(raw) + 1}"), mtype=tid)


def _node(parent: Any, name: str, label: str, typ: str, data: NDArray[Any] | None = None) -> Any:
    """Create one CGNS node under `parent`."""
    g = parent.create_group(name, track_order=True)
    g.attrs.create("flags", np.array([1], dtype="<i4"))
    _fixed_attr(g, "label", label)
    _fixed_attr(g, "name", name)
    _fixed_attr(g, "type", typ)
    if data is not None:
        g.create_dataset(DATA, data=data)
    return g


def _text(s: str) -> NDArray[np.int8]:
    return np.frombuffer(s.encode("ascii"), dtype=np.int8).copy()


def write_zone(cgns: Path, xy: ArrayLike, node_attrs: Mapping[str, ArrayLike],
               cell_attrs: Mapping[str, ArrayLike] | None = None,
               integer: frozenset[str] = frozenset()) -> None:
    """Replace the grid zone of an iRIC CGNS file. `xy` is (ni, nj, 2); node attributes are
    (ni, nj), cell attributes (ni-1, nj-1); names in `integer` are stored as I4."""
    a = np.asarray(xy, dtype=np.float64)
    if a.ndim != 3 or a.shape[2] != 2 or a.shape[0] < 2 or a.shape[1] < 2:
        raise ValueError(f"xy must be (ni, nj, 2) with ni, nj >= 2 (got {a.shape})")
    ni, nj = a.shape[:2]
    if not np.isfinite(a).all():
        raise ValueError("xy has non-finite values")
    values: dict[str, NDArray[Any]] = {}
    for kind, attrs, shape in (("node", node_attrs, (ni, nj)),
                               ("cell", cell_attrs or {}, (ni - 1, nj - 1))):
        for k, v in attrs.items():
            arr = np.asarray(v, dtype=np.float64)
            if arr.shape != shape:
                raise ValueError(f"{kind} attribute {k!r} has shape {arr.shape}, expected {shape}")
            if not np.isfinite(arr).all():
                raise ValueError(f"{kind} attribute {k!r} has non-finite values")
            if k in values:
                raise ValueError(f"attribute {k!r} given as both node and cell")
            values[k] = arr.T.ravel().astype(_TYPES["I4" if k in integer else "R8"])
    with h5py.File(cgns, "r+") as f:
        if BASE not in f:
            raise ValueError(f"{cgns}: no {BASE!r} base; not an iRIC CGNS file")
        base = f[BASE]
        if ZONE in base:
            del base[ZONE]
        size = np.array([[ni, nj], [ni - 1, nj - 1], [0, 0]], dtype="<i4")
        zone = _node(base, ZONE, "Zone_t", "I4", size)
        _node(zone, "ZoneType", "ZoneType_t", "C1", _text("Structured"))
        gc = _node(zone, "GridCoordinates", "GridCoordinates_t", "MT")
        _node(gc, "CoordinateX", "DataArray_t", "R8", np.ascontiguousarray(a[..., 0].T))
        _node(gc, "CoordinateY", "DataArray_t", "R8", np.ascontiguousarray(a[..., 1].T))
        cond = _node(zone, "GridConditions", "UserDefinedData_t", "MT")
        for k, flat in values.items():
            item = _node(cond, k, "UserDefinedData_t", "MT")
            _node(item, "Value", "DataArray_t", "I4" if k in integer else "R8", flat)
        _node(zone, "ZoneIterativeData", "ZoneIterativeData_t", "MT")
        _node(zone, "ZoneBC", "ZoneBC_t", "MT")


def set_conditions(cgns: Path, conditions: Mapping[str, float | int], *,
                   create: bool = False) -> None:
    """Set scalar calculation conditions, keeping each existing one's type. A condition the
    file lacks is a KeyError (naming them all) unless `create`, which adds it as I4 for an int
    value and R8 for a float. ValueError for a non-integer value given to an integer condition
    or for a condition that is not one number."""
    with h5py.File(cgns, "r+") as f:
        cc = f[f"{BASE}/CalculationConditions"]
        missing = sorted(k for k in conditions if k not in cc or "Value" not in cc[k])
        if missing and not create:
            raise KeyError(f"calculation conditions not in the template: {', '.join(missing)}")
        for k, v in conditions.items():
            if k in missing:
                if k in cc:
                    del cc[k]
                is_int = isinstance(v, (int, np.integer)) and not isinstance(v, bool)
                typ = "I4" if is_int else "R8"
                _node(_node(cc, k, "UserDefinedData_t", "MT"), "Value", "DataArray_t", typ,
                      np.array([v], dtype=_TYPES[typ]))
                continue
            node = cc[k]["Value"]
            old = node[DATA]
            if old.shape != (1,) or old.dtype.kind not in "if":
                raise ValueError(f"condition {k!r} is not one number ({old.dtype}, {old.shape})")
            if old.dtype.kind == "i" and float(v) != int(v):
                raise ValueError(f"condition {k!r} is an integer; got {v!r}")
            new = np.array([v], dtype=old.dtype)
            del node[DATA]                       # recreate, never resize
            node.create_dataset(DATA, data=new)


def set_functions(cgns: Path, functions: Mapping[str, Mapping[str, ArrayLike]]) -> None:
    """Write table conditions: name -> {column name -> values}, columns of equal length named
    as the solver definition names the parameter and values. An existing table is replaced."""
    with h5py.File(cgns, "r+") as f:
        cc = f[f"{BASE}/CalculationConditions"]
        for name, columns in functions.items():
            arrays = {k: np.asarray(v, dtype=np.float64).ravel() for k, v in columns.items()}
            if not arrays or len({len(a) for a in arrays.values()}) != 1:
                raise ValueError(f"table {name!r} needs columns of one length")
            if not all(np.isfinite(a).all() for a in arrays.values()):
                raise ValueError(f"table {name!r} has non-finite values")
            if name in cc:
                del cc[name]
            node = _node(cc, name, "UserDefinedData_t", "MT")
            for col, a in arrays.items():
                _node(node, col, "DataArray_t", "R8", a)


def read_solution(cgns: Path, step: int = -1) -> dict[str, NDArray[np.float64]]:
    """Grid coordinates and one solution step of a solved iRIC CGNS file, as (ni, nj) arrays
    keyed by the solver's field names, plus `x` and `y`. `step` counts solutions in the order
    written (negative from the end). Fields not on the grid nodes are left out."""
    with h5py.File(cgns, "r") as f:
        zone = f[f"{BASE}/{ZONE}"]
        x = np.asarray(zone[f"GridCoordinates/CoordinateX/{DATA}"][()], dtype=np.float64).T
        y = np.asarray(zone[f"GridCoordinates/CoordinateY/{DATA}"][()], dtype=np.float64).T
        names = sorted((k for k in zone if k.startswith("FlowSolution") and k[12:].isdigit()),
                       key=lambda k: int(k[12:]))
        if not names:
            raise ValueError(f"{cgns}: no solution in the file")
        sol = zone[names[step]]
        out: dict[str, NDArray[np.float64]] = {"x": x, "y": y}
        for k in sol:
            node = sol[k]
            if isinstance(node, h5py.Group) and DATA in node:
                a = np.asarray(node[DATA][()])
                if a.dtype.kind in "if" and a.T.shape == x.shape:
                    out[k] = a.T.astype(np.float64)
    return out


def fastmech_conditions(pkg: Package, *, roughness_by_node: bool) -> dict[str, float | int]:
    """FaSTMECH conditions for one steady state: constant discharge, constant downstream stage,
    initial water surface from the upstream stage, and node roughness when the grid carries it."""
    need = {"discharge": pkg.discharge, "downstream stage": pkg.stage_downstream,
            "upstream stage": pkg.stage_upstream}
    lacking = [k for k, v in need.items() if v is None]
    if lacking:
        raise ValueError(f"package has no {', '.join(lacking)}; a flow state is required")
    assert pkg.discharge is not None and pkg.stage_downstream is not None
    assert pkg.stage_upstream is not None
    return {
        "FM_HydAttVarDischType": 0, "FM_HydAttQ": float(pkg.discharge),
        "FM_HydAttVarStgType": 0, "FM_HydAttWS": float(pkg.stage_downstream),
        "FM_HydAttWSType": 0, "FM_HydAttWS2": float(pkg.stage_upstream),
        "FM_HydAttCDType": 1 if roughness_by_node else 0,
    }


def nays2dh_conditions(pkg: Package, duration_s: float
                       ) -> tuple[dict[str, float | int], dict[str, dict[str, list[float]]]]:
    """Nays2DH conditions for one steady state held for `duration_s`: downstream water surface
    from the time series, times in seconds, and the series itself (constant discharge and
    downstream stage). Returns (scalars, tables). Time step, output interval and the initial
    surface stay as the template has them."""
    if pkg.discharge is None or pkg.stage_downstream is None:
        raise ValueError("package has no discharge or downstream stage; a flow state is required")
    if not duration_s > 0:
        raise ValueError("duration_s must be positive")
    q, h = float(pkg.discharge), float(pkg.stage_downstream)
    return ({"j_wl": 2, "i_sec_hour": 1},
            {"discharge_waterlevel": {"time": [0.0, float(duration_s)], "discharge": [q, q],
                                      "water_level": [h, h]}})


def _cgns_member(names: list[str], project_xml: bytes) -> tuple[str, str]:
    root = ET.fromstring(project_xml)
    solver = str(root.get("solverName", ""))
    files = root.find("CgnsFileList")
    current = files.get("current") if files is not None else None
    member = f"{current}.cgn" if current else ""
    if member not in names:
        raise ValueError(f"template has no CGNS file for the current case ({member or 'none'})")
    return member, solver


def write_project(template: Path, out: Path, xy: ArrayLike,
                  node_attrs: Mapping[str, ArrayLike],
                  cell_attrs: Mapping[str, ArrayLike] | None = None,
                  conditions: Mapping[str, float | int] | None = None, *,
                  functions: Mapping[str, Mapping[str, ArrayLike]] | None = None,
                  definition: Path | None = None, solver: str | None = None) -> Path:
    """Clone `template` (.ipro) to `out` with the grid, grid attributes and conditions set.

    With `definition` (the solver's definition.xml) every declared real/integer node or cell
    attribute is written: ones not supplied take the definition's default, an attribute with no
    numeric default must be supplied, and a supplied name the definition lacks is an error.
    Without it only the supplied attributes are written, as reals. `functions` are table
    conditions (`set_functions`). `solver`, when given, must match the template's solver name.
    A condition the template lacks is an error unless the definition declares it as a scalar:
    the GUI leaves out conditions whose option was never switched on, so those are added."""
    template, out = Path(template), Path(out)
    if out.resolve() == template.resolve():
        raise ValueError("out must differ from the template")
    a = np.asarray(xy, dtype=np.float64)
    node = {k: np.asarray(v, dtype=np.float64) for k, v in node_attrs.items()}
    cell = {k: np.asarray(v, dtype=np.float64) for k, v in (cell_attrs or {}).items()}
    integer: set[str] = set()
    if definition is not None:
        declared = {g.name: g for g in grid_attributes_of(definition)}
        unknown = sorted((set(node) | set(cell)) - set(declared))
        if unknown:
            raise ValueError(f"attributes not in the solver definition: {', '.join(unknown)}")
        for g in declared.values():
            mine, other = (node, cell) if g.position == "node" else (cell, node)
            if g.name in other:
                raise ValueError(f"attribute {g.name!r} is a {g.position} attribute")
            if g.name not in mine:
                if g.default is None:
                    raise ValueError(f"attribute {g.name!r} has no default; supply it")
                ni, nj = a.shape[:2]
                shape = (ni, nj) if g.position == "node" else (ni - 1, nj - 1)
                mine[g.name] = np.full(shape, g.default)
            if g.integer:
                integer.add(g.name)
    with zipfile.ZipFile(template) as zin:
        names = zin.namelist()
        member, found = _cgns_member(names, zin.read("project.xml"))
        if solver is not None and solver != found:
            raise ValueError(f"template is for solver {found!r}, not {solver!r}")
        out.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(suffix=".cgn", dir=out.parent)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(zin.read(member))
            write_zone(tmp, a, node, cell, frozenset(integer))
            if conditions:
                known = conditions_of(definition) if definition is not None else {}
                typed: dict[str, float | int] = {
                    k: (int(v) if isinstance(known.get(k), int) and float(v) == int(v)
                        else float(v) if k in known and not isinstance(known[k], int) else v)
                    for k, v in conditions.items()}
                declared_only = {k: v for k, v in typed.items() if k in known}
                others = {k: v for k, v in typed.items() if k not in known}
                set_conditions(tmp, declared_only, create=True)
                set_conditions(tmp, others)
            if functions:
                set_functions(tmp, functions)
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
                for info in zin.infolist():
                    if info.filename == member:
                        zout.write(tmp, member)
                    else:
                        zout.writestr(info, zin.read(info.filename))
        finally:
            tmp.unlink(missing_ok=True)
    return out

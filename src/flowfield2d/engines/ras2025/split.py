"""Derive a subdomain from a GUI-authored full-domain template, headlessly (ADR-0001 addendum).

The template's conceptual model (probe step D) is a 2D-area `Polygon`, a closed perimeter arc in
`Mesh Topology` (`Nodes` + `Arc Internal Points`), a region `Control Points` entry, and BC lines in
the BC layer (`BC Lines/Polyline` with per-line `Count`/`Start` attrs). A subdomain is the template
clipped to `keep`; named BC lines are moved onto the cut. The mesh must then be regenerated with
`ras geometry generate-mesh`. Works on a cloned project (`templates.clone_project`), never the
template itself.
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
from shapely.geometry import LineString, MultiPolygon, Polygon

from flowfield2d.engines.ras2025.bc import bc_lines
from flowfield2d.engines.ras2025.h5edit import recreate_dataset

POLY = "/Geometry/2D Flow Areas/Polygon"
TOPO = "/Geometry/Mesh Topology"
BC_POLY = "/Boundary Conditions/BC Lines/Polyline"


def _one(folder: Path) -> Path:
    files = sorted(folder.glob("*.h5"))
    if len(files) != 1:
        raise ValueError(f"expected one layer in {folder}, found {len(files)}")
    return files[0]


def _set_count(ds: h5py.Dataset, counts: list[int], starts: list[int]) -> None:
    ds.attrs.modify("Count", np.array(counts, dtype=ds.attrs["Count"].dtype))
    ds.attrs.modify("Start", np.array(starts, dtype=ds.attrs["Start"].dtype))


def bc_polylines(bc_file: Path) -> dict[str, LineString]:
    lines = bc_lines(bc_file)
    with h5py.File(bc_file, "r", locking=False) as f:
        pl = f[BC_POLY][:]
        cnt, st = f[BC_POLY].attrs["Count"], f[BC_POLY].attrs["Start"]
    return {ln.name: LineString(pl[int(st[ln.index]):int(st[ln.index]) + int(cnt[ln.index])])
            for ln in lines}


def split_geometry(project: Path, keep: Polygon, cut_bcs: dict[str, LineString]) -> Polygon:
    """Clip the project's 2D area to `keep` and move each named BC line to its cut line.

    Returns the subdomain polygon. The largest piece is kept if the clip splits the area.
    """
    geom = _one(Path(project) / "Geometries")
    bc = _one(Path(project) / "Boundary Conditions")
    names = {ln.name: ln.index for ln in bc_lines(bc)}
    missing = sorted(set(cut_bcs) - set(names))
    if missing:
        raise ValueError(f"no BC line named {missing}")
    with h5py.File(geom, "r+", locking=False) as f:
        piece = Polygon(f[POLY][:]).intersection(keep)
        if piece.is_empty:
            raise ValueError("clip polygon leaves the 2D area empty")
        sub = max(piece.geoms, key=lambda g: g.area) if isinstance(piece, MultiPolygon) else piece
        if not isinstance(sub, Polygon):
            raise ValueError(f"clip produced {sub.geom_type}, not a polygon")
        ring = np.asarray(sub.exterior.coords)[:-1]
        recreate_dataset(f[POLY].parent, "Polygon", ring)
        _set_count(f[POLY], [len(ring)], [0])
        topo = f[TOPO]
        recreate_dataset(topo, "Nodes", ring[:1].copy())
        recreate_dataset(topo, "Arc Internal Points", ring[1:].copy())
        _set_count(topo["Arc Internal Points"], [len(ring) - 1], [0])
        cp = sub.representative_point()
        recreate_dataset(topo, "Control Points", np.array([[cp.x, cp.y]]))
    if cut_bcs:
        current = bc_polylines(bc)
        order = sorted(names, key=lambda n: names[n])
        parts = [np.asarray((cut_bcs.get(n) or current[n]).coords, dtype="f8") for n in order]
        counts = [len(x) for x in parts]
        starts = [int(s) for s in np.cumsum([0, *counts[:-1]])]
        with h5py.File(bc, "r+", locking=False) as f:
            recreate_dataset(f[BC_POLY].parent, "Polyline", np.concatenate(parts))
            _set_count(f[BC_POLY], counts, starts)
    return sub

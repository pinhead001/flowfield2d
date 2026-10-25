"""Derive a subdomain from a full-domain template (synthetic geometry + BC files)."""

from pathlib import Path

import h5py
import numpy as np
import pytest
from shapely.geometry import LineString, Point, Polygon, box

from flowfield2d.engines.ras2025.split import bc_polylines, split_geometry

from .test_ras_bc_writer import LINE_DT


def _project(tmp_path: Path) -> Path:
    p = tmp_path / "proj"
    (p / "Geometries").mkdir(parents=True)
    (p / "Boundary Conditions").mkdir()
    ring = np.array([[0, 0], [100, 0], [100, 1000], [0, 1000]], dtype="f8")
    with h5py.File(p / "Geometries" / "g.h5", "w") as f:
        d = f.create_dataset("/Geometry/2D Flow Areas/Polygon", data=ring)
        d.attrs["Count"] = np.array([4], dtype="i4")
        d.attrs["Start"] = np.array([0], dtype="i4")
        t = f.create_group("/Geometry/Mesh Topology")
        t.create_dataset("Nodes", data=ring[:1])
        a = t.create_dataset("Arc Internal Points", data=ring[1:])
        a.attrs["Count"] = np.array([3], dtype="i4")
        a.attrs["Start"] = np.array([0], dtype="i4")
        t.create_dataset("Control Points", data=np.array([[50.0, 500.0]]))
    with h5py.File(p / "Boundary Conditions" / "b.h5", "w") as f:
        f.create_dataset("/Boundary Conditions/BC Lines/Attributes", data=np.array(
            [(b"Outlet", 1, 0, 1), (b"Inflow", 1, 1, 1)], dtype=LINE_DT))
        pl = f.create_dataset("/Boundary Conditions/BC Lines/Polyline",
                              data=np.array([[0, 1], [100, 1], [0, 999], [100, 999]], dtype="f8"))
        pl.attrs["Count"] = np.array([2, 2], dtype="i4")
        pl.attrs["Start"] = np.array([0, 2], dtype="i4")
    return p


def test_split_rewrites_outline_topology_and_cut_bc(tmp_path: Path) -> None:
    p = _project(tmp_path)
    keep = box(-10, 400, 110, 1010)                         # upper part
    cut = LineString([(0, 401), (100, 401)])
    sub = split_geometry(p, keep, {"Outlet": cut})
    assert isinstance(sub, Polygon) and sub.area == pytest.approx(100 * 600)
    with h5py.File(p / "Geometries" / "g.h5", "r") as f:
        ring = f["/Geometry/2D Flow Areas/Polygon"][:]
        assert Polygon(ring).area == pytest.approx(100 * 600)
        assert f["/Geometry/2D Flow Areas/Polygon"].attrs["Count"].tolist() == [len(ring)]
        t = f["/Geometry/Mesh Topology"]
        assert t["Nodes"][0].tolist() == ring[0].tolist()
        assert t["Arc Internal Points"].attrs["Count"].tolist() == [len(ring) - 1]
        cp = t["Control Points"][0]
        assert sub.contains(Point(*cp))
    lines = bc_polylines(p / "Boundary Conditions" / "b.h5")
    assert lines["Outlet"].coords[:] == [(0.0, 401.0), (100.0, 401.0)]
    assert lines["Inflow"].coords[:] == [(0.0, 999.0), (100.0, 999.0)]   # untouched


def test_split_handles_cut_lines_with_more_points(tmp_path: Path) -> None:
    p = _project(tmp_path)
    cut = LineString([(0, 401), (50, 402), (100, 401)])
    split_geometry(p, box(-10, 400, 110, 1010), {"Outlet": cut})
    with h5py.File(p / "Boundary Conditions" / "b.h5", "r") as f:
        pl = f["/Boundary Conditions/BC Lines/Polyline"]
        assert pl.attrs["Count"].tolist() == [3, 2] and pl.attrs["Start"].tolist() == [0, 3]
    assert len(bc_polylines(p / "Boundary Conditions" / "b.h5")["Outlet"].coords) == 3


def test_split_rejects_bad_requests(tmp_path: Path) -> None:
    p = _project(tmp_path)
    with pytest.raises(ValueError, match="no BC line"):
        split_geometry(p, box(-10, 400, 110, 1010), {"Nope": LineString([(0, 401), (1, 401)])})
    with pytest.raises(ValueError, match="empty"):
        split_geometry(p, box(500, 500, 600, 600), {})

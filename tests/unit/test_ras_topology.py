"""Mesh topology writer: arcs (breaklines, patch edges) and regions (control points) appended to
a geometry's /Geometry/Mesh Topology, sharing nodes between arcs. Layout and compound types as
written by the pinned build (probe 2026-10-25): an outline is one closed arc on node 0."""

from pathlib import Path

import h5py
import numpy as np
import pytest
from shapely.geometry import LineString, Point

from flowfield2d.engines.ras2025.topology import Arc, PatchType, Region, add_topology

TOPO = "/Geometry/Mesh Topology"
ARC_DT = np.dtype({
    "names": ["LaplaceBC", "Count", "Bias", "SizeFunction", "ConstantSize", "ConstrainStretching",
              "DistanceStraightLine", "AreaWeight", "DiscretizeMagnetism", "FollowExactly",
              "ArcAngleLeft", "ArcAngleRight"],
    "formats": ["<i4", "<i4", "<f4", "<i4", "<f4", "<i4", "u1", "<f4", "<f4", "u1", "<f4", "<f4"],
    "offsets": [0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44], "itemsize": 48})
CP_DT = np.dtype([("SizeFunction", "<i4"), ("PatchType", "<i4"), ("ConstantSize", "<f4"),
                  ("Recipe", "S9"), ("StretchRate", "<f4"), ("Multipoint", "<f4"),
                  ("TINResolution", "<f4"), ("SizeTolerance", "<f4"),
                  ("SecondaryConstantSize", "<f4"), ("RotationDegrees", "<f4")])


def _geom(path: Path) -> Path:
    """A 100 x 50 outline: node 0 at (0, 0), closed arc through the other three corners."""
    with h5py.File(path, "w") as f:
        t = f.create_group(TOPO)
        t.create_dataset("Nodes", data=np.array([[0.0, 0.0]]))
        t.create_dataset("Arc Connectivity", data=np.array([[0, 0]], dtype=np.int32))
        aip = t.create_dataset("Arc Internal Points",
                               data=np.array([[100.0, 0.0], [100.0, 50.0], [0.0, 50.0]]))
        aip.attrs.create("Count", np.array([3], dtype=np.int32))
        aip.attrs.create("Start", np.array([0], dtype=np.int32))
        t.create_dataset("Arc Attributes",
                         data=np.array([(0, 8, 1.0, 0, np.nan, 0, 1, 0.0, 0.1, 1, 0.0, 0.0)],
                                       dtype=ARC_DT))
        t.create_dataset("Control Points", data=np.array([[50.0, 25.0]]))
        t.create_dataset("Control Point Attributes",
                         data=np.array([(0, 2, 30.0, b"Default()", np.nan, 1.0, 1.0, 1.0,
                                         np.nan, 0.0)], dtype=CP_DT))
    return path


def test_append_two_arcs_sharing_a_node(tmp_path: Path) -> None:
    g = _geom(tmp_path / "g.h5")
    add_topology(g, [Arc(LineString([(10, 10), (20, 15), (30, 10)]), cell_size=5.0),
                     Arc(LineString([(30, 10), (30, 40)]), follow_exactly=False)])
    with h5py.File(g, "r") as f:
        t = f[TOPO]
        assert t["Nodes"][()].tolist() == [[0, 0], [10, 10], [30, 10], [30, 40]]
        assert t["Arc Connectivity"][()].tolist() == [[0, 0], [1, 2], [2, 3]]
        assert t["Arc Connectivity"].dtype == np.int32
        assert t["Arc Internal Points"][()].tolist() == [[100, 0], [100, 50], [0, 50], [20, 15]]
        assert t["Arc Internal Points"].attrs["Count"].tolist() == [3, 1, 0]
        assert t["Arc Internal Points"].attrs["Start"].tolist() == [0, 3, 4]
        attrs = t["Arc Attributes"][()]
        assert attrs.dtype == ARC_DT and len(attrs) == 3
        assert attrs[1]["ConstantSize"] == 5.0 and attrs[1]["FollowExactly"] == 1
        assert np.isnan(attrs[2]["ConstantSize"]) and attrs[2]["FollowExactly"] == 0
        assert attrs[1]["Count"] == 8 and attrs[1]["DiscretizeMagnetism"] == pytest.approx(0.1)
        assert t["Control Points"][()].tolist() == [[50, 25]]          # no region given


def test_endpoints_snap_to_existing_nodes(tmp_path: Path) -> None:
    g = _geom(tmp_path / "g.h5")
    add_topology(g, [Arc(LineString([(0.0000004, 0.0), (40.0, 30.0)]))], snap_tol=1e-6)
    with h5py.File(g, "r") as f:
        assert f[TOPO]["Nodes"][()].tolist() == [[0, 0], [40, 30]]
        assert f[TOPO]["Arc Connectivity"][()].tolist()[-1] == [0, 1]


def test_region_appended_with_patch_type_and_size(tmp_path: Path) -> None:
    g = _geom(tmp_path / "g.h5")
    add_topology(g, [], [Region(Point(20.0, 12.0), PatchType.QUAD, 4.5)])
    with h5py.File(g, "r") as f:
        t = f[TOPO]
        assert t["Control Points"][()].tolist() == [[50, 25], [20, 12]]
        cpa = t["Control Point Attributes"][()]
        assert cpa.dtype == CP_DT and len(cpa) == 2
        assert cpa[1]["PatchType"] == 0 and cpa[1]["ConstantSize"] == 4.5
        assert cpa[1]["Recipe"] == b"Default()"                        # other fields copied
    assert (PatchType.QUAD, PatchType.TRIANGLE_PAVER, PatchType.CARTESIAN) == (0, 1, 2)


@pytest.mark.parametrize("arc", [
    Arc(LineString([(1, 1), (1, 1)])),                                 # zero length
    Arc(LineString([(1, 1), (5, 5), (1, 1)])),                         # closed
    Arc(LineString([(1, 1), (5, 5)]), cell_size=0.0),
])
def test_bad_arcs_rejected_and_nothing_written(tmp_path: Path, arc: Arc) -> None:
    g = _geom(tmp_path / "g.h5")
    good = Arc(LineString([(10, 10), (20, 20)]))
    with pytest.raises(ValueError):
        add_topology(g, [good, arc])
    with h5py.File(g, "r") as f:
        assert len(f[TOPO]["Nodes"]) == 1 and len(f[TOPO]["Arc Attributes"]) == 1


def test_bad_region_rejected(tmp_path: Path) -> None:
    g = _geom(tmp_path / "g.h5")
    with pytest.raises(ValueError):
        add_topology(g, [], [Region(Point(1, 1), PatchType.QUAD, -1.0)])

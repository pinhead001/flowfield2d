"""Refinement regions and channel land-cover classes applied while building a model."""

from pathlib import Path

import h5py
import numpy as np
from shapely.geometry import Point, Polygon

from flowfield2d.engines.ras2025.engine import add_refinements

from .test_ras_topology import TOPO, _geom


def _with_outline(path: Path) -> Path:
    g = _geom(path)
    with h5py.File(g, "r+") as f:
        f.create_dataset("/Geometry/2D Flow Areas/Polygon",
                         data=np.array([[0.0, 0.0], [100.0, 0.0], [100.0, 50.0], [0.0, 50.0]]))
    return g


def test_refinement_region_bounded_by_two_arcs_with_its_cell_size(tmp_path: Path) -> None:
    g = _with_outline(tmp_path / "g.h5")
    chan = Polygon([(10, 20), (90, 20), (90, 30), (10, 30)])
    add_refinements(g, [(chan, 4.0)])
    with h5py.File(g, "r") as f:
        t = f[TOPO]
        assert len(t["Arc Connectivity"]) == 1 + 2              # outline + two half rings
        assert len(t["Nodes"]) == 1 + 2                         # the two shared split nodes
        cps, cpa = t["Control Points"][()], t["Control Point Attributes"][()]
        assert len(cps) == 2 and cpa[1]["ConstantSize"] == 4.0
        assert cpa[1]["PatchType"] == cpa[0]["PatchType"]       # same patch type as the outline
        assert chan.contains(Point(cps[1]))
        assert not chan.contains(Point(cps[0]))      # outline point moved out (was 50, 25)
        assert Polygon([(0, 0), (100, 0), (100, 50), (0, 50)]).contains(Point(cps[0]))


def test_no_refinement_leaves_the_geometry_alone(tmp_path: Path) -> None:
    g = _with_outline(tmp_path / "g.h5")
    add_refinements(g, [])
    with h5py.File(g, "r") as f:
        assert len(f[TOPO]["Arc Connectivity"]) == 1
        assert f[TOPO]["Control Points"][0].tolist() == [50, 25]


def test_land_cover_class_goes_to_the_geometry_n_layers_classification(tmp_path: Path) -> None:
    from flowfield2d.engines.ras2025.engine import add_land_cover

    from .test_ras_landcover import POLYS, _class_layer, _n_layer

    proj = tmp_path / "proj"
    (proj / "Surface Layers").mkdir(parents=True)
    (proj / "p.ras").write_text(
        '<Project><GeometryAssociation Geometry="g1" Terrain="t1" N_Values="n1" /></Project>',
        encoding="utf-8")
    _class_layer(proj / "Surface Layers" / "class01.h5")
    n = _n_layer(proj / "Surface Layers" / "n1.h5")
    with h5py.File(n, "r+") as f:                       # the n layer names its classification
        del f["/NValues"].attrs["Classification Layer Name"]
        f["/NValues"].attrs["Classification Layer Name"] = np.bytes_(b"class01")
    chan = Polygon([(10, 20), (90, 20), (90, 30), (10, 30)])
    add_land_cover(proj, "g1", [chan], "Channel", 0.035)
    with h5py.File(proj / "Surface Layers" / "class01.h5", "r") as f:
        assert [r["Classification"] for r in f[POLYS]["Attributes"][()]] == [b"Channel"]
    with h5py.File(n, "r") as f:
        rows = {r["Class"]: round(float(r["N Value"]), 4) for r in f["/NValues/Table"][()]}
        assert rows[b"Channel"] == 0.035

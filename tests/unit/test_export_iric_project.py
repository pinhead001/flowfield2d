"""iRIC project writer: clone a template .ipro, replace the grid zone, set conditions."""

import zipfile
from pathlib import Path

import h5py
import h5py.h5a
import h5py.h5t
import numpy as np
import pytest
from numpy.typing import NDArray

from flowfield2d.export.iric import Package
from flowfield2d.export.iric_project import (
    _node,
    fastmech_conditions,
    grid_attributes_of,
    set_conditions,
    write_project,
    write_zone,
)

PROJECT_XML = (b'<?xml version="1.0" encoding="UTF-8"?>\n<iRICProject version="4" '
               b'solverName="fastmech" solverVersion="1"><CgnsFileList current="Case1">'
               b'<CgnsFileEntry filename="Case1" comment=""/></CgnsFileList></iRICProject>')
DEFINITION = """<?xml version="1.0"?>
<SolverDefinition xmlns="www.iric.net/SolverDefinition/1.0" name="fastmech">
  <GridRelatedCondition>
    <Item name="Elevation"><Definition position="node" valueType="real" default="max"/></Item>
    <Item name="roughness"><Definition position="node" valueType="real" default="0.003"/></Item>
    <Item name="Obstacle"><Definition position="cell" valueType="integer" default="0"/></Item>
    <Item name="mix"><Definition position="node" valueType="functional"/></Item>
  </GridRelatedCondition>
</SolverDefinition>"""
REALS = ("FM_HydAttQ", "FM_HydAttWS", "FM_HydAttWS2")
INTS = ("FM_HydAttVarDischType", "FM_HydAttVarStgType", "FM_HydAttWSType", "FM_HydAttCDType")


def _cgns(path: Path) -> Path:
    with h5py.File(path, "w", track_order=True) as f:
        base = _node(f, "iRIC", "CGNSBase_t", "I4", np.array([2, 2], dtype="<i4"))
        cc = _node(base, "CalculationConditions", "UserDefinedData_t", "MT")
        for name in REALS:
            _node(_node(cc, name, "UserDefinedData_t", "MT"), "Value", "DataArray_t", "R8",
                  np.array([100.0]))
        for name in INTS:
            _node(_node(cc, name, "UserDefinedData_t", "MT"), "Value", "DataArray_t", "I4",
                  np.array([0], dtype="<i4"))
        _node(base, "iRICZone", "Zone_t", "I4", np.zeros((3, 2), dtype="<i4"))   # stale grid
    return path


def _template(tmp_path: Path) -> Path:
    cg = _cgns(tmp_path / "Case1.cgn")
    p = tmp_path / "template.ipro"
    with zipfile.ZipFile(p, "w") as z:
        z.write(cg, "Case1.cgn")
        z.writestr("project.xml", PROJECT_XML)
        z.writestr("subwindows/preprocessor.xml", b"<PreProcessorWindow/>")
    return p


def _xy(ni: int = 4, nj: int = 3) -> NDArray[np.float64]:
    xy = np.zeros((ni, nj, 2))
    xy[..., 0] = (10.0 * np.arange(ni))[:, None]
    xy[..., 1] = (2.0 * np.arange(nj))[None, :]
    return xy


def test_zone_layout(tmp_path: Path) -> None:
    cg = _cgns(tmp_path / "c.cgn")
    xy = _xy()
    z = xy[..., 0] + 100 * xy[..., 1]
    write_zone(cg, xy, {"Elevation": z}, {"Obstacle": np.arange(6.0).reshape(3, 2)},
               frozenset({"Obstacle"}))
    with h5py.File(cg) as f:
        zone = f["iRIC/iRICZone"]
        assert zone[" data"][()].tolist() == [[4, 3], [3, 2], [0, 0]]
        assert zone["ZoneType/ data"][()].tobytes() == b"Structured"
        x = zone["GridCoordinates/CoordinateX/ data"][()]
        assert x.shape == (3, 4) and x[0].tolist() == [0.0, 10.0, 20.0, 30.0]   # (nj, ni)
        assert zone["GridCoordinates/CoordinateY/ data"][()][:, 0].tolist() == [0.0, 2.0, 4.0]
        e = zone["GridConditions/Elevation/Value/ data"][()]
        assert e.dtype == np.float64 and e[:5].tolist() == [0.0, 10.0, 20.0, 30.0, 200.0]
        o = zone["GridConditions/Obstacle/Value/ data"][()]
        assert o.dtype == np.int32 and o.tolist() == [0, 2, 4, 1, 3, 5]         # i fastest
        assert list(zone) == [" data", "ZoneType", "GridCoordinates", "GridConditions",
                              "ZoneIterativeData", "ZoneBC"]                    # creation order
        g = zone["GridCoordinates"]
        assert g.attrs["label"].tolist() == [b"GridCoordinates_t"]
        assert g.attrs["flags"].tolist() == [1] and g.attrs["type"].tolist() == [b"MT"]
        aid = h5py.h5a.open(g.id, b"name")
        assert aid.shape == (1,) and aid.get_type().get_size() == len("GridCoordinates") + 1
        assert aid.get_type().get_strpad() == h5py.h5t.STR_NULLTERM


def test_zone_refuses_bad_input(tmp_path: Path) -> None:
    cg = _cgns(tmp_path / "c.cgn")
    with pytest.raises(ValueError, match="shape"):
        write_zone(cg, _xy(), {"Elevation": np.zeros((3, 4))})
    bad = np.zeros((4, 3))
    bad[0, 0] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        write_zone(cg, _xy(), {"Elevation": bad})


def test_set_conditions_keeps_types(tmp_path: Path) -> None:
    cg = _cgns(tmp_path / "c.cgn")
    set_conditions(cg, {"FM_HydAttQ": 12, "FM_HydAttCDType": 1})
    with h5py.File(cg) as f:
        q = f["iRIC/CalculationConditions/FM_HydAttQ/Value/ data"]
        assert q.dtype == np.float64 and q[()].tolist() == [12.0]
        t = f["iRIC/CalculationConditions/FM_HydAttCDType/Value/ data"]
        assert t.dtype == np.int32 and t[()].tolist() == [1]
    with pytest.raises(KeyError, match="FM_Nope"):
        set_conditions(cg, {"FM_Nope": 1.0})
    with pytest.raises(ValueError, match="integer"):
        set_conditions(cg, {"FM_HydAttCDType": 0.5})


def test_definition_attributes(tmp_path: Path) -> None:
    d = tmp_path / "definition.xml"
    d.write_text(DEFINITION)
    got = {g.name: g for g in grid_attributes_of(d)}
    assert set(got) == {"Elevation", "roughness", "Obstacle"}
    assert got["Elevation"].default is None and got["roughness"].default == 0.003
    assert got["Obstacle"].integer and got["Obstacle"].position == "cell"


def test_write_project(tmp_path: Path) -> None:
    tmpl = _template(tmp_path)
    before = tmpl.read_bytes()
    d = tmp_path / "definition.xml"
    d.write_text(DEFINITION)
    xy = _xy()
    pkg = Package(xy=xy, chainage=np.arange(4.0), elevation=np.ones((4, 3)), discharge=7.5,
                  stage_downstream=1.2, stage_upstream=1.4)
    out = write_project(tmpl, tmp_path / "out" / "model.ipro", xy, {"Elevation": pkg.elevation},
                        conditions=fastmech_conditions(pkg, roughness_by_node=False),
                        definition=d, solver="fastmech")
    assert tmpl.read_bytes() == before                      # the template is never edited
    with zipfile.ZipFile(out) as z:
        assert sorted(z.namelist()) == ["Case1.cgn", "project.xml",
                                        "subwindows/preprocessor.xml"]
        assert z.read("project.xml") == PROJECT_XML
        z.extract("Case1.cgn", tmp_path / "x")
    assert not list((tmp_path / "out").glob("*.cgn"))       # no temporary file left behind
    with h5py.File(tmp_path / "x" / "Case1.cgn") as f:
        gc = f["iRIC/iRICZone/GridConditions"]
        assert set(gc) == {"Elevation", "roughness", "Obstacle"}
        rough = gc["roughness/Value/ data"][()]
        assert np.allclose(rough, 0.003) and len(rough) == 12
        obstacle = gc["Obstacle/Value/ data"][()]
        assert obstacle.dtype == np.int32 and len(obstacle) == 6
        cc = f["iRIC/CalculationConditions"]
        assert cc["FM_HydAttQ/Value/ data"][0] == 7.5
        assert cc["FM_HydAttWS/Value/ data"][0] == 1.2
        assert cc["FM_HydAttWS2/Value/ data"][0] == 1.4


def test_write_project_refusals(tmp_path: Path) -> None:
    tmpl = _template(tmp_path)
    d = tmp_path / "definition.xml"
    d.write_text(DEFINITION)
    xy, z = _xy(), np.ones((4, 3))
    with pytest.raises(ValueError, match="not 'nays2dh'"):
        write_project(tmpl, tmp_path / "o.ipro", xy, {"Elevation": z}, solver="nays2dh")
    with pytest.raises(ValueError, match="no default"):
        write_project(tmpl, tmp_path / "o.ipro", xy, {}, definition=d)
    with pytest.raises(ValueError, match="not in the solver definition"):
        write_project(tmpl, tmp_path / "o.ipro", xy, {"Elevation": z, "typo": z}, definition=d)
    with pytest.raises(ValueError, match="differ"):
        write_project(tmpl, tmpl, xy, {"Elevation": z})
    with pytest.raises(ValueError, match="flow state"):
        fastmech_conditions(Package(xy=xy, chainage=np.arange(4.0), elevation=z),
                            roughness_by_node=True)

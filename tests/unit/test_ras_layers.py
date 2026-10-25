"""Copy a layer under a new name and bind layers in the project file, headless (probe-proven)."""

from pathlib import Path

import h5py
import numpy as np
import pytest

from flowfield2d.engines.ras2025.h5edit import read_fixed_string
from flowfield2d.engines.ras2025.templates import associations, copy_layer, set_associations

XML = ('﻿<Project>\r\n  <Projection Type="EPSG">6597</Projection>\r\n  <PlanAssociations>\r\n'
       '    <PlanAssociation Plan="p01_a" Geometry="g01_a" BoundaryCondition="bc01_a" />\r\n'
       '  </PlanAssociations>\r\n  <GeometryAssociations>\r\n'
       '    <GeometryAssociation Geometry="g01_a" Terrain="t01" N_Values="n01" />\r\n'
       '  </GeometryAssociations>\r\n</Project>\r\n')
GROUPS = {"Geometries": "Geometry", "Boundary Conditions": "Boundary Conditions", "Plans": "Plan Data"}


def _name_attr(group: h5py.Group, value: str, size: int) -> None:
    tid = h5py.h5t.C_S1.copy()
    tid.set_size(size)
    tid.set_strpad(h5py.h5t.STR_NULLTERM)
    group.attrs.create("Name", np.array(value.encode(), dtype=f"S{size}"), dtype=h5py.Datatype(tid))


def _project(tmp_path: Path) -> Path:
    p = tmp_path / "P"
    p.mkdir()
    (p / "P.ras").write_bytes(XML.encode("utf-8"))
    for folder, group in GROUPS.items():
        (p / folder).mkdir()
        stem = {"Geometries": "g01_a", "Boundary Conditions": "bc01_a", "Plans": "p01_a"}[folder]
        with h5py.File(p / folder / f"{stem}.h5", "w") as f:
            g = f.create_group(group)
            _name_attr(g, stem, len(stem) + 1)
            g.create_dataset("x", data=np.arange(3))
    return p


def test_copy_layer_renames_in_place(tmp_path: Path) -> None:
    p = _project(tmp_path)
    out = copy_layer(p, "geometry", "g01_a", "g02_a")
    assert out == p / "Geometries" / "g02_a.h5"
    with h5py.File(out, "r") as f:
        assert read_fixed_string(f["Geometry"], "Name") == "g02_a"
        assert f["Geometry"].attrs["Name"].dtype.itemsize == len("g01_a") + 1   # type unchanged
        assert f["Geometry/x"][:].tolist() == [0, 1, 2]
    with h5py.File(p / "Geometries" / "g01_a.h5", "r") as f:
        assert read_fixed_string(f["Geometry"], "Name") == "g01_a"         # source untouched
    copy_layer(p, "boundary", "bc01_a", "bc2")                              # shorter name fits
    copy_layer(p, "plan", "p01_a", "p02_a")


def test_copy_layer_errors(tmp_path: Path) -> None:
    p = _project(tmp_path)
    with pytest.raises(ValueError, match="long"):
        copy_layer(p, "geometry", "g01_a", "g01_much_longer_name")
    assert not (p / "Geometries" / "g01_much_longer_name.h5").exists()    # nothing left behind
    copy_layer(p, "geometry", "g01_a", "g02_a")
    with pytest.raises(FileExistsError):
        copy_layer(p, "geometry", "g01_a", "g02_a")
    with pytest.raises(FileNotFoundError):
        copy_layer(p, "plan", "nope", "p09")
    with pytest.raises(ValueError, match="kind"):
        copy_layer(p, "terrain", "t01", "t02")


def test_set_and_read_associations_preserves_file(tmp_path: Path) -> None:
    p = _project(tmp_path)
    set_associations(p, plans={"p02_a": ("g02_a", "bc02_a")},
                     geometries={"g02_a": ("t03", "n01")})
    raw = (p / "P.ras").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    assert b'<Projection Type="EPSG">6597</Projection>' in raw
    a = associations(p)
    assert a["plans"] == {"p01_a": ("g01_a", "bc01_a"), "p02_a": ("g02_a", "bc02_a")}
    assert a["geometries"] == {"g01_a": ("t01", "n01"), "g02_a": ("t03", "n01")}
    set_associations(p, geometries={"g02_a": ("t01", "n01")})              # replace, not duplicate
    assert associations(p)["geometries"]["g02_a"] == ("t01", "n01")
    assert (p / "P.ras").read_bytes().count(b'Geometry="g02_a" Terrain') == 1

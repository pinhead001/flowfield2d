import sqlite3
import struct
from pathlib import Path

import pytest
from shapely.geometry import MultiPolygon, Polygon, box

from flowfield2d.post.gpkg import read_gpkg_layer, write_gpkg

WKT_3857 = ('PROJCS["WGS 84 / Pseudo-Mercator",GEOGCS["WGS 84",DATUM["WGS_1984",'
            'SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],'
            'UNIT["degree",0.0174532925199433]],PROJECTION["Mercator_1SP"],'
            'UNIT["metre",1]]')


def _geoms() -> list[MultiPolygon]:
    a = MultiPolygon([box(0, 0, 10, 10), box(20, 20, 25, 30)])
    b = MultiPolygon([Polygon([(100, 100), (140, 100), (140, 150), (100, 100)],
                              [[(110, 105), (120, 105), (120, 115), (110, 105)]])])
    return [a, b]


def _write(path: Path, layer: str = "wet") -> Path:
    return write_gpkg(path, layer, _geoms(),
                      {"scenario_id": ["s1", "s2"], "q": [12.5, 40.0], "n": [1, 2],
                       "ok": [True, False]},
                      crs_wkt=WKT_3857, srs_id=3857, srs_name="WGS 84 / Pseudo-Mercator",
                      description="wet extents")


def test_write_and_read_back(tmp_path: Path) -> None:
    out = _write(tmp_path / "sub" / "x.gpkg")
    assert out.is_file()
    geoms, attrs = read_gpkg_layer(out, "wet")
    assert len(geoms) == 2
    for got, want in zip(geoms, _geoms(), strict=True):
        assert isinstance(got, MultiPolygon) and got.equals(want)
    assert attrs["scenario_id"] == ["s1", "s2"]
    assert attrs["q"] == [12.5, 40.0]
    assert attrs["n"] == [1, 2]
    assert attrs["ok"] == [1, 0]


def test_schema_and_metadata(tmp_path: Path) -> None:
    out = _write(tmp_path / "x.gpkg")
    con = sqlite3.connect(out)
    try:
        assert con.execute("PRAGMA application_id").fetchone()[0] == 0x47504B47
        assert con.execute("PRAGMA user_version").fetchone()[0] == 10300
        srs = con.execute("select srs_id, organization, organization_coordsys_id, definition "
                          "from gpkg_spatial_ref_sys order by srs_id").fetchall()
        assert [r[0] for r in srs] == [-1, 0, 3857]
        assert srs[2][1:] == ("EPSG", 3857, WKT_3857)
        row = con.execute("select table_name, data_type, identifier, description, min_x, min_y, "
                          "max_x, max_y, srs_id from gpkg_contents").fetchall()
        assert row == [("wet", "features", "wet", "wet extents", 0.0, 0.0, 140.0, 150.0, 3857)]
        gc = con.execute("select table_name, column_name, geometry_type_name, srs_id, z, m "
                         "from gpkg_geometry_columns").fetchall()
        assert gc == [("wet", "geom", "MULTIPOLYGON", 3857, 0, 0)]
        cols = {r[1]: r[2] for r in con.execute("PRAGMA table_info(wet)").fetchall()}
        assert cols == {"fid": "INTEGER", "geom": "BLOB", "scenario_id": "TEXT", "q": "REAL",
                        "n": "INTEGER", "ok": "INTEGER"}
        blob = con.execute("select geom from wet where fid = 1").fetchone()[0]
    finally:
        con.close()
    # GeoPackageBinary header: magic, version, flags (XY envelope, little endian), srs_id,
    # envelope minx, maxx, miny, maxy, then little-endian WKB.
    assert blob[:2] == b"GP" and blob[2] == 0 and blob[3] == 0b00000011
    assert struct.unpack("<i", blob[4:8])[0] == 3857
    assert struct.unpack("<4d", blob[8:40]) == (0.0, 25.0, 0.0, 30.0)
    assert blob[40] == 1                                       # WKB byte order: little endian


def test_second_layer_and_duplicate(tmp_path: Path) -> None:
    out = _write(tmp_path / "x.gpkg")
    write_gpkg(out, "other", [box(0, 0, 1, 1)], {"k": [1]}, crs_wkt=WKT_3857, srs_id=3857,
               srs_name="WGS 84 / Pseudo-Mercator", geometry_type="POLYGON")
    con = sqlite3.connect(out)
    try:
        assert con.execute("select count(*) from gpkg_contents").fetchone()[0] == 2
        assert con.execute("select count(*) from gpkg_spatial_ref_sys").fetchone()[0] == 3
    finally:
        con.close()
    geoms, attrs = read_gpkg_layer(out, "other")
    assert geoms[0].equals(box(0, 0, 1, 1)) and attrs == {"k": [1]}
    with pytest.raises(ValueError):
        _write(out)


def test_length_mismatch_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        write_gpkg(tmp_path / "x.gpkg", "wet", _geoms(), {"q": [1.0]}, crs_wkt=WKT_3857,
                   srs_id=3857, srs_name="x")
    assert not (tmp_path / "x.gpkg").exists()                 # validated before any write

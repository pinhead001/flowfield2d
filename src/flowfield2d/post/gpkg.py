"""GeoPackage feature writer on the standard library (sqlite3) only, so consumers without GDAL
vector bindings can still write one (GeoPackage 1.3: application_id "GPKG", user_version 10300).

Geometry BLOBs are GeoPackageBinary: magic "GP", version 0, a flags byte with an XY envelope
and little-endian byte order (0b00000011), srs_id int32 LE, the envelope as minx, maxx, miny,
maxy float64 LE, then little-endian WKB. Attribute column types come from the Python values:
int / bool -> INTEGER, float -> REAL, str -> TEXT.
"""

from __future__ import annotations

import sqlite3
import struct
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import shapely
from shapely.geometry.base import BaseGeometry

APPLICATION_ID = 0x47504B47
USER_VERSION = 10300
_FLAGS_XY_LE = 0b00000011
_ENVELOPE_BYTES = (0, 32, 48, 48, 64)   # header envelope size by envelope indicator

_SCHEMA = """
CREATE TABLE IF NOT EXISTS gpkg_spatial_ref_sys (
  srs_name TEXT NOT NULL, srs_id INTEGER NOT NULL PRIMARY KEY, organization TEXT NOT NULL,
  organization_coordsys_id INTEGER NOT NULL, definition TEXT NOT NULL, description TEXT);
CREATE TABLE IF NOT EXISTS gpkg_contents (
  table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL, identifier TEXT UNIQUE,
  description TEXT DEFAULT '', last_change DATETIME NOT NULL DEFAULT
  (strftime('%Y-%m-%dT%H:%M:%fZ','now')), min_x DOUBLE, min_y DOUBLE, max_x DOUBLE,
  max_y DOUBLE, srs_id INTEGER,
  CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id));
CREATE TABLE IF NOT EXISTS gpkg_geometry_columns (
  table_name TEXT NOT NULL, column_name TEXT NOT NULL, geometry_type_name TEXT NOT NULL,
  srs_id INTEGER NOT NULL, z TINYINT NOT NULL, m TINYINT NOT NULL,
  CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name),
  CONSTRAINT uk_gc_table_name UNIQUE (table_name),
  CONSTRAINT fk_gc_tn FOREIGN KEY (table_name) REFERENCES gpkg_contents(table_name),
  CONSTRAINT fk_gc_srs FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys (srs_id));
"""

_MANDATORY_SRS = (
    ("Undefined cartesian SRS", -1, "NONE", -1, "undefined", "undefined cartesian coordinate "
     "reference system"),
    ("Undefined geographic SRS", 0, "NONE", 0, "undefined", "undefined geographic coordinate "
     "reference system"),
)


def geometry_blob(geom: BaseGeometry, srs_id: int) -> bytes:
    """GeoPackageBinary for `geom` with an XY envelope."""
    minx, miny, maxx, maxy = geom.bounds
    header = struct.pack("<2sBBi4d", b"GP", 0, _FLAGS_XY_LE, int(srs_id), minx, maxx, miny, maxy)
    return header + bytes(shapely.to_wkb(geom))


def parse_geometry_blob(blob: bytes) -> BaseGeometry:
    """The geometry of a GeoPackageBinary blob (any envelope indicator)."""
    if blob[:2] != b"GP":
        raise ValueError("not a GeoPackage geometry blob")
    envelope = _ENVELOPE_BYTES[(blob[3] >> 1) & 0b111]
    return shapely.from_wkb(bytes(blob[8 + envelope:]))


def _sql_type(values: Sequence[Any], name: str) -> str:
    for v in values:
        if v is None:
            continue
        if isinstance(v, bool | int):
            return "INTEGER"
        if isinstance(v, float):
            return "REAL"
        if isinstance(v, str):
            return "TEXT"
        raise TypeError(f"attribute {name!r}: unsupported value type {type(v).__name__}")
    return "TEXT"


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def write_gpkg(path: Path, layer: str, geometries: Sequence[BaseGeometry],
               attributes: Mapping[str, Sequence[Any]], *, crs_wkt: str, srs_id: int,
               srs_name: str, organization: str = "EPSG", geometry_type: str = "MULTIPOLYGON",
               description: str = "") -> Path:
    """Write `geometries` with `attributes` as feature table `layer` of the GeoPackage at
    `path`, creating the file (schema and SRS rows) if absent. Raises ValueError if the layer
    exists or an attribute column's length differs from the geometry count."""
    n = len(geometries)
    for k, v in attributes.items():
        if len(v) != n:
            raise ValueError(f"attribute {k!r} has {len(v)} values for {n} geometries")
    if "fid" in attributes or "geom" in attributes:
        raise ValueError("attribute names 'fid' and 'geom' are reserved")
    col_types = {k: _sql_type(v, k) for k, v in attributes.items()}

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(out)
    try:
        con.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        con.execute(f"PRAGMA user_version = {USER_VERSION}")
        con.executescript(_SCHEMA)
        if con.execute("SELECT 1 FROM gpkg_contents WHERE table_name = ?",
                       (layer,)).fetchone():
            raise ValueError(f"layer {layer!r} already exists in {out}")
        with con:
            con.executemany(
                "INSERT OR IGNORE INTO gpkg_spatial_ref_sys VALUES (?, ?, ?, ?, ?, ?)",
                [*_MANDATORY_SRS,
                 (srs_name, int(srs_id), organization, int(srs_id), crs_wkt, "")])
            cols = ", ".join(f"{_quote(k)} {t}" for k, t in col_types.items())
            con.execute(f"CREATE TABLE {_quote(layer)} (fid INTEGER PRIMARY KEY AUTOINCREMENT, "
                        f"geom BLOB{', ' + cols if cols else ''})")
            env: tuple[float | None, ...] = (
                tuple(float(b) for b in shapely.total_bounds(list(geometries))) if n
                else (None, None, None, None))
            now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + \
                f"{datetime.now(UTC).microsecond // 1000:03d}Z"
            con.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, "
                        "description, last_change, min_x, min_y, max_x, max_y, srs_id) "
                        "VALUES (?, 'features', ?, ?, ?, ?, ?, ?, ?, ?)",
                        (layer, layer, description, now, env[0], env[1], env[2], env[3],
                         int(srs_id)))
            con.execute("INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', ?, ?, 0, 0)",
                        (layer, geometry_type, int(srs_id)))
            names = ["geom", *attributes]
            marks = ", ".join("?" for _ in names)
            keys = list(attributes)
            rows = [(geometry_blob(g, srs_id),
                     *(int(attributes[k][i]) if isinstance(attributes[k][i], bool)
                       else attributes[k][i] for k in keys))
                    for i, g in enumerate(geometries)]
            con.executemany(f"INSERT INTO {_quote(layer)} "
                            f"({', '.join(_quote(c) for c in names)}) VALUES ({marks})", rows)
    finally:
        con.close()
    return out


def read_gpkg_layer(path: Path, layer: str) -> tuple[list[BaseGeometry], dict[str, list[Any]]]:
    """Geometries (fid order) and attribute columns of `layer` (for tests and QA)."""
    con = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    try:
        geom_col = con.execute("SELECT column_name FROM gpkg_geometry_columns WHERE "
                               "table_name = ?", (layer,)).fetchone()
        if geom_col is None:
            raise ValueError(f"layer {layer!r} not found in {path}")
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({_quote(layer)})").fetchall()]
        attrs = [c for c in cols if c not in ("fid", geom_col[0])]
        select = ", ".join(_quote(c) for c in (geom_col[0], *attrs))
        rows = con.execute(f"SELECT {select} FROM {_quote(layer)} ORDER BY fid").fetchall()
    finally:
        con.close()
    geoms = [parse_geometry_blob(r[0]) for r in rows]
    table = {a: [r[i + 1] for r in rows] for i, a in enumerate(attrs)}
    return geoms, table

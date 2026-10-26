"""Land-cover n layers: polygons added to a classification layer's polygon classifier, n-table
rows, and the n layer's link to its classification layer. Synthetic files with the layout the
pinned build writes (probe 2026-10-25): a classification layer can hold a raster and a polygon
classifier; polygons override the raster."""

from pathlib import Path

import h5py
import numpy as np
import pytest
from shapely.geometry import Polygon

from flowfield2d.engines.ras2025.landcover import (
    add_class_polygons,
    link_classification,
    set_n_value,
)

POLYS = "/Classification/Classification Polygons"


def _class_layer(path: Path) -> Path:
    """Raster classifier plus an empty polygon classifier group (as GUI-made)."""
    with h5py.File(path, "w") as f:
        g = f.create_group("Classification")
        g.attrs["Name"] = np.bytes_(b"class01")
        att = np.array([(b"lc", b"Raster", b"/Classification/lc"),
                        (b"Classification Polygons", b"PolyClassifier", POLYS)],
                       dtype=[("Name", "S23"), ("Type", "S14"), ("Location", "S39")])
        g.create_dataset("Attributes", data=att)
        p = g.create_group("Classification Polygons")
        p.attrs["Name"] = np.bytes_(b"Classification Polygons")
    return path


def _n_layer(path: Path) -> Path:
    with h5py.File(path, "w") as f:
        g = f.create_group("NValues")
        g.attrs.create("Classification Layer Name", np.bytes_(b"OLD"),
                       dtype=h5py.string_dtype("ascii", 3))
        g.attrs["Mode"] = np.bytes_(b"Classification Layer")
        tab = np.array([(b"NoData", 0.0), (b"Open Water", 0.035)],
                       dtype=[("Class", "S28"), ("N Value", "<f4")])
        g.create_dataset("Table", data=tab)
    return path


SQ = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
TRI = Polygon([(20, 0), (30, 0), (25, 8)])


def test_polygons_written_into_an_empty_classifier(tmp_path: Path) -> None:
    lay = _class_layer(tmp_path / "c.h5")
    add_class_polygons(lay, [SQ, TRI], "Channel")
    with h5py.File(lay, "r") as f:
        p = f[POLYS]
        assert [r["Classification"] for r in p["Attributes"][()]] == [b"Channel", b"Channel"]
        xy = p["Polygon"][()]
        assert xy.shape == (4 + 3, 2) and xy.dtype == np.float64   # rings, no closing vertex
        assert p["Polygon"].attrs["Count"].tolist() == [4, 3]
        assert p["Polygon"].attrs["Start"].tolist() == [0, 4]
        assert p["Polygon"].attrs["Count"].dtype == np.int32
        assert Polygon(xy[:4]).equals(SQ) and Polygon(xy[4:]).equals(TRI)
        assert p.attrs["Name"] == b"Classification Polygons"             # group attrs kept


def test_polygons_append_and_class_names_widen(tmp_path: Path) -> None:
    lay = _class_layer(tmp_path / "c.h5")
    add_class_polygons(lay, [SQ], "Bar")
    add_class_polygons(lay, [TRI], "Gravel bar island")
    with h5py.File(lay, "r") as f:
        p = f[POLYS]
        assert [r["Classification"] for r in p["Attributes"][()]] == [b"Bar", b"Gravel bar island"]
        assert p["Polygon"].attrs["Count"].tolist() == [4, 3]
        assert p["Polygon"].attrs["Start"].tolist() == [0, 4]


def test_bad_polygons_rejected_before_writing(tmp_path: Path) -> None:
    lay = _class_layer(tmp_path / "c.h5")
    with pytest.raises(ValueError):
        add_class_polygons(lay, [SQ, Polygon()], "Channel")
    with pytest.raises(ValueError):
        add_class_polygons(lay, [], "Channel")
    with pytest.raises(ValueError):
        add_class_polygons(lay, [SQ], "")
    with h5py.File(lay, "r") as f:
        assert "Polygon" not in f[POLYS]


def test_set_n_value_adds_or_updates_rows(tmp_path: Path) -> None:
    lay = _n_layer(tmp_path / "n.h5")
    set_n_value(lay, "Channel", 0.035)
    set_n_value(lay, "Open Water", 0.03)
    with h5py.File(lay, "r") as f:
        t = f["/NValues/Table"][()]
        assert t.dtype == np.dtype([("Class", "S28"), ("N Value", "<f4")])
        assert [(r["Class"], round(float(r["N Value"]), 4)) for r in t] == [
            (b"NoData", 0.0), (b"Open Water", 0.03), (b"Channel", 0.035)]
    with pytest.raises(ValueError):
        set_n_value(lay, "Channel", 0.0)
    set_n_value(lay, "A class name longer than twenty-eight chars", 0.05)     # widens
    with h5py.File(lay, "r") as f:
        last = f["/NValues/Table"][()][-1]["Class"]
        assert last == b"A class name longer than twenty-eight chars"


def test_link_classification_rewrites_the_layer_name(tmp_path: Path) -> None:
    lay = _n_layer(tmp_path / "n.h5")
    link_classification(lay, "class01_NLCD")                    # longer than the stored "OLD"
    with h5py.File(lay, "r") as f:
        g = f["/NValues"]
        assert g.attrs["Classification Layer Name"] == b"class01_NLCD"
        assert g.attrs["Mode"] == b"Classification Layer"

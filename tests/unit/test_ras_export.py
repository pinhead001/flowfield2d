"""RAS results -> engine-neutral flow state for exports."""

import math
from pathlib import Path

import h5py
import numpy as np
import pytest
import rasterio
from shapely.geometry import box

from flowfield2d.engines.ras2025.export import (
    class_polygons,
    flow_state,
    n_values,
    polygon_n,
    terrain_sources,
)
from flowfield2d.engines.ras2025.results import ResultsReader
from flowfield2d.roughness import rasterize_n

from .test_results_series import _result

FT = 0.3048


def _reader(tmp_path: Path) -> ResultsReader:
    p = _result(tmp_path)
    with h5py.File(p, "a") as f:        # RAS always writes face velocity; the fixture omits it
        f.create_dataset("/Results/Output Blocks/Base Output/2D Flow Areas/Mesh/Face Velocity",
                         data=np.full((3, 8), 0.5, dtype="f4"))
    return ResultsReader(p)


def test_flow_state_in_si(tmp_path: Path) -> None:
    r = _reader(tmp_path)
    s = flow_state(r, "Mesh", 1, FT, inflow_lines=["Inflow"], tol=0.01)
    assert math.isclose(s.discharge, 5.0 * FT**3)            # inflow is -5 through the left face
    assert s.cell_xy[:2].tolist() == [[0.5, 0.5], [1.5, 0.5]]  # coordinates stay in CRS units
    assert np.allclose(s.wse[:2], np.array([101.0, 103.0]) * FT)
    assert s.depth is not None and np.allclose(s.depth[:2], np.array([1.0, 2.0]) * FT)
    assert s.velocity is not None and np.allclose(s.velocity[:2], 0.5 * FT)
    assert np.isnan(s.wse[2])                                 # dry cell


def test_flow_state_last_output_and_given_discharge(tmp_path: Path) -> None:
    r = _reader(tmp_path)
    s = flow_state(r, "Mesh", -1, 1.0, discharge=12.5)
    assert s.discharge == 12.5 and np.allclose(s.wse[:2], [102.0, 104.0])
    both = flow_state(r, "Mesh", -1, 1.0, inflow_lines=["Inflow", "Outflow"], tol=0.01)
    assert math.isclose(both.discharge, 5.0 + 4.0)


def test_flow_state_refuses_bad_requests(tmp_path: Path) -> None:
    r = _reader(tmp_path)
    with pytest.raises(ValueError):
        flow_state(r, "Mesh", 0, 1.0)
    with pytest.raises(IndexError):
        flow_state(r, "Mesh", 7, 1.0, discharge=1.0)
    with pytest.raises(KeyError):
        flow_state(r, "Mesh", 0, 1.0, inflow_lines=["Nope"], tol=0.01)


def test_terrain_sources_in_stack_order(tmp_path: Path) -> None:
    layer = tmp_path / "T.h5"
    dt = [("Name", "S8"), ("Type", "S6"), ("Location", "S20")]
    with h5py.File(layer, "w") as f:
        f.create_dataset("/Terrain/Attributes", data=np.array(
            [(b"base", b"Raster", b"/Terrain/base"), (b"patch", b"Raster", b"/Terrain/patch")],
            dtype=dt))
        f.create_group("/Terrain/base").attrs["Filename"] = np.bytes_(b"T.base.tif")
        f.create_group("/Terrain/patch").attrs["Filename"] = np.bytes_(b"T.patch.tif")
    with pytest.raises(FileNotFoundError):
        terrain_sources(layer)
    for name in ("T.base.tif", "T.patch.tif"):
        (tmp_path / name).write_bytes(b"")
    assert [p.name for p in terrain_sources(layer)] == ["T.base.tif", "T.patch.tif"]


def _layers(tmp_path: Path) -> tuple[Path, Path]:
    cl, nl = tmp_path / "C.h5", tmp_path / "N.h5"
    with h5py.File(cl, "w") as f:
        g = f.create_group("/Classification/Classification Polygons")
        g.create_dataset("Attributes", data=np.array([(b"flood",), (b"channel",)],
                                                     dtype=[("Classification", "S7")]))
        ring = lambda b: np.array(b.exterior.coords)[:-1]     # noqa: E731
        pts = np.vstack([ring(box(0, 0, 10, 10)), ring(box(4, 0, 6, 10))])
        ds = g.create_dataset("Polygon", data=np.column_stack([pts, np.zeros(len(pts))]))
        ds.attrs["Start"] = np.array([0, 4], dtype="i4")
        ds.attrs["Count"] = np.array([4, 4], dtype="i4")
    with h5py.File(nl, "w") as f:
        g = f.create_group("/NValues")
        g.attrs["Constant Value"] = np.float32(0.06)
        g.create_dataset("Table", data=np.array(
            [(b"NoData", 0.0), (b"flood", 0.08), (b"channel", 0.035)],
            dtype=[("Class", "S7"), ("N Value", "<f4")]))
    return cl, nl


def test_polygon_n_and_rasterize(tmp_path: Path) -> None:
    cl, nl = _layers(tmp_path)
    polys = class_polygons(cl)
    assert [n for n, _ in polys] == ["flood", "channel"] and polys[1][1].area == 20.0
    table, default = n_values(nl)
    assert math.isclose(table["channel"], 0.035, rel_tol=1e-6) and math.isclose(default, 0.06,
                                                                              rel_tol=1e-6)
    pairs, default = polygon_n(cl, nl)
    out = rasterize_n(pairs, default, (-2.0, 0.0, 12.0, 10.0), 1.0, tmp_path / "n.tif")
    with rasterio.open(out) as ds:
        row = ds.read(1)[5]
    # outside: default; flood polygon; the later channel polygon covers the flood polygon
    assert np.allclose(row[[0, 1, 12, 13]], 0.06) and np.allclose(row[[2, 5, 8, 11]], 0.08)
    assert np.allclose(row[[6, 7]], 0.035)
    with pytest.raises(ValueError):
        rasterize_n(pairs, default, (0.0, 0.0, 0.0, 10.0), 1.0, tmp_path / "x.tif")

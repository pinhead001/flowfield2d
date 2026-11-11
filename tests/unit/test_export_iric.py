import json
import math
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString

from flowfield2d.curvigrid import build_grid
from flowfield2d.export.iric import (
    FlowState,
    drag_from_manning,
    grid_attributes,
    nearest_values,
    prepare,
    write_grid_csv,
    write_package,
    write_points_csv,
    write_raster_scaled,
    write_tpo,
)

FT = 0.3048


def _raster(path: Path, fn, *, crs: str | None = None) -> Path:  # type: ignore[no-untyped-def]
    """200 x 60 raster of 1-unit cells over x 0..200, y -30..30 holding fn(x, y) at centres."""
    rows, cols = np.mgrid[0:60, 0:200]
    x, y = cols + 0.5, 30 - rows - 0.5
    with rasterio.open(path, "w", driver="GTiff", height=60, width=200, count=1,
                       dtype="float32", transform=from_origin(0, 30, 1, 1), nodata=-9999.0,
                       crs=crs) as ds:
        ds.write(np.asarray(fn(x, y), dtype="float32"), 1)
    return path


def _grid():  # type: ignore[no-untyped-def]
    return build_grid(LineString([(10, 0), (190, 0)]), width=40.0, ni=10, nj=5)


def test_drag_from_manning_hand_value() -> None:
    # n = 0.03, h = 1 m: Cd = 9.80665 * 0.0009 = 0.008826
    assert math.isclose(float(drag_from_manning(0.03, 1.0)), 0.008825985, rel_tol=1e-6)
    assert math.isclose(float(drag_from_manning(0.03, 8.0)), 0.008825985 / 2, rel_tol=1e-6)
    assert np.isnan(drag_from_manning(0.03, 0.0))


def test_nearest_values_skips_nan_and_far_points() -> None:
    src = np.array([[0.0, 0.0], [10.0, 0.0], [20.0, 0.0]])
    out = nearest_values(src, [1.0, np.nan, 3.0], np.array([[1.0, 0.0], [11.0, 0.0], [50.0, 0]]),
                         max_dist=10.0)
    assert out[0] == 1.0 and out[1] == 3.0 and np.isnan(out[2])


def test_prepare_converts_to_si(tmp_path: Path) -> None:
    """A model in feet: x, y, terrain and nothing else scale; n does not."""
    terrain = _raster(tmp_path / "z.tif", lambda x, y: 100.0 - 0.01 * x + 0.0 * y)
    nras = _raster(tmp_path / "n.tif", lambda x, y: np.where(np.abs(y) < 10, 0.03, 0.08))
    g = _grid()
    cells = np.array([[x, 0.0] for x in np.arange(5.0, 200.0, 10.0)])
    flow = FlowState(discharge=50.0, cell_xy=cells, wse=(102.0 - 0.01 * cells[:, 0]) * FT)
    pkg = prepare(g, terrain, xy_unit_m=FT, z_unit_m=FT, roughness=nras, flow=flow,
                  wse_max_dist=30.0)
    assert np.allclose(pkg.xy, g.xy * FT) and np.allclose(pkg.chainage, g.s * FT)
    assert np.allclose(pkg.elevation, (100.0 - 0.01 * g.xy[..., 0]) * FT, atol=1e-4)
    assert pkg.n_node is not None and pkg.n_cell is not None
    assert np.allclose(pkg.n_node[:, 2], 0.03) and np.allclose(pkg.n_node[:, 0], 0.08)
    assert pkg.n_cell.shape == (9, 4)
    assert pkg.discharge == 50.0
    assert pkg.stage_upstream is not None and pkg.stage_downstream is not None
    assert math.isclose(pkg.stage_upstream, (102.0 - 0.01 * 15.0) * FT, abs_tol=1e-9)
    assert math.isclose(pkg.stage_downstream, (102.0 - 0.01 * 185.0) * FT, abs_tol=1e-9)
    assert pkg.depth is not None and (pkg.depth[np.isfinite(pkg.depth)] > 0).all()


def test_prepare_refuses_nodes_off_the_terrain(tmp_path: Path) -> None:
    terrain = _raster(tmp_path / "z.tif", lambda x, y: 0.0 * x)
    g = build_grid(LineString([(10, 0), (190, 0)]), width=80.0, ni=10, nj=5)
    with pytest.raises(ValueError, match="no terrain value"):
        prepare(g, terrain, xy_unit_m=1.0, z_unit_m=1.0)


def test_grid_attributes_per_solver(tmp_path: Path) -> None:
    terrain = _raster(tmp_path / "z.tif", lambda x, y: 0.0 * x)
    g = _grid()
    cells = g.cell_centres().reshape(-1, 2)
    flow = FlowState(discharge=10.0, cell_xy=cells, wse=np.full(len(cells), 2.0))
    pkg = prepare(g, terrain, xy_unit_m=1.0, z_unit_m=1.0, roughness=0.04, flow=flow,
                  wse_max_dist=50.0)
    node, cell = grid_attributes(pkg, "fastmech")
    assert set(node) == {"Elevation"} and not cell          # no depth chosen: no drag written
    node, _ = grid_attributes(pkg, "fastmech", drag_depth=1.0)
    assert np.allclose(node["roughness"], G_N2 := 9.80665 * 0.04**2)
    node, _ = grid_attributes(pkg, "fastmech", drag_depth="local")
    assert np.allclose(node["roughness"], G_N2 / np.cbrt(2.0))
    node, cell = grid_attributes(pkg, "nays2dh")
    assert set(node) == {"Elevation", "Elevation_zb"}
    assert np.array_equal(node["Elevation_zb"], node["Elevation"])
    assert np.allclose(cell["roughness_cell"], 0.04)
    with pytest.raises(ValueError):
        grid_attributes(pkg, "other")
    with pytest.raises(ValueError):
        grid_attributes(pkg, "fastmech", drag_depth=0.0)


def test_grid_csv_layout(tmp_path: Path) -> None:
    xy = np.zeros((3, 2, 2))
    xy[..., 0] = np.array([0.0, 1.0, 2.0])[:, None]
    xy[..., 1] = np.array([0.0, 5.0])[None, :]
    z = np.arange(6, dtype=float).reshape(3, 2)
    p = write_grid_csv(tmp_path / "g.csv", xy, {"Elevation": z},
                       {"roughness_cell": np.array([[0.03], [0.04]])})
    rows = p.read_text().splitlines()
    assert rows[:3] == ["IMAX,JMAX,KMAX", "3,2,1", "I,J,K,X,Y,Z,N_Elevation,C_roughness_cell"]
    assert rows[3:] == [
        "0,0,0,0,0,0,0,0.03", "1,0,0,1,0,0,2,0.04", "2,0,0,2,0,0,4,",
        "0,1,0,0,5,0,1,", "1,1,0,1,5,0,3,", "2,1,0,2,5,0,5,",
    ]


def test_grid_csv_refuses_bad_values(tmp_path: Path) -> None:
    xy = np.zeros((3, 2, 2))
    with pytest.raises(ValueError, match="shape"):
        write_grid_csv(tmp_path / "g.csv", xy, {"Elevation": np.zeros((2, 3))})
    bad = np.zeros((3, 2))
    bad[1, 1] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        write_grid_csv(tmp_path / "g.csv", xy, {"Elevation": bad})


def test_tpo_and_points_csv(tmp_path: Path) -> None:
    p = write_tpo(tmp_path / "a.tpo", [1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.5, np.nan, 9.0])
    assert p.read_text().splitlines() == ["2", "1 4 7.5", "3 6 9"]
    c = write_points_csv(tmp_path / "w.csv", [1.0, 2.0, 3.0], [4.0, 5.0, 6.0],
                         {"WaterSurfaceElevation": [10.0, np.nan, 12.0],
                          "Depth": [1.0, 2.0, np.nan]})
    assert c.read_text().splitlines() == ["X,Y,WaterSurfaceElevation,Depth", "1,4,10,1",
                                          "3,6,12,"]


def test_raster_scaled_clips_and_scales(tmp_path: Path) -> None:
    src = _raster(tmp_path / "z.tif", lambda x, y: x + 0.0 * y, crs="EPSG:2927")
    out = write_raster_scaled(src, tmp_path / "o.tif", xy_scale=FT, value_scale=FT,
                              bounds=(10.2, -5.0, 20.0, 5.0))
    with rasterio.open(out) as ds:
        assert ds.crs is None                              # scaled feet are not that CRS
        assert (ds.width, ds.height) == (10, 10)
        assert math.isclose(ds.bounds.left, 10 * FT) and math.isclose(ds.bounds.top, 5 * FT)
        assert math.isclose(ds.transform.a, FT)
        assert np.allclose(ds.read(1)[0], (np.arange(10, 20) + 0.5) * FT, atol=1e-5)
    same = write_raster_scaled(src, tmp_path / "s.tif", xy_scale=1.0, value_scale=1.0)
    with rasterio.open(same) as ds:
        assert ds.crs is not None and (ds.width, ds.height) == (200, 60)


def test_write_package(tmp_path: Path) -> None:
    terrain = _raster(tmp_path / "z.tif", lambda x, y: 100.0 - 0.01 * x + 0.0 * y)
    nras = _raster(tmp_path / "n.tif", lambda x, y: 0.035 + 0.0 * x)
    g = _grid()
    cells = np.array([[x, 0.0] for x in np.arange(5.0, 200.0, 10.0)])
    wse = 102.0 - 0.01 * cells[:, 0]
    wse[3] = np.nan                                         # a dry cell
    flow = FlowState(discharge=50.0, cell_xy=cells, wse=wse, depth=np.full(len(cells), 2.0))
    pkg = prepare(g, terrain, xy_unit_m=1.0, z_unit_m=1.0, roughness=nras, flow=flow,
                  wse_max_dist=30.0)
    paths = write_package(pkg, tmp_path / "out", solver="fastmech", drag_depth=2.0,
                          terrain=terrain, roughness=nras, flow=flow, tpo_spacing=10.0, margin=5.0,
                          extra={"source": "unit test"})
    assert set(paths) == {"grid", "elevation", "elevation_points", "manning_n", "wse", "summary"}
    head = paths["grid"].read_text().splitlines()
    assert head[1] == "10,5,1" and head[2] == "I,J,K,X,Y,Z,N_Elevation,N_roughness"
    assert len(head) == 3 + 50
    with rasterio.open(paths["elevation"]) as ds:
        assert ds.bounds.left == 5.0 and ds.bounds.right == 195.0 and ds.bounds.top == 25.0
    assert int(paths["elevation_points"].read_text().splitlines()[0]) == 20 * 6
    w = paths["wse"].read_text().splitlines()
    assert w[0] == "X,Y,WaterSurfaceElevation,Depth" and len(w) == 1 + len(cells) - 1
    info = json.loads(paths["summary"].read_text())
    assert info["discharge_cms"] == 50.0 and info["source"] == "unit test"
    assert info["node_attributes"] == ["Elevation", "roughness"]
    assert math.isclose(info["stage_downstream_m"], 102.0 - 1.85)
    assert len(info["wse_profile"]) == 10 and info["roughness"]["fastmech_drag_depth"] == 2.0


def test_write_package_terrain_stack(tmp_path: Path) -> None:
    base = _raster(tmp_path / "base.tif", lambda x, y: 10.0 + 0.0 * x)
    patch = tmp_path / "patch.tif"                       # 0.5-unit cells over x 50..100, y -5..5
    with rasterio.open(patch, "w", driver="GTiff", height=20, width=100, count=1,
                       dtype="float32", transform=from_origin(50, 5, 0.5, 0.5),
                       nodata=-9999.0) as ds:
        ds.write(np.full((20, 100), 7.0, dtype="float32"), 1)
    far = tmp_path / "far.tif"                           # nowhere near the grid
    with rasterio.open(far, "w", driver="GTiff", height=2, width=2, count=1, dtype="float32",
                       transform=from_origin(5000, 5000, 1, 1), nodata=-9999.0) as ds:
        ds.write(np.zeros((2, 2), dtype="float32"), 1)
    g = _grid()
    pkg = prepare(g, [base, far, patch], xy_unit_m=1.0, z_unit_m=1.0)
    on_patch = (g.xy[..., 0] > 51) & (g.xy[..., 0] < 99) & (np.abs(g.xy[..., 1]) < 4)
    assert on_patch.any() and np.allclose(pkg.elevation[on_patch], 7.0)
    assert np.allclose(pkg.elevation[np.abs(g.xy[..., 1]) > 6], 10.0)
    paths = write_package(pkg, tmp_path / "out", terrain=[base, far, patch])
    assert {"elevation_1", "elevation_2"} <= set(paths) and "elevation_3" not in paths
    with rasterio.open(paths["elevation_2"]) as ds:
        assert ds.res == (0.5, 0.5) and float(ds.read(1).max()) == 7.0


def test_prepare_fine_grid_still_finds_coarse_cells(tmp_path: Path) -> None:
    """Sections 1 unit apart over model cells 10 units apart: the default search reach follows
    the cell spacing, so every section still gets a water surface."""
    terrain = _raster(tmp_path / "z.tif", lambda x, y: 0.0 * x)
    g = build_grid(LineString([(10, 0), (190, 0)]), width=10.0, ni=181, nj=3)
    cells = np.array([[x, 0.0] for x in np.arange(5.0, 200.0, 10.0)])
    flow = FlowState(discharge=1.0, cell_xy=cells, wse=np.full(len(cells), 2.0))
    pkg = prepare(g, terrain, xy_unit_m=1.0, z_unit_m=1.0, flow=flow)
    assert pkg.wse is not None and np.isfinite(pkg.wse[:, 1]).all()
    assert pkg.stage_downstream == 2.0 and pkg.stage_upstream == 2.0
    tight = prepare(g, terrain, xy_unit_m=1.0, z_unit_m=1.0, flow=flow, wse_max_dist=1.0)
    assert tight.wse is not None and not np.isfinite(tight.wse[:, 1]).all()


def test_stage_from_nearest_section_inside_the_end(tmp_path: Path) -> None:
    """Cells stop short of the grid ends: the stages come from the nearest sections that have
    a water surface, but not from farther than twice the search reach."""
    terrain = _raster(tmp_path / "z.tif", lambda x, y: 0.0 * x)
    g = build_grid(LineString([(10, 0), (190, 0)]), width=10.0, ni=181, nj=3)
    cells = np.array([[x, 0.0] for x in np.arange(14.0, 187.0, 1.0)])
    flow = FlowState(discharge=1.0, cell_xy=cells, wse=3.0 - 0.01 * cells[:, 0])
    pkg = prepare(g, terrain, xy_unit_m=1.0, z_unit_m=1.0, flow=flow, wse_max_dist=1.5)
    assert pkg.wse is not None and not np.isfinite(pkg.wse[0]).any()
    assert pkg.stage_upstream is not None and pkg.stage_downstream is not None
    assert math.isclose(pkg.stage_upstream, 3.0 - 0.14, abs_tol=1e-9)
    assert math.isclose(pkg.stage_downstream, 3.0 - 1.86, abs_tol=1e-9)
    far = prepare(g, terrain, xy_unit_m=1.0, z_unit_m=1.0, flow=flow, wse_max_dist=0.6)
    assert far.stage_upstream is None and far.stage_downstream is None

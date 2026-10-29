from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq
import pytest
import rasterio
from numpy.typing import NDArray
from rasterio import Affine
from rasterio.transform import from_origin
from shapely.geometry import MultiPolygon

from flowfield2d.results import (
    Fields,
    cell_table_from_results,
    cells_table,
    froude,
    mask_fields,
    nesting_violations,
    read_fields,
    spike_mask,
    to_si,
    wet_mask,
    wet_polygon,
    write_cog,
    write_parquet,
)

CRS = "EPSG:3857"
NODATA = -9999.0
T4 = from_origin(0, 4, 1, 1)


def _write(path: Path, a: NDArray[Any], transform: Affine = T4, crs: str = CRS) -> Path:
    with rasterio.open(path, "w", driver="GTiff", height=a.shape[0], width=a.shape[1], count=1,
                       dtype="float32", crs=crs, nodata=NODATA, transform=transform) as ds:
        ds.write(a.astype("f4"), 1)
    return path


def _triple(tmp_path: Path, transform_wse: Affine = T4) -> tuple[Path, Path, Path]:
    depth = np.full((4, 4), 2.0)
    depth[0, 0] = NODATA
    depth[3, 3] = 0.0
    speed = np.full((4, 4), 1.0)
    speed[1, 1] = NODATA
    wse = np.full((4, 4), 100.0)
    return (_write(tmp_path / "d.tif", depth), _write(tmp_path / "v.tif", speed),
            _write(tmp_path / "w.tif", wse, transform=transform_wse))


def _fields(unit_m: float = 1.0) -> Fields:
    depth = np.array([[1.0, 2.0, np.nan], [0.0, 4.0, 1.0]])
    speed = np.array([[1.0, 2.0, 3.0], [1.0, 2.0, np.nan]])
    wse = np.array([[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]])
    return Fields(depth, speed, wse, from_origin(100, 200, 2, 2), CRS, unit_m)


def test_read_fields_nodata_to_nan_and_units(tmp_path: Path) -> None:
    f = read_fields(*_triple(tmp_path), unit_m=0.5)
    assert f.depth.shape == (4, 4) and f.depth.dtype == np.float64
    assert np.isnan(f.depth[0, 0]) and np.isnan(f.speed[1, 1])
    assert f.depth[3, 3] == 0.0 and f.depth[2, 2] == 2.0       # not converted yet
    assert f.unit_m == 0.5
    assert f.transform == T4
    assert "3857" in f.crs                                    # WKT of the raster CRS


def test_read_fields_mismatch_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        read_fields(*_triple(tmp_path, transform_wse=from_origin(1, 4, 1, 1)), unit_m=1.0)
    d, v, w = _triple(tmp_path)
    _write(tmp_path / "w5.tif", np.full((5, 4), 1.0))
    with pytest.raises(ValueError):
        read_fields(d, v, tmp_path / "w5.tif", unit_m=1.0)
    _write(tmp_path / "w4326.tif", np.full((4, 4), 1.0), crs="EPSG:4326")
    with pytest.raises(ValueError):
        read_fields(d, v, tmp_path / "w4326.tif", unit_m=1.0)


def test_to_si_scales() -> None:
    f = _fields(unit_m=0.5)
    s = to_si(f)
    assert s.unit_m == 1.0
    assert s.depth[0, 1] == 1.0 and s.speed[0, 2] == 1.5 and s.wse[1, 2] == 7.5
    assert np.isnan(s.depth[0, 2])
    assert s.transform == f.transform and s.crs == f.crs
    assert to_si(s) is s                                      # no-op when already SI


def test_spike_mask_flags_spikes_and_neighbours() -> None:
    depth = np.full((12, 12), 1.0)
    depth[5, 5] = 500.0
    depth[8, 2] = 80.0
    depth[0, 0] = np.nan
    bad = spike_mask(depth, jump=10.0)
    expected = np.zeros((12, 12), dtype=bool)
    for r, c in ((5, 5), (8, 2)):
        expected[r, c] = True
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            expected[r + dr, c + dc] = True
    assert bad.dtype == np.bool_ and np.array_equal(bad, expected)
    assert not bad[0, 0]
    assert not spike_mask(np.full((12, 12), 1.0), jump=10.0).any()
    assert spike_mask(depth, jump=10.0, dilate=0).sum() == 2
    assert not spike_mask(depth, jump=1000.0).any()           # jump respected


def test_mask_fields() -> None:
    f = _fields()
    bad = np.zeros((2, 3), dtype=bool)
    bad[1, 1] = True
    m = mask_fields(f, bad)
    assert np.isnan(m.depth[1, 1]) and np.isnan(m.speed[1, 1]) and np.isnan(m.wse[1, 1])
    assert m.depth[0, 0] == 1.0 and f.depth[1, 1] == 4.0      # input untouched


def test_froude() -> None:
    fr = froude(np.array([1.0, 2.0, 1.0, 1.0]), np.array([1.0, 0.5, 0.0, np.nan]), g=10.0)
    assert fr[0] == pytest.approx(1.0 / np.sqrt(10.0))
    assert fr[1] == pytest.approx(2.0 / np.sqrt(5.0))
    assert np.isnan(fr[2]) and np.isnan(fr[3])


def test_wet_mask_and_polygon() -> None:
    depth = np.array([[0.5, 0.6, 0.0, 0.0],
                      [0.4, 0.0, 0.0, 0.0],
                      [0.0, 0.0, 0.0, 0.02],
                      [np.nan, 0.0, 0.0, 0.3]])
    wet = wet_mask(depth, 0.05)
    assert wet.sum() == 4 and not wet[2, 3] and not wet[3, 0]
    mp = wet_polygon(wet, from_origin(0, 8, 2, 2))
    assert isinstance(mp, MultiPolygon) and len(mp.geoms) == 2
    assert mp.area == pytest.approx(4 * 4.0)
    one = wet_polygon(wet_mask(depth, 0.45), from_origin(0, 8, 2, 2))
    assert isinstance(one, MultiPolygon) and len(one.geoms) == 1
    assert wet_polygon(np.zeros((4, 4), dtype=bool), from_origin(0, 8, 2, 2)) is None


def test_nesting_violations() -> None:
    lower = np.array([[True, True, False], [False, True, False]])
    higher = np.array([[True, False, False], [False, False, True]])
    assert nesting_violations(lower, higher) == 2
    assert nesting_violations(lower, lower) == 0


def test_write_cog(tmp_path: Path) -> None:
    a = np.arange(64 * 64, dtype=np.float64).reshape(64, 64)
    a[3, 4] = np.nan
    out = write_cog(a, tmp_path / "sub" / "x.tif", from_origin(0, 64, 1, 1), CRS)
    assert out.is_file()
    with rasterio.open(out) as ds:
        assert ds.driver == "GTiff" and ds.dtypes[0] == "float32" and ds.nodata == NODATA
        assert ds.crs.to_epsg() == 3857 and ds.transform == from_origin(0, 64, 1, 1)
        got = ds.read(1)
        assert ds.overviews(1) or ds.profile.get("tiled")
        assert ds.profile.get("compress", "").lower() == "deflate"
    assert got[3, 4] == NODATA
    good = np.isfinite(a)
    assert np.array_equal(got[good], a[good].astype(np.float32))


def test_cells_table() -> None:
    f = _fields()
    mask = np.isfinite(f.depth) & (f.depth > 0)
    t = cells_table(f, mask, g=10.0)
    assert list(t) == ["cell_id", "x", "y", "depth_m", "vel_mps", "wse_m", "froude"]
    assert t["cell_id"].dtype == np.int64
    assert t["cell_id"].tolist() == [0, 1, 4, 5]              # row * width + col, row-major
    assert t["x"].tolist() == [101.0, 103.0, 103.0, 105.0]    # pixel centres
    assert t["y"].tolist() == [199.0, 199.0, 197.0, 197.0]
    assert t["depth_m"].tolist() == [1.0, 2.0, 4.0, 1.0]
    assert t["vel_mps"][:3].tolist() == [1.0, 2.0, 2.0] and np.isnan(t["vel_mps"][3])
    assert t["wse_m"].tolist() == [10.0, 11.0, 14.0, 15.0]
    assert t["froude"][0] == pytest.approx(1.0 / np.sqrt(10.0))
    assert t["froude"][2] == pytest.approx(2.0 / np.sqrt(40.0))
    assert np.isnan(t["froude"][3])
    with pytest.raises(ValueError):
        cells_table(_fields(unit_m=0.3048), mask)


def test_write_parquet_roundtrip(tmp_path: Path) -> None:
    f = _fields()
    t = cells_table(f, np.ones((2, 3), dtype=bool))
    out = write_parquet(t, tmp_path / "p" / "cells.parquet")
    back = pq.read_table(out)
    assert back.column_names == list(t)
    assert back.num_rows == 6
    assert back.column("cell_id").to_pylist() == list(range(6))
    got = np.asarray(back.column("depth_m").to_numpy(zero_copy_only=False), dtype=np.float64)
    assert np.array_equal(np.isnan(got), np.isnan(t["depth_m"]))
    assert np.array_equal(got[~np.isnan(got)], t["depth_m"][~np.isnan(t["depth_m"])])


class _FakeNoSpeed:
    """Minimal stand-in for the `Results` protocol (no face speeds)."""

    def areas(self) -> list[str]:
        return ["a"]

    def time_days(self) -> NDArray[np.float64]:
        return np.array([0.0, 1.0])

    def cell_coordinates(self, area: str) -> NDArray[np.float64]:
        return np.array([[0.0, 0.0], [10.0, 0.0], [20.0, 0.0], [30.0, 0.0]])

    def cell_depth(self, area: str, t: int) -> NDArray[np.float64]:
        return np.array([2.0, 0.0, 0.05, 1.0]) * (t + 1)

    def cell_wse(self, area: str, t: int, min_depth: float = 0.0) -> NDArray[np.float64]:
        d = self.cell_depth(area, t)
        return np.where(d > min_depth, d + 100.0, np.nan)

    def cell_wse_series(self, area: str, cells: Sequence[int], min_depth: float = 0.0
                        ) -> NDArray[np.float64]:
        raise NotImplementedError

    def boundary_flow(self, area: str, line: str, tol: float) -> NDArray[np.float64]:
        raise NotImplementedError

    def boundary_lines(self) -> dict[str, Any]:
        return {}


class _FakeResults(_FakeNoSpeed):
    """The protocol plus the optional `cell_max_face_speed`."""

    def cell_max_face_speed(self, area: str, t: int) -> NDArray[np.float64]:
        return np.array([3.0, 0.0, 1.0, 2.0])


def test_cell_table_from_results() -> None:
    t = cell_table_from_results(_FakeResults(), "a", 1, unit_m=0.5, min_depth=0.1)
    assert list(t) == ["cell_id", "x", "y", "depth_m", "vel_mps", "wse_m", "froude"]
    assert t["cell_id"].tolist() == [0, 1, 2, 3] and t["cell_id"].dtype == np.int64
    assert t["x"].tolist() == [0.0, 10.0, 20.0, 30.0]          # CRS units, not converted
    assert t["y"].tolist() == [0.0, 0.0, 0.0, 0.0]
    assert t["depth_m"][0] == 2.0 and t["depth_m"][3] == 1.0     # 4 * 0.5, 2 * 0.5
    assert np.isnan(t["depth_m"][1]) and np.isnan(t["depth_m"][2])   # 0.0 and 0.1 <= min_depth
    assert t["vel_mps"][0] == 1.5 and np.isnan(t["vel_mps"][1])
    assert t["wse_m"][0] == 52.0 and np.isnan(t["wse_m"][1])
    assert t["froude"][0] == pytest.approx(1.5 / np.sqrt(9.80665 * 2.0))
    no_speed = cell_table_from_results(_FakeNoSpeed(), "a", 0, unit_m=1.0)
    assert np.isnan(no_speed["vel_mps"]).all() and no_speed["depth_m"][0] == 2.0
    assert np.isnan(no_speed["froude"]).all()

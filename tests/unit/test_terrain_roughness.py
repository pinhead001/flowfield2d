import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from rasdrive.roughness import map_classes, roughness_from_classes
from rasdrive.terrain import TerrainMeta, clip_mosaic, read_sidecar, void_fraction

CRS = "EPSG:3857"


def _tif(path: Path, data: np.ndarray, x0: float, y0: float, res: float = 1.0,
         nodata: float | None = -9999.0, crs: str = CRS) -> Path:
    with rasterio.open(path, "w", driver="GTiff", height=data.shape[0], width=data.shape[1],
                       count=1, dtype=data.dtype, crs=crs, nodata=nodata,
                       transform=from_origin(x0, y0, res, res)) as ds:
        ds.write(data, 1)
    return path


def test_clip_mosaic_two_tiles(tmp_path: Path) -> None:
    a = _tif(tmp_path / "a.tif", np.full((4, 4), 1.0, "f4"), 0, 4)
    b = _tif(tmp_path / "b.tif", np.full((4, 4), 2.0, "f4"), 4, 4)
    out = clip_mosaic([a, b], (2.0, 1.0, 6.0, 3.0), tmp_path / "out.tif")
    with rasterio.open(out) as ds:
        arr = ds.read(1)
        assert arr.shape == (2, 4) and ds.crs.to_string() == CRS
        assert arr[:, :2].tolist() == [[1, 1], [1, 1]] and arr[:, 2:].tolist() == [[2, 2], [2, 2]]
        assert ds.res == (1.0, 1.0)


def test_clip_mosaic_refuses_mixed_crs_or_resolution(tmp_path: Path) -> None:
    a = _tif(tmp_path / "a.tif", np.ones((4, 4), "f4"), 0, 4)
    b = _tif(tmp_path / "b.tif", np.ones((4, 4), "f4"), 4, 4, crs="EPSG:4326")
    c = _tif(tmp_path / "c.tif", np.ones((2, 2), "f4"), 4, 4, res=2.0)
    with pytest.raises(ValueError, match="CRS"):
        clip_mosaic([a, b], (0, 0, 8, 4), tmp_path / "o1.tif")
    with pytest.raises(ValueError, match="resolution"):
        clip_mosaic([a, c], (0, 0, 8, 4), tmp_path / "o2.tif")


def test_sidecar_and_void_fraction(tmp_path: Path) -> None:
    p = tmp_path / "dem.json"
    p.write_text(json.dumps({"crs": CRS, "horizontal_units": "m", "vertical_units": "m",
                             "vertical_datum": "D1"}))
    assert read_sidecar(p) == TerrainMeta(CRS, "m", "m", "D1")
    p.write_text(json.dumps({"crs": CRS}))
    with pytest.raises(ValueError, match="vertical_datum"):
        read_sidecar(p)
    wet = np.array([[True, True], [True, False]])
    void = np.array([[True, False], [False, True]])
    assert void_fraction(void, wet) == pytest.approx(1 / 3)
    assert void_fraction(void, np.zeros((2, 2), bool)) == 0.0


def test_map_classes() -> None:
    classes = np.array([[1, 2], [255, 3]], dtype="u1")
    n = map_classes(classes, {1: 0.03, 2: 0.08, 3: 0.12}, nodata=255)
    assert n[0].tolist() == pytest.approx([0.03, 0.08]) and np.isnan(n[1, 0])
    with pytest.raises(ValueError, match="7"):
        map_classes(np.array([[1, 7]]), {1: 0.03})
    with pytest.raises(ValueError):
        map_classes(classes, {1: 0.03, 2: -0.1, 3: 0.1}, nodata=255)


def test_roughness_raster_keeps_grid(tmp_path: Path) -> None:
    src = _tif(tmp_path / "lc.tif", np.array([[1, 2], [2, 0]], dtype="u1"), 10, 20, nodata=0)
    out = roughness_from_classes(src, {1: 0.035, 2: 0.1}, tmp_path / "n.tif")
    with rasterio.open(out) as ds, rasterio.open(src) as s:
        n = ds.read(1)
        assert ds.transform == s.transform and ds.crs == s.crs and ds.dtypes[0] == "float32"
        assert n[0].tolist() == pytest.approx([0.035, 0.1]) and np.isnan(n[1, 1])

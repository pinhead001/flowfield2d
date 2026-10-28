"""post.rasters: priority mosaic of per-domain rasters onto one snapped grid, written as a sparse
tiled GeoTIFF with overviews (synthetic rasters only)."""

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from flowfield2d.post.rasters import Grid, Source, mosaic, snapped_grid

CRS = "EPSG:3857"
NODATA = -9999.0


def _tif(path: Path, data: np.ndarray, x0: float, y0: float, res: float = 1.0,
         crs: str = CRS) -> Path:
    with rasterio.open(path, "w", driver="GTiff", height=data.shape[0], width=data.shape[1],
                       count=1, dtype="float32", crs=crs, nodata=NODATA,
                       transform=from_origin(x0, y0, res, res)) as ds:
        ds.write(data.astype("float32"), 1)
    return path


def test_snapped_grid_expands_outward_to_the_lattice() -> None:
    g = snapped_grid((0.4, 0.3, 6.6, 4.1), pixel=1.0, crs=CRS)
    assert isinstance(g, Grid)
    assert (g.transform.c, g.transform.f) == (0.0, 5.0)          # left, top on the lattice
    assert (g.width, g.height) == (7, 5) and g.crs == CRS
    assert g.transform.a == 1.0 and g.transform.e == -1.0
    assert g.bounds == (0.0, 0.0, 7.0, 5.0)
    g2 = snapped_grid((0.0, 0.0, 7.0, 5.0), pixel=2.0, crs=CRS)
    assert (g2.width, g2.height) == (4, 3) and g2.bounds == (0.0, 0.0, 8.0, 6.0)
    g3 = snapped_grid((10.5, 10.5, 12.0, 12.0), pixel=1.0, crs=CRS, origin=(0.5, 0.5))
    assert g3.bounds == (10.5, 10.5, 12.5, 12.5) and (g3.width, g3.height) == (2, 2)
    with pytest.raises(ValueError):
        snapped_grid((0, 0, 1, 1), pixel=0.0, crs=CRS)
    with pytest.raises(ValueError):
        snapped_grid((2, 0, 1, 1), pixel=1.0, crs=CRS)


def test_mosaic_first_source_wins_inside_its_area(tmp_path: Path) -> None:
    a = _tif(tmp_path / "a.tif", np.full((4, 4), 1.0), 0, 4)      # x 0..4, y 0..4
    b = _tif(tmp_path / "b.tif", np.full((4, 4), 2.0), 3, 5)      # x 3..7, y 1..5
    out = tmp_path / "m.tif"
    grid = mosaic([Source(a, area=box(0, 0, 5, 5)), Source(b, area=box(4, 0, 8, 6))], out,
                  pixel=1.0, nodata=NODATA)
    assert grid.bounds == (0.0, 0.0, 7.0, 5.0) and (grid.width, grid.height) == (7, 5)
    with rasterio.open(out) as ds:
        assert ds.crs.to_string() == CRS and ds.nodata == NODATA and ds.dtypes[0] == "float32"
        assert ds.res == (1.0, 1.0) and ds.is_tiled and ds.compression is not None
        m = ds.read(1)
        v = {xy: m[ds.index(*xy)] for xy in [(1.5, 1.5), (3.5, 3.5), (4.5, 3.5), (4.5, 0.5),
                                              (6.5, 4.5), (0.5, 4.5), (6.5, 0.5)]}
    assert v[(1.5, 1.5)] == 1.0                                  # a only
    assert v[(3.5, 3.5)] == 1.0                                  # overlap, inside a's area
    assert v[(4.5, 3.5)] == 2.0                                  # overlap, inside b's area
    assert v[(4.5, 0.5)] == NODATA                               # b's area but b has no data
    assert v[(6.5, 4.5)] == 2.0                                  # b only
    assert v[(0.5, 4.5)] == NODATA and v[(6.5, 0.5)] == NODATA  # no source


def test_mosaic_without_areas_takes_the_first_valid_source(tmp_path: Path) -> None:
    za = np.full((4, 4), 1.0)
    za[0, :] = NODATA                                            # a's top row is empty
    a = _tif(tmp_path / "a.tif", za, 0, 4)
    b = _tif(tmp_path / "b.tif", np.full((4, 4), 2.0), 0, 4)
    out = tmp_path / "m.tif"
    mosaic([Source(a), Source(b)], out, pixel=1.0, nodata=NODATA)
    with rasterio.open(out) as ds:
        m = ds.read(1)
    assert m.shape == (4, 4) and m[0].tolist() == [2.0] * 4 and m[1].tolist() == [1.0] * 4


def test_mosaic_masks_values_above_max_and_snaps_offset_sources(tmp_path: Path) -> None:
    za = np.full((4, 4), 1.0)
    za[2, 2] = 500.0                                             # a map spike
    a = _tif(tmp_path / "a.tif", za, 0.3, 4.3)                  # grid not on the lattice
    out = tmp_path / "m.tif"
    grid = mosaic([Source(a, max_value=100.0)], out, pixel=1.0, nodata=NODATA)
    assert grid.bounds == (0.0, 0.0, 5.0, 5.0)
    with rasterio.open(out) as ds:
        m = ds.read(1)
        assert ds.bounds == (0.0, 0.0, 5.0, 5.0)
    assert set(np.unique(m).tolist()) == {NODATA, 1.0}
    assert (m == 1.0).sum() == 15                                # 16 cells minus the spike


def test_mosaic_coarser_pixel_and_overviews(tmp_path: Path) -> None:
    a = _tif(tmp_path / "a.tif", np.arange(64, dtype=float).reshape(8, 8), 0, 8)
    out = tmp_path / "m.tif"
    grid = mosaic([Source(a)], out, pixel=2.0, nodata=NODATA, overviews=(2, 4))
    assert (grid.width, grid.height) == (4, 4)
    with rasterio.open(out) as ds:
        assert ds.overviews(1) == [2, 4]
        m = ds.read(1)
    assert m.shape == (4, 4) and np.isfinite(m).all() and (m != NODATA).all()


def test_mosaic_source_spanning_several_block_strips(tmp_path: Path) -> None:
    za = np.arange(40 * 40, dtype=float).reshape(40, 40)
    za[7, :] = NODATA                                            # a nodata row across strips
    a = _tif(tmp_path / "a.tif", za, 5, 45)                      # window not block aligned
    b = _tif(tmp_path / "b.tif", np.full((40, 40), -1.0), 5, 45)  # fills what a left empty
    out = tmp_path / "m.tif"
    mosaic([Source(a), Source(b)], out, pixel=1.0, nodata=NODATA, blocksize=16)
    with rasterio.open(out) as ds:
        assert ds.block_shapes == [(16, 16)]
        m = ds.read(1)
    assert m.shape == (40, 40)
    expect = za.copy()
    expect[7, :] = -1.0
    assert np.array_equal(m, expect.astype("float32"))


def test_mosaic_refuses_mixed_crs_or_no_sources(tmp_path: Path) -> None:
    a = _tif(tmp_path / "a.tif", np.ones((2, 2)), 0, 2)
    b = _tif(tmp_path / "b.tif", np.ones((2, 2)), 0, 2, crs="EPSG:4326")
    with pytest.raises(ValueError, match="CRS"):
        mosaic([Source(a), Source(b)], tmp_path / "m.tif", pixel=1.0)
    with pytest.raises(ValueError):
        mosaic([], tmp_path / "m.tif", pixel=1.0)
    assert not (tmp_path / "m.tif").exists()

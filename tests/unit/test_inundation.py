import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import shape

from flowfield2d.post.inundation import inundation_polygons, write_geojson


def _depth(tmp_path: Path) -> Path:
    d = np.array([[0.0, 0.5, 0.6, 0.0],
                  [0.0, 0.4, 0.0, 0.0],
                  [0.0, 0.0, 0.0, 0.02],
                  [-9999.0, 0.0, 0.0, 0.3]], dtype="f4")
    p = tmp_path / "depth.tif"
    with rasterio.open(p, "w", driver="GTiff", height=4, width=4, count=1, dtype="float32",
                       crs="EPSG:3857", nodata=-9999.0, transform=from_origin(0, 4, 1, 1)) as ds:
        ds.write(d, 1)
    return p


def test_polygons_by_threshold(tmp_path: Path) -> None:
    polys, crs = inundation_polygons(_depth(tmp_path), min_depth=0.05)
    assert crs == "EPSG:3857"
    areas = sorted(round(p.area, 6) for p in polys)
    assert areas == [1.0, 3.0]                        # 3-cell blob top-left, 1 cell bottom-right
    assert sum(p.area for p in inundation_polygons(_depth(tmp_path), min_depth=0.0)[0]) == 5.0
    big = inundation_polygons(_depth(tmp_path), min_depth=0.05, min_area=2.0)[0]
    assert [p.area for p in big] == [3.0]


def test_write_geojson_roundtrip(tmp_path: Path) -> None:
    polys, crs = inundation_polygons(_depth(tmp_path), min_depth=0.05)
    out = write_geojson(polys, tmp_path / "inund.geojson", crs=crs,
                        properties={"scenario_id": "s1"})
    fc = json.loads(out.read_text())
    assert fc["type"] == "FeatureCollection" and len(fc["features"]) == 2
    assert fc["crs"] == {"type": "name", "properties": {"name": "EPSG:3857"}}
    f0 = fc["features"][0]
    assert f0["properties"]["scenario_id"] == "s1" and shape(f0["geometry"]).area > 0
    with pytest.raises(ValueError):
        inundation_polygons(_depth(tmp_path), min_depth=-1.0)

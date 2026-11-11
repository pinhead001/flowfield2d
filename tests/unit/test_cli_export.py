import json
import zipfile
from pathlib import Path

import h5py
import numpy as np
import rasterio
from rasterio.transform import from_origin
from typer.testing import CliRunner

from flowfield2d.cli import app

from .test_export_iric_project import DEFINITION, _template
from .test_results_series import _result

runner = CliRunner()


def _inputs(tmp_path: Path) -> list[str]:
    """Terrain over the two-cell result fixture ([0, 2] x [0, 1], feet) and a line through it."""
    with rasterio.open(tmp_path / "z.tif", "w", driver="GTiff", height=30, width=40, count=1,
                       dtype="float32", transform=from_origin(-1, 2, 0.1, 0.1)) as ds:
        ds.write(np.full((30, 40), 99.0, dtype="float32"), 1)
    (tmp_path / "line.wkt").write_text("LINESTRING (0.2 0.5, 1.8 0.5)")
    res = _result(tmp_path)
    with h5py.File(res, "a") as f:
        f.create_dataset("/Results/Output Blocks/Base Output/2D Flow Areas/Mesh/Face Velocity",
                         data=np.full((3, 8), 0.5, dtype="f4"))
    return ["export", "iric", "--terrain", str(tmp_path / "z.tif"),
            "--centerline", str(tmp_path / "line.wkt"), "--width", "0.8", "--ni", "5",
            "--nj", "3", "--xy-unit", "foot", "--z-unit", "foot", "--manning-n", "0.03",
            "--results", str(res), "--model-unit", "foot", "--inflow-line", "Inflow",
            "--tol", "0.01", "--time-index", "1"]


def test_export_iric_files(tmp_path: Path) -> None:
    out = tmp_path / "out"
    r = runner.invoke(app, [*_inputs(tmp_path), "--out", str(out), "--drag-depth", "local"])
    assert r.exit_code == 0, r.output
    assert {p.name for p in out.iterdir()} == {"grid.csv", "elevation.tif", "wse.csv",
                                               "summary.json"}
    info = json.loads((out / "summary.json").read_text())
    assert abs(info["discharge_cms"] - 5.0 * 0.3048**3) < 1e-12
    assert abs(info["stage_upstream_m"] - 101.0 * 0.3048) < 1e-6
    assert abs(info["stage_downstream_m"] - 103.0 * 0.3048) < 1e-6
    assert info["node_attributes"] == ["Elevation", "roughness"]
    head = (out / "grid.csv").read_text().splitlines()
    assert head[1] == "5,3,1"
    first = head[3].split(",")
    assert abs(float(first[3]) - 0.2 * 0.3048) < 1e-9 and abs(float(first[6]) - 99 * 0.3048) < 1e-5


def test_export_iric_project(tmp_path: Path) -> None:
    out = tmp_path / "out"
    (tmp_path / "definition.xml").write_text(DEFINITION)
    tmpl = _template(tmp_path)
    r = runner.invoke(app, [*_inputs(tmp_path), "--out", str(out), "--template", str(tmpl),
                            "--definition", str(tmp_path / "definition.xml"),
                            "--condition", "FM_HydAttWSType=1", "--condition", "FM_HydAttWS2=7.5"])
    assert r.exit_code == 0, r.output
    with zipfile.ZipFile(out / "project.ipro") as z:
        z.extract("Case1.cgn", tmp_path / "x")
    with h5py.File(tmp_path / "x" / "Case1.cgn") as f:
        assert f["iRIC/iRICZone/ data"][()].tolist() == [[5, 3], [4, 2], [0, 0]]
        q = f["iRIC/CalculationConditions/FM_HydAttQ/Value/ data"][0]
        assert abs(q - 5.0 * 0.3048**3) < 1e-12
        assert f["iRIC/CalculationConditions/FM_HydAttCDType/Value/ data"][0] == 0
        assert f["iRIC/CalculationConditions/FM_HydAttWSType/Value/ data"][0] == 1
        assert f["iRIC/CalculationConditions/FM_HydAttWS2/Value/ data"][0] == 7.5   # overrides


def test_export_iric_bad_arguments(tmp_path: Path) -> None:
    args = _inputs(tmp_path)
    bad_unit = [a if a != "foot" else "furlong" for a in args]
    assert runner.invoke(app, [*bad_unit, "--out", str(tmp_path / "o")]).exit_code != 0
    wide = [a if a != "0.8" else "50" for a in args]            # grid runs off the terrain
    r = runner.invoke(app, [*wide, "--out", str(tmp_path / "o")])
    assert r.exit_code != 0 and "no terrain value" in r.output


def test_export_iric_bad_condition(tmp_path: Path) -> None:
    (tmp_path / "definition.xml").write_text(DEFINITION)
    tmpl = _template(tmp_path)
    for bad in ("FM_HydAttQ", "FM_Nope=1"):
        r = runner.invoke(app, [*_inputs(tmp_path), "--out", str(tmp_path / "o"), "--template",
                                str(tmpl), "--condition", bad])
        assert r.exit_code != 0

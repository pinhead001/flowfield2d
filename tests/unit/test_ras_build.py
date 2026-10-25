"""RasEngine model assembly on a GUI template: layers, perimeter rebuild, split, BCs, plan."""

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import h5py
import numpy as np
import pytest
from shapely.geometry import LineString, Polygon, box

from flowfield2d.engines import BcSpec, ModelSpec, PlanSpec
from flowfield2d.engines.ras2025.bc import payloads
from flowfield2d.engines.ras2025.cli import RasCli
from flowfield2d.engines.ras2025.engine import RasEngine
from flowfield2d.engines.ras2025.split import bc_polylines, rebuild_perimeter
from flowfield2d.engines.ras2025.templates import fingerprints

from .test_ras_bc_writer import HOUR, _bc_full
from .test_ras_engine import FAKE
from .test_ras_layers import _name_attr

# Rectangle 100 x 1000 with 12 outline points, but a coarse 4-point arc (as GUI templates have).
RING = np.array([[0, 0], [50, 0], [100, 0], [100, 250], [100, 500], [100, 750], [100, 1000],
                 [50, 1000], [0, 1000], [0, 750], [0, 500], [0, 250]], dtype="f8")
LAYERS = {"geometry": "gB", "boundary": "bB", "plan": "pB"}
PROJECT_XML = """<Project>
  <PlanAssociations>
    <PlanAssociation Plan="pB" Geometry="gB" BoundaryCondition="bB" />
  </PlanAssociations>
  <GeometryAssociations>
    <GeometryAssociation Geometry="gB" Terrain="t1" N_Values="n1" />
  </GeometryAssociations>
</Project>
"""


def _geometry(path: Path) -> None:
    with h5py.File(path, "w") as f:
        d = f.create_dataset("/Geometry/2D Flow Areas/Polygon", data=RING)
        d.attrs["Count"] = np.array([len(RING)], dtype="i4")
        d.attrs["Start"] = np.array([0], dtype="i4")
        t = f.create_group("/Geometry/Mesh Topology")
        t.create_dataset("Nodes", data=RING[:1])
        a = t.create_dataset("Arc Internal Points", data=RING[[2, 6, 8]])
        a.attrs["Count"] = np.array([3], dtype="i4")
        a.attrs["Start"] = np.array([0], dtype="i4")
        t.create_dataset("Control Points", data=np.array([[50.0, 500.0]]))


def _template(tmp_path: Path) -> Path:
    p = tmp_path / "T"
    for d in ("Geometries", "Boundary Conditions", "Plans", "Results"):
        (p / d).mkdir(parents=True)
    (p / "T.ras").write_text(PROJECT_XML)
    for g in ("gA", "gB"):
        _geometry(p / "Geometries" / f"{g}.h5")
    for b in ("bA", "bB"):
        (tmp_path / b).mkdir()
        src = _bc_full(tmp_path / b)
        with h5py.File(src, "a") as f:     # BC line geometry: Outlet at the bottom, inflows at top
            pl = f.create_dataset("/Boundary Conditions/BC Lines/Polyline", data=np.array(
                [[0, 1], [100, 1], [0, 999], [50, 999], [50, 999], [100, 999]], dtype="f8"))
            pl.attrs["Count"] = np.array([2, 2, 2], dtype="i4")
            pl.attrs["Start"] = np.array([0, 2, 4], dtype="i4")
        shutil.move(str(src), p / "Boundary Conditions" / f"{b}.h5")
    for pl_name in ("pA", "pB"):
        with h5py.File(p / "Plans" / f"{pl_name}.h5", "w") as f:
            f.create_group("Plan Data").attrs["Compute Core Count"] = np.int32(4)
    groups = (("Geometries", "Geometry"), ("Boundary Conditions", "Boundary Conditions"),
              ("Plans", "Plan Data"))
    for folder, group in groups:                            # internal layer names, as RAS writes
        for h in (p / folder).glob("*.h5"):
            with h5py.File(h, "a") as f:
                _name_attr(f.require_group(group), h.stem, 8)
    return p


@pytest.fixture
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RasEngine:
    monkeypatch.setenv("FAKE_RAS_LOG", str(tmp_path / "ras.log"))
    return RasEngine(RasCli([sys.executable, str(FAKE)], timeout_s=60))


def _calls(tmp_path: Path) -> list[list[str]]:
    log = tmp_path / "ras.log"
    return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []


def test_rebuild_perimeter_uses_full_outline(tmp_path: Path) -> None:
    p = _template(tmp_path)
    poly = rebuild_perimeter(p, geometry="gB", boundary="bB")
    assert poly.area == pytest.approx(100 * 1000)
    with h5py.File(p / "Geometries" / "gB.h5", "r") as f:
        t = f["/Geometry/Mesh Topology"]
        assert t["Arc Internal Points"].attrs["Count"].tolist() == [len(RING) - 1]
        assert Polygon(f["/Geometry/2D Flow Areas/Polygon"][:]).area == pytest.approx(1e5)
    with h5py.File(p / "Geometries" / "gA.h5", "r") as f:          # other layer untouched
        assert f["/Geometry/Mesh Topology/Arc Internal Points"].shape == (3, 2)
    assert bc_polylines(p / "Boundary Conditions" / "bB.h5")["Outlet"].coords[:] == [
        (0.0, 1.0), (100.0, 1.0)]


def test_build_full_domain(tmp_path: Path, engine: RasEngine) -> None:
    t = _template(tmp_path)
    base = fingerprints(t)
    model = engine.build_or_verify_model(ModelSpec(t, tmp_path / "run" / "full", None, {}, 9.0,
                                                   layers=LAYERS))
    assert model == tmp_path / "run" / "full" and (model / "T.ras").exists()
    geom = model / "Geometries" / "gB.h5"
    with h5py.File(geom, "r") as f:
        assert f["/Geometry/Mesh Topology/Arc Internal Points"].shape == (len(RING) - 1, 2)
    assert _calls(tmp_path) == [
        ["geometry", "modify", str(geom), "topology.region.cellsize = 9",
         "topology.arc.cellsize = 9"],
        ["geometry", "generate-mesh", str(geom)]]
    after = fingerprints(model)
    assert after["Geometries/gA.h5"] == base["Geometries/gA.h5"]   # unselected layers untouched
    with pytest.raises(FileExistsError):                            # never builds over a model
        engine.build_or_verify_model(ModelSpec(t, model, None, {}, 9.0, layers=LAYERS))


def test_build_subdomain_moves_cut_bc(tmp_path: Path, engine: RasEngine) -> None:
    t = _template(tmp_path)
    cut = LineString([(0, 401), (100, 401)])
    model = engine.build_or_verify_model(ModelSpec(t, tmp_path / "sub", box(-10, 400, 110, 1010),
                                                   {"Outlet": cut}, 6.5, layers=LAYERS))
    with h5py.File(model / "Geometries" / "gB.h5", "r") as f:
        assert Polygon(f["/Geometry/2D Flow Areas/Polygon"][:]).area == pytest.approx(100 * 600)
    assert bc_polylines(model / "Boundary Conditions" / "bB.h5")["Outlet"].coords[:] == [
        (0.0, 401.0), (100.0, 401.0)]
    assert bc_polylines(model / "Boundary Conditions" / "bA.h5")["Outlet"].coords[:] == [
        (0.0, 1.0), (100.0, 1.0)]
    assert _calls(tmp_path)[0][3:] == ["topology.region.cellsize = 6.5",
                                       "topology.arc.cellsize = 6.5"]


def test_build_layer_selection_errors(tmp_path: Path, engine: RasEngine) -> None:
    t = _template(tmp_path)
    with pytest.raises(ValueError, match="one layer"):              # two geometries, none chosen
        engine.build_or_verify_model(ModelSpec(t, tmp_path / "a", None, {}, 9.0))
    with pytest.raises(FileNotFoundError, match="gZ"):
        engine.build_or_verify_model(ModelSpec(t, tmp_path / "b", None, {}, 9.0,
                                               layers={**LAYERS, "geometry": "gZ"}))


def test_write_bcs_on_selected_layer(tmp_path: Path, engine: RasEngine) -> None:
    model = engine.build_or_verify_model(ModelSpec(_template(tmp_path), tmp_path / "m", None, {},
                                                   9.0, layers=LAYERS))
    start = datetime(2000, 1, 1)
    bc = engine.write_bcs(model, BcSpec(start, [0.0, 3600.0, 7200.0], {"Inflow A": [1.0, 2.0, 3.0]},
                                        {"Outlet": 0.002}))
    assert bc == model / "Boundary Conditions" / "bB.h5"
    with h5py.File(bc, "r") as f:
        g = f["/Boundary Conditions/BC Lines/Payloads"]
        assert g["Values"][:3].tolist() == [1.0, 2.0, 3.0]
        a = f["/Boundary Conditions"].attrs
        assert int(a["End Time"]) - int(a["Start Time"]) == 2 * HOUR
    outlet = [p for p in payloads(bc) if p.variable == "Normal Depth"][0]
    assert outlet.constant == pytest.approx(0.002)
    other = model / "Boundary Conditions" / "bA.h5"
    with h5py.File(other, "r") as f:
        assert f["/Boundary Conditions/BC Lines/Payloads/Values"][:4].tolist() == [10, 11, 12, 13]


def test_write_bcs_rejects_bad_slope_before_writing(tmp_path: Path, engine: RasEngine) -> None:
    model = engine.build_or_verify_model(ModelSpec(_template(tmp_path), tmp_path / "m", None, {},
                                                   9.0, layers=LAYERS))
    bc = model / "Boundary Conditions" / "bB.h5"
    before = bc.read_bytes()
    with pytest.raises(ValueError, match="slope"):
        engine.write_bcs(model, BcSpec(datetime(2000, 1, 1), [0.0, 3600.0],
                                       {"Inflow A": [1.0, 2.0]}, {"Outlet": 0.0}))
    assert bc.read_bytes() == before


def test_create_plan_sets_solver_settings(tmp_path: Path, engine: RasEngine) -> None:
    model = engine.build_or_verify_model(ModelSpec(_template(tmp_path), tmp_path / "m", None, {},
                                                   9.0, layers=LAYERS))
    plan = engine.create_plan(model, PlanSpec("3s", "15min", "Explicit"))
    assert plan == model / "Plans" / "pB.h5"
    call = _calls(tmp_path)[-1]
    assert call[:3] == ["plan", "modify", str(plan)]
    assert {"ComputeTimestep = 3s", "BaseOutputInterval = 15min",
            "TimeStepping = Explicit"} <= set(call)


def test_model_unit_m_from_project_units(tmp_path: Path, engine: RasEngine) -> None:
    t = _template(tmp_path)
    for g, units in (("gA", "SI"), ("gB", "USC")):
        with h5py.File(t / "Geometries" / f"{g}.h5", "a") as f:
            f.attrs["Project Units"] = np.bytes_(units)
    assert engine.model_unit_m(t, LAYERS) == pytest.approx(0.3048)
    assert engine.model_unit_m(t, {"geometry": "gA"}) == 1.0
    with h5py.File(t / "Geometries" / "gA.h5", "a") as f:
        f.attrs["Project Units"] = np.bytes_("Furlongs")
    with pytest.raises(ValueError, match="Furlongs"):
        engine.model_unit_m(t, {"geometry": "gA"})


def test_corrupt_layer_selection_raises(tmp_path: Path, engine: RasEngine) -> None:
    model = engine.build_or_verify_model(ModelSpec(_template(tmp_path), tmp_path / "m", None, {},
                                                   9.0, layers=LAYERS))
    (model / "flowfield2d.json").write_text("{not json")
    with pytest.raises(ValueError, match="layer selection"):
        engine.create_plan(model, PlanSpec("3s", "15min", "Explicit"))


def test_multi_ring_area_refused(tmp_path: Path) -> None:
    t = _template(tmp_path)
    with h5py.File(t / "Geometries" / "gB.h5", "a") as f:
        f["/Geometry/2D Flow Areas/Polygon"].attrs["Count"] = np.array([6, 6], dtype="i4")
    with pytest.raises(ValueError, match="one 2D area"):
        rebuild_perimeter(t, geometry="gB")


def test_build_synthesised_model_with_new_outline_terrain_and_names(tmp_path: Path,
                                                                   engine: RasEngine) -> None:
    from flowfield2d.engines.ras2025.templates import associations

    t = _template(tmp_path)
    outline = Polygon([(-50, -100), (150, -100), (150, 1500), (-50, 1500)])
    bcs = {"Outlet": LineString([(-50, -100), (150, -100)]),
           "Inflow A": LineString([(-50, 1500), (150, 1500)])}
    spec = ModelSpec(t, tmp_path / "syn", None, bcs, 30.0, layers=LAYERS, outline=outline,
                     terrain="t3", rename={"geometry": "gC", "boundary": "bC", "plan": "pC"})
    model = engine.build_or_verify_model(spec)
    a = associations(model)
    assert a["plans"]["pC"] == ("gC", "bC") and a["geometries"]["gC"] == ("t3", "n1")
    with h5py.File(model / "Geometries" / "gC.h5", "r") as f:
        assert Polygon(f["/Geometry/2D Flow Areas/Polygon"][:]).area == pytest.approx(outline.area)
    assert bc_polylines(model / "Boundary Conditions" / "bC.h5")["Outlet"].coords[:] == [
        (-50.0, -100.0), (150.0, -100.0)]
    with h5py.File(model / "Geometries" / "gB.h5", "r") as f:   # donor layer untouched
        assert Polygon(f["/Geometry/2D Flow Areas/Polygon"][:]).area == pytest.approx(1e5)
    geom = model / "Geometries" / "gC.h5"
    assert _calls(tmp_path)[-1] == ["geometry", "generate-mesh", str(geom)]
    plan = engine.create_plan(model, PlanSpec("3s", "15min", "Explicit"))   # later steps follow
    assert plan == model / "Plans" / "pC.h5"                                # the renamed layers
    assert engine.write_bcs(model, BcSpec(datetime(2000, 1, 1), [0.0, 3600.0],
                                          {"Inflow A": [1.0, 2.0]}, {})) == (
        model / "Boundary Conditions" / "bC.h5")


def test_outline_and_keep_are_exclusive(tmp_path: Path, engine: RasEngine) -> None:
    t = _template(tmp_path)
    sq = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    with pytest.raises(ValueError, match="outline"):
        engine.build_or_verify_model(ModelSpec(t, tmp_path / "x", sq, {}, 9.0, layers=LAYERS,
                                               outline=sq))

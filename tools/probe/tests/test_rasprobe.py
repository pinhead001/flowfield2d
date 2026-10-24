"""Tests for rasprobe: HDF5 schemas (RAS-style NULLTERM strings), snapshots, smoke runner,
inventory/.NET metadata on a real managed DLL when available, tier rules, report."""
from __future__ import annotations

import json
import shutil
import sys
import textwrap
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import rasprobe  # noqa: E402

h5py = pytest.importorskip("h5py")
np = pytest.importorskip("numpy")
from h5py import h5t  # noqa: E402


def _nullterm(size: int):
    tid = h5t.C_S1.copy()
    tid.set_size(size)
    tid.set_strpad(h5t.STR_NULLTERM)
    return tid


def write_ras_like_bc(path: Path, extra_attr: bool = False) -> None:
    """Mimic a RAS 2025 bc_XX.h5: full-width NULLTERM strings written with mtype == file type."""
    with h5py.File(path, "w") as f:
        g = f.create_group("Boundary Conditions")
        sid = h5py.h5s.create(h5py.h5s.SCALAR)
        for name, text in [(b"Name", b"bc_04"), (b"End Time (DESC)", b"1/29/3000 12:00:00 AM")]:
            tid = _nullterm(len(text))
            aid = h5py.h5a.create(g.id, name, tid, sid)
            aid.write(np.array(text, dtype=f"S{len(text)}"), mtype=tid)
        if extra_attr:
            g.attrs["Added"] = 1
        payloads = g.create_group("BC Lines/Payloads")
        ct = h5t.create(h5t.COMPOUND, 7 + 8)
        ct.insert(b"TS Type", 0, _nullterm(7))
        ct.insert(b"Count", 7, h5t.STD_I64LE)
        did = h5py.h5d.create(payloads.id, b"Time Series Definitions", ct, h5py.h5s.create_simple((1,)))
        rec = np.zeros(1, dtype=[("TS Type", "S7"), ("Count", "<i8")])
        rec["TS Type"], rec["Count"] = b"Regular", 673
        did.write(h5py.h5s.ALL, h5py.h5s.ALL, rec, mtype=ct)
        payloads.create_dataset("Values", data=np.linspace(30, 150, 673), chunks=(673,), compression="gzip")
        payloads.create_dataset("Times", data=np.arange(673, dtype="i8") * 36_000_000_000,
                                chunks=(673,), compression="gzip")


def test_h5schema_captures_nullterm_full_width_and_compound(tmp_path):
    p = tmp_path / "bc_04.h5"
    write_ras_like_bc(p)
    res = rasprobe.h5schema([p])
    info = res["files"]["bc_04.h5"]
    attrs = info["objects"]["/Boundary Conditions"]["attrs"]
    assert attrs["End Time (DESC)"]["type"]["strpad"] == "NULLTERM"
    assert attrs["End Time (DESC)"]["value"] == "1/29/3000 12:00:00 AM"  # last char kept
    assert attrs["End Time (DESC)"]["full_width"] is True
    tsd = info["objects"]["/Boundary Conditions/BC Lines/Payloads/Time Series Definitions"]
    member = tsd["type"]["members"][0]
    assert member["name"] == "TS Type" and member["type"]["size"] == 7
    vals = info["objects"]["/Boundary Conditions/BC Lines/Payloads/Values"]
    assert vals["filters"][0]["name"] == "deflate" and vals["chunks"] == [673]
    assert len(info["full_width_strings"]) == 2


def test_fingerprint_stable_and_diff_detects_changes(tmp_path):
    a, b, c = tmp_path / "a.h5", tmp_path / "b.h5", tmp_path / "c.h5"
    write_ras_like_bc(a)
    write_ras_like_bc(b)
    write_ras_like_bc(c, extra_attr=True)
    sa, sb, sc = (rasprobe.h5schema([p]) for p in (a, b, c))
    fa = sa["files"]["a.h5"]["fingerprint"]
    assert fa == sb["files"]["b.h5"]["fingerprint"]
    assert fa != sc["files"]["c.h5"]["fingerprint"]
    d = rasprobe.h5diff(sa, sc)
    (only,) = d["files"].values()
    assert only["attrs_added"] == ["/Boundary Conditions@Added"]
    assert only["fingerprint_equal"] is False


def test_snapshot_and_snapdiff(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "keep.txt").write_text("a")
    (root / "change.txt").write_text("a")
    (root / "gone.txt").write_text("a")
    before = rasprobe.snapshot(root)
    (root / "change.txt").write_text("b")
    (root / "gone.txt").unlink()
    (root / "sub").mkdir()
    (root / "sub" / "new.txt").write_text("c")
    d = rasprobe.snapdiff(before, rasprobe.snapshot(root))
    assert d == {"added": ["sub/new.txt"], "removed": ["gone.txt"], "modified": ["change.txt"]}


WRITE_H5 = textwrap.dedent("""
    import sys, pathlib, h5py, numpy as np
    out = pathlib.Path(sys.argv[1]) / "Results"; out.mkdir(exist_ok=True)
    rng = np.random.default_rng(None if sys.argv[2] == "random" else 7)
    with h5py.File(out / "result.h5", "w") as f:
        f["Depth"] = rng.random(100)
""")


def make_spec(tmp_path: Path) -> Path:
    seed = tmp_path / "seed"
    (seed / "Geometries").mkdir(parents=True)
    write_ras_like_bc(seed / "Geometries" / "bc_04.h5")
    script = tmp_path / "write_h5.py"
    script.write_text(WRITE_H5)
    py = sys.executable.replace("\\", "/")
    spec = f"""
[vars]
seed = '{seed.as_posix()}'
scratch = '{(tmp_path / "scratch").as_posix()}'
py = '{py}'
script = '{script.as_posix()}'

[[op]]
id = "A_deterministic"
capability = "compute"
argv = ["{{py}}", "{{script}}", "{{project}}", "fixed"]
repeat = 2
compare_glob = "Results/*"
timeout_s = 60
expect = {{ exit_code = 0, no_window = true, created = ["Results/*"] }}

[[op]]
id = "B_named_error"
capability = "compute_error"
argv = ["{{py}}", "-c", "import sys; print('bad boundary BC-1', file=sys.stderr); sys.exit(3)"]
timeout_s = 60
expect = {{ exit_code_nonzero = true, output_contains = "boundary" }}

[[op]]
id = "C_hangs"
capability = "mesh"
argv = ["{{py}}", "-c", "import time; time.sleep(30)"]
timeout_s = 1
expect = {{ exit_code = 0 }}

[[op]]
id = "D_manual"
capability = "mesh"
method = "gui"
manual = "do something in {{project}}"

[[op]]
id = "E_confinement"
capability = "agy_confinement"
fresh_copy = false
pre = [["{{py}}", "-c", "import os; os.makedirs(r'{{opdir}}/repo', exist_ok=True)"]]
snapshot = ["{{opdir}}"]
cwd = "{{opdir}}/repo"
argv = ["{{py}}", "-c", "open('../escape.txt','w').write('x')"]
timeout_s = 60
expect = {{ not_created = ["escape.txt"] }}

[[op]]
id = "F_parallel"
capability = "concurrency"
argv = ["{{py}}", "{{script}}", "{{project}}", "fixed"]
parallel = 2
timeout_s = 60
expect = {{ exit_code = 0 }}

[[op]]
id = "G_random"
capability = "determinism"
argv = ["{{py}}", "{{script}}", "{{project}}", "random"]
repeat = 2
compare_glob = "Results/*"
timeout_s = 60
expect = {{ exit_code = 0 }}

[[op]]
id = "H_edit_bc"
capability = "bc"
method = "h5edit"
argv = ["{{py}}", "-c", "import h5py; f=h5py.File(r'{{project}}/Geometries/bc_04.h5','a'); f['Boundary Conditions'].attrs['Note']=1; f.close()"]
timeout_s = 60
expect = {{ exit_code = 0, modified = ["Geometries/bc_04.h5"] }}
"""
    p = tmp_path / "smoke.toml"
    p.write_text(spec)
    return p


@pytest.fixture(scope="module")
def smoke_run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("smoke")
    out = tmp / "probe" / "smoke"
    recs = rasprobe.smoke(make_spec(tmp), out, only=[], interactive=False)
    return tmp, out, {r["id"]: r for r in recs}


def test_smoke_statuses(smoke_run):
    _tmp, out, r = smoke_run
    assert r["A_deterministic"]["status"] == "pass"
    assert r["A_deterministic"]["determinism"]["identical"] is True
    assert r["B_named_error"]["status"] == "pass"
    assert r["C_hangs"]["status"] == "timeout"
    assert r["D_manual"]["status"] == "skipped-manual"
    assert r["E_confinement"]["status"] == "fail"  # the fake escaped its cwd, as designed
    assert r["F_parallel"]["status"] == "pass" and len(r["F_parallel"]["runs"]) == 2
    det = r["G_random"]["determinism"]
    assert det["identical"] is False and det["max_abs_diff"] > 0
    h5c = r["H_edit_bc"]["h5_changes"]["Geometries/bc_04.h5"]
    (fd,) = h5c["diff"]["files"].values()
    assert fd["attrs_added"] == ["/Boundary Conditions@Note"]
    assert (out / "A_deterministic.json").exists()


def test_suggest_tier_rules():
    def rec(cap, status="pass", method="cli", window=False):
        return {"capability": cap, "status": status, "method": method, "window_seen": window}

    full = [rec(c) for c in rasprobe.CORE_CAPS] + [rec("bc", method="h5edit"), rec("compute_error")]
    assert rasprobe.suggest_tier(full)[0] == "A"
    hybrid = [rec("compute"), rec("compute_error"), rec("mesh", method="gui")]
    assert rasprobe.suggest_tier(hybrid)[0] == "B"
    windowed = [rec("compute", window=True), rec("compute_error")]
    assert rasprobe.suggest_tier(windowed)[0] == "C"


def test_report_from_smoke(smoke_run):
    _tmp, out, _r = smoke_run
    md = rasprobe.report(out.parent)
    assert "## Smoke results" in md and "Suggested tier:" in md
    assert "| compute |" in md


def _managed_dll():
    try:
        import pythonnet  # noqa: F401
    except ImportError:
        return None
    hits = list(Path(sys.modules["pythonnet"].__file__).parent.rglob("Python.Runtime.dll"))
    return hits[0] if hits else None


def test_inventory_and_dotnet(tmp_path):
    ras = tmp_path / "ras"
    ras.mkdir()
    (ras / "ras.runtimeconfig.json").write_text(json.dumps(
        {"runtimeOptions": {"tfm": "net9.0", "framework": {"name": "Microsoft.NETCore.App", "version": "9.0.0"}}}))
    (ras / "ras.deps.json").write_text(json.dumps(
        {"libraries": {"System.CommandLine/2.0.0": {"type": "package"}, "HDF.PInvoke/1.0": {"type": "package"}}}))
    (ras / "appsettings.json").write_text('{"update": "https://updates.example.org/ras2025/feed.json"}')
    dll = _managed_dll()
    if dll:
        shutil.copy(dll, ras / "Python.Runtime.dll")
    inv = rasprobe.inventory(ras)
    s = inv["summary"]
    assert s["cli_frameworks"] == ["System.CommandLine"]
    assert "updates.example.org" in s["hosts"]
    assert s["dotnet_runtimeconfigs"][0]["tfm"] == "net9.0"
    if dll and rasprobe.pefile is not None:
        rec = next(f for f in inv["files"] if f["path"] == "Python.Runtime.dll")
        assert rec["is_dotnet"] is True and rec["version_strings"].get("FileVersion")
    if dll and rasprobe.dnfile is not None:
        dn = rasprobe.dotnet_scan(ras)
        assert dn["assemblies"] and dn["assemblies"][0]["public_types"] > 0


def test_make_terrain(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    out = tmp_path / "tiny.tif"
    rasprobe.make_terrain(out, like=None, epsg=26910, size=64, cell=1.0)
    with rasterio.open(out) as src:
        assert src.nodata == -9999.0 and src.width == 64 and src.crs.to_epsg() == 26910
    out2 = tmp_path / "tiny2.tif"
    rasprobe.make_terrain(out2, like=out, epsg=None, size=32, cell=1.0)
    with rasterio.open(out2) as src:
        assert src.width == 32 and src.crs.to_epsg() == 26910

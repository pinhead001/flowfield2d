"""Warm start: a mesh state read from a result, written as the initial state of a ready-to-run file.

Synthetic files with the layout `plan prepare` and `plan solve` produce (probe 2026-10-25):
  result: /Results/Output Blocks/Base Output/2D Flow Areas/<area>/Cell Depth (n_t, n_cells)
                                                                 /Face Velocity (n_t, n_faces)
  r2r:    /Results/Initial Conditions/2D Flow Areas/<area>/Cell Depth (n_cells,)
                                                        /Face Velocity (n_faces,)
"""

from pathlib import Path

import h5py
import numpy as np
import pytest

from flowfield2d.engines.ras2025.warmstart import MeshState, read_state, write_initial_state

BASE = "/Results/Output Blocks/Base Output/2D Flow Areas/A"
IC = "/Results/Initial Conditions/2D Flow Areas/A"


def _result(path: Path) -> Path:
    with h5py.File(path, "w") as f:
        depth = np.arange(12, dtype=np.float32).reshape(3, 4)
        f.create_dataset(f"{BASE}/Cell Depth", data=depth)
        velocity = -np.arange(15, dtype=np.float32).reshape(3, 5)
        f.create_dataset(f"{BASE}/Face Velocity", data=velocity)
    return path


def _r2r(path: Path, n_cells: int = 4, n_faces: int = 5) -> Path:
    with h5py.File(path, "w") as f:
        zeros = np.zeros(n_cells, dtype=np.float32)
        d = f.create_dataset(f"{IC}/Cell Depth", data=zeros, chunks=True)
        d.attrs["Units"] = np.bytes_(b"ft")
        f.create_dataset(f"{IC}/Face Velocity", data=np.zeros(n_faces, dtype=np.float32))
        f.create_dataset("/Results/Other", data=np.ones(3))
    return path


def test_read_state_at_an_output_index(tmp_path: Path) -> None:
    res = _result(tmp_path / "res.h5")
    s = read_state(res, "A", 1)
    assert isinstance(s, MeshState)
    assert s.cell_depth.tolist() == [4.0, 5.0, 6.0, 7.0]
    assert s.face_velocity.tolist() == [-5.0, -6.0, -7.0, -8.0, -9.0]
    assert read_state(res, "A", -1).cell_depth.tolist() == [8.0, 9.0, 10.0, 11.0]
    with pytest.raises(IndexError):
        read_state(res, "A", 3)
    with pytest.raises(KeyError):
        read_state(res, "B", 0)


def test_write_initial_state_replaces_only_the_initial_conditions(tmp_path: Path) -> None:
    r2r = _r2r(tmp_path / "job.r2r.h5")
    write_initial_state(r2r, "A", read_state(_result(tmp_path / "res.h5"), "A", -1))
    with h5py.File(r2r, "r") as f:
        assert f[f"{IC}/Cell Depth"][()].tolist() == [8.0, 9.0, 10.0, 11.0]
        assert f[f"{IC}/Cell Depth"].dtype == np.float32
        assert f[f"{IC}/Cell Depth"].attrs["Units"] == b"ft"          # attributes kept
        assert f[f"{IC}/Face Velocity"][()].tolist() == [-10.0, -11.0, -12.0, -13.0, -14.0]
        assert f["/Results/Other"][()].tolist() == [1.0, 1.0, 1.0]


def test_write_initial_state_depth_only_zeroes_velocity(tmp_path: Path) -> None:
    r2r = _r2r(tmp_path / "job.r2r.h5")
    with h5py.File(r2r, "r+") as f:
        f[f"{IC}/Face Velocity"][...] = 7.0
    write_initial_state(r2r, "A", MeshState(np.full(4, 2.0), None))
    with h5py.File(r2r, "r") as f:
        assert f[f"{IC}/Cell Depth"][()].tolist() == [2.0] * 4
        assert f[f"{IC}/Face Velocity"][()].tolist() == [0.0] * 5


def test_write_initial_state_rejects_other_meshes_and_bad_values(tmp_path: Path) -> None:
    r2r = _r2r(tmp_path / "job.r2r.h5", n_cells=6)
    state = read_state(_result(tmp_path / "res.h5"), "A", 0)
    with pytest.raises(ValueError, match="cells"):
        write_initial_state(r2r, "A", state)                           # 4 cells vs 6
    r2r5 = _r2r(tmp_path / "five.r2r.h5", n_faces=7)
    with pytest.raises(ValueError, match="faces"):
        write_initial_state(r2r5, "A", state)
    ok = _r2r(tmp_path / "ok.r2r.h5")
    for bad in (np.array([1.0, -0.5, 0.0, 0.0]), np.array([1.0, np.nan, 0.0, 0.0])):
        with pytest.raises(ValueError, match="depth"):
            write_initial_state(ok, "A", MeshState(bad, None))
    with h5py.File(ok, "r") as f:                                      # nothing written on failure
        assert f[f"{IC}/Cell Depth"][()].tolist() == [0.0] * 4
    with pytest.raises(KeyError):
        write_initial_state(ok, "B", state)

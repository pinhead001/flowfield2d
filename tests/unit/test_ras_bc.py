"""BC layer edits on a synthetic file shaped like the probed RAS 2025 BC schema (no real data)."""

from pathlib import Path

import h5py
import numpy as np
import pytest

from flowfield2d.engines.ras2025.bc import (
    BcPayload,
    payloads,
    scale_flow_series,
    set_normal_depth_slope,
)

PAYLOAD_DT = np.dtype([("Name", "S14"), ("Variable", "S12"), ("Enabled", "i1"), ("Mode", "S10"),
                       ("External Connection", "S1"), ("External Path", "S1"),
                       ("Constant", "<f8"), ("Row", "<i4")])
G = "/Boundary Conditions/BC Lines/Payloads"


def _bc(tmp_path: Path) -> Path:
    p = tmp_path / "bc.h5"
    with h5py.File(p, "w") as f:
        g = f.create_group(G)
        g.create_dataset("Payloads", data=np.array([
            (b"Hydraulic Data", b"Normal Depth", 1, b"Constant", b"", b"", 0.001, -1),
            (b"Hydraulic Data", b"Flow", 1, b"TimeSeries", b"", b"", 0.0, 0)], dtype=PAYLOAD_DT))
        g.create_dataset("Times", data=np.arange(5, dtype="<i8") * 36_000_000_000,
                         chunks=(5,), compression="gzip")
        g.create_dataset("Values", data=np.array([10.0, 20, 30, 20, 10]),
                         chunks=(5,), compression="gzip")
    return p


def test_read_payloads(tmp_path: Path) -> None:
    rows = payloads(_bc(tmp_path))
    assert rows == [BcPayload(0, "Normal Depth", "Constant", True, 0.001, -1),
                    BcPayload(1, "Flow", "TimeSeries", True, 0.0, 0)]


def test_scale_flow_series_keeps_layout(tmp_path: Path) -> None:
    p = _bc(tmp_path)
    scale_flow_series(p, 1.5)
    with h5py.File(p, "r") as f:
        v = f[G]["Values"]
        assert v[:].tolist() == [15.0, 30.0, 45.0, 30.0, 15.0]
        assert v.dtype == np.dtype("<f8") and v.chunks == (5,) and v.compression == "gzip"
        assert f[G]["Times"][-1] == 4 * 36_000_000_000
    with pytest.raises(ValueError):
        scale_flow_series(p, 0.0)


def test_set_normal_depth_slope_rewrites_only_that_field(tmp_path: Path) -> None:
    p = _bc(tmp_path)
    set_normal_depth_slope(p, 0.002)
    rows = payloads(p)
    assert rows[0].constant == 0.002 and rows[1] == BcPayload(1, "Flow", "TimeSeries", True, 0.0, 0)
    with h5py.File(p, "r") as f:
        assert f[G]["Payloads"].dtype == PAYLOAD_DT
    set_normal_depth_slope(p, 0.0, allow_invalid=True)          # probe E6b only
    assert payloads(p)[0].constant == 0.0
    with pytest.raises(ValueError):
        set_normal_depth_slope(p, -0.01)


def test_ambiguous_payloads_are_refused(tmp_path: Path) -> None:
    p = _bc(tmp_path)
    with h5py.File(p, "r+") as f:
        arr = f[G]["Payloads"][:]
        arr[1]["Variable"] = b"Normal Depth"
        arr[1]["Mode"] = b"Constant"
        del f[G]["Payloads"]
        f[G].create_dataset("Payloads", data=arr)
    with pytest.raises(ValueError, match="2 normal-depth"):
        set_normal_depth_slope(p, 0.002)
    with pytest.raises(ValueError, match="flow"):
        scale_flow_series(p, 2.0)

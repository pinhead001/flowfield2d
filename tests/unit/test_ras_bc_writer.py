"""BC writer on a synthetic three-line BC file shaped like the probed RAS 2025 layout."""

from datetime import datetime
from pathlib import Path

import h5py
import numpy as np
import pytest

from flowfield2d.engines.ras2025.bc import (
    bc_lines,
    payloads,
    set_normal_depth_slope,
    set_time_window,
    write_flow_series,
)
from flowfield2d.engines.ras2025.h5edit import read_fixed_string, to_ticks
from flowfield2d.engines.ras2025.validate import validate_bc

from .test_ras_bc import PAYLOAD_DT

BC = "/Boundary Conditions"
G = BC + "/BC Lines/Payloads"
HOUR = 36_000_000_000
LINE_DT = np.dtype([("Name", "S25"), ("Enabled", "i1"), ("Start", "<i4"), ("Count", "<i4")])
TSD_DT = np.dtype([("TS Type", "S7"), ("Irregular Time Expressed As", "S8"),
                   ("RTS Interval", "<i8"), ("RTS Interval (DESC)", "S8"), ("Fixed Start", "<i8"),
                   ("Fixed Start (DESC)", "S20"), ("Start (Time)", "<i4"),
                   ("Start (Value)", "<i4"), ("Count", "<i4")])


def _s(obj: h5py.Group, name: str, value: str, size: int) -> None:
    tid = h5py.h5t.C_S1.copy()
    tid.set_size(size)
    tid.set_strpad(h5py.h5t.STR_NULLTERM)
    obj.attrs.create(name, np.array(value.encode(), dtype=f"S{size}"), dtype=h5py.Datatype(tid))


def _bc_full(tmp_path: Path) -> Path:
    """Line 'Outlet': normal depth; lines 'Inflow A' and 'Inflow B': hourly flow series over 3 h."""
    p = tmp_path / "bc.h5"
    with h5py.File(p, "w") as f:
        b = f.create_group(BC)
        b.attrs["Start Time"] = np.int64(630822816000000000)
        _s(b, "Start Time (DESC)", "1/1/2000 12:00:00 AM", 20)
        b.attrs["End Time"] = np.int64(630822816000000000 + 3 * HOUR)
        _s(b, "End Time (DESC)", "1/1/2000 3:00:00 AM", 20)
        f.create_dataset(BC + "/BC Lines/Attributes", data=np.array(
            [(b"Outlet", 1, 0, 1), (b"Inflow A", 1, 1, 1), (b"Inflow B", 1, 2, 1)], dtype=LINE_DT))
        g = f[BC + "/BC Lines"].create_group("Payloads")
        g.create_dataset("Payloads", data=np.array([
            (b"Hydraulic Data", b"Normal Depth", 1, b"Constant", b"", b"", 0.001, -1),
            (b"Hydraulic Data", b"Flow", 1, b"TimeSeries", b"", b"", 0.0, 0),
            (b"Hydraulic Data", b"Flow", 1, b"TimeSeries", b"", b"", 0.0, 1)], dtype=PAYLOAD_DT))
        g.create_dataset("Time Series Definitions", data=np.array([
            (b"Regular", b"Absolute", HOUR, b"01:00:00", 0, b"1/1/0001 12:00:00 AM", 0, 0, 4),
            (b"Regular", b"Absolute", HOUR, b"01:00:00", 0, b"1/1/0001 12:00:00 AM", 4, 4, 4)],
            dtype=TSD_DT))
        g.create_dataset("Times", data=np.array([0, 1, 2, 3, 0, 1, 2, 3], dtype="<i8") * HOUR,
                         chunks=(8,), compression="gzip")
        g.create_dataset("Values", data=np.array([10.0, 11, 12, 13, 5, 6, 7, 8]),
                         chunks=(8,), compression="gzip")
    return p


def test_bc_lines_map_to_payloads(tmp_path: Path) -> None:
    lines = bc_lines(_bc_full(tmp_path))
    assert [(ln.name, ln.payload_start, ln.payload_count) for ln in lines] == [
        ("Outlet", 0, 1), ("Inflow A", 1, 1), ("Inflow B", 2, 1)]


def test_write_flow_series_resizes_one_line_and_keeps_others(tmp_path: Path) -> None:
    p = _bc_full(tmp_path)
    write_flow_series(p, "Inflow A", [0, 1800, 3600, 5400, 7200, 9000, 10800], [1.0] * 7)
    with h5py.File(p, "r") as f:
        g = f[G]
        tsd = g["Time Series Definitions"][:]
        assert tsd["Count"].tolist() == [7, 4]
        assert tsd["Start (Time)"].tolist() == [0, 7] and tsd["Start (Value)"].tolist() == [0, 7]
        assert tsd["RTS Interval"][0] == HOUR // 2
        assert tsd["RTS Interval (DESC)"][0] == b"00:30:00"
        assert g["Values"][:].tolist() == [1.0] * 7 + [5.0, 6.0, 7.0, 8.0]  # Inflow B untouched
        assert g["Times"][:7].tolist() == [i * HOUR // 2 for i in range(7)]
        assert g["Values"].compression == "gzip" and g["Values"].dtype == np.dtype("<f8")
    assert validate_bc(p) == []


def test_write_flow_series_rejects_bad_input(tmp_path: Path) -> None:
    p = _bc_full(tmp_path)
    with pytest.raises(ValueError, match="no BC line"):
        write_flow_series(p, "Nope", [0, 3600], [1, 1])
    with pytest.raises(ValueError, match="flow"):
        write_flow_series(p, "Outlet", [0, 3600], [1, 1])
    with pytest.raises(ValueError, match="regular"):
        write_flow_series(p, "Inflow A", [0, 3600, 5400], [1, 1, 1])
    with pytest.raises(ValueError):
        write_flow_series(p, "Inflow A", [0, 3600], [1, -1])
    with pytest.raises(ValueError):
        write_flow_series(p, "Inflow A", [0, 3600], [1])


def test_normal_depth_slope_by_line(tmp_path: Path) -> None:
    p = _bc_full(tmp_path)
    set_normal_depth_slope(p, 0.004, line="Outlet")
    assert payloads(p)[0].constant == 0.004
    with pytest.raises(ValueError):
        set_normal_depth_slope(p, 0.004, line="Inflow A")


def test_set_time_window_writes_ticks_and_desc(tmp_path: Path) -> None:
    p = _bc_full(tmp_path)
    set_time_window(p, datetime(2000, 1, 1), datetime(2000, 1, 3, 13, 30))
    with h5py.File(p, "r") as f:
        b = f[BC]
        assert b.attrs["Start Time"] == to_ticks(datetime(2000, 1, 1))
        assert b.attrs["End Time"] == to_ticks(datetime(2000, 1, 3, 13, 30))
        assert read_fixed_string(b, "End Time (DESC)") == "1/3/2000 1:30:00 PM"
        assert b.attrs.get_id("End Time (DESC)").get_type().get_size() == 20
    with pytest.raises(ValueError, match="width"):
        set_time_window(p, datetime(2000, 1, 1), datetime(2000, 12, 31, 23, 0))
    with pytest.raises(ValueError):
        set_time_window(p, datetime(2000, 1, 2), datetime(2000, 1, 1))


def test_validate_flags_series_shorter_than_window(tmp_path: Path) -> None:
    p = _bc_full(tmp_path)
    set_time_window(p, datetime(2000, 1, 1), datetime(2000, 1, 1, 5))   # both series cover 3 h
    kinds = sorted(pr.kind for pr in validate_bc(p))
    assert kinds == ["series_short", "series_short"]

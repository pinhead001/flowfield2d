from datetime import datetime, timedelta
from pathlib import Path

import h5py
import numpy as np
import pytest

from rasdrive.engine.ras2025.h5edit import (
    DOTNET_EPOCH,
    from_ticks,
    guarded,
    read_fixed_string,
    recreate_dataset,
    to_ticks,
    write_fixed_string_attr,
)
from rasdrive.engine.ras2025.h5schema import SchemaMismatch, fingerprint, walk


def test_ticks() -> None:
    assert to_ticks(timedelta(seconds=1)) == 10_000_000
    assert to_ticks(timedelta(microseconds=1)) == 10
    assert to_ticks(datetime(2000, 1, 1)) == 630822816000000000
    assert from_ticks(630822816000000000) == datetime(2000, 1, 1)
    assert from_ticks(0) == DOTNET_EPOCH
    t = datetime(2026, 10, 24, 6, 30, 15, 123456)
    assert from_ticks(to_ticks(t)) == t


def _nullterm_attr(obj: h5py.Group, name: str, size: int) -> None:
    tid = h5py.h5t.C_S1.copy()
    tid.set_size(size)
    tid.set_strpad(h5py.h5t.STR_NULLTERM)
    obj.attrs.create(name, np.array(b"x", dtype=f"S{size}"), dtype=h5py.Datatype(tid))


def test_fixed_string_keeps_last_char_and_type(tmp_path: Path) -> None:
    p = tmp_path / "a.h5"
    with h5py.File(p, "w") as f:
        g = f.create_group("BC")
        _nullterm_attr(g, "Name", 8)
        write_fixed_string_attr(g, "Name", "ABCDEFG")         # size - 1 characters
        write_fixed_string_attr(g, "New", "xy", size=4)
        with pytest.raises(ValueError):
            write_fixed_string_attr(g, "Name", "ABCDEFGHIJ")
        with pytest.raises(ValueError):
            write_fixed_string_attr(g, "Other", "no size given")
    with h5py.File(p, "r") as f:
        g = f["BC"]
        assert read_fixed_string(g, "Name") == "ABCDEFG"
        tid = g.attrs.get_id("Name").get_type()
        assert tid.get_size() == 8 and tid.get_strpad() == h5py.h5t.STR_NULLTERM
        assert read_fixed_string(g, "New") == "xy"
        assert g.attrs.get_id("New").get_type().get_strpad() == h5py.h5t.STR_NULLTERM


def test_recreate_dataset_keeps_layout_and_attrs(tmp_path: Path) -> None:
    p = tmp_path / "a.h5"
    with h5py.File(p, "w") as f:
        ds = f.create_dataset("T/Flow", data=np.zeros((4, 2), "f4"), chunks=(2, 2),
                              compression="gzip", compression_opts=4, maxshape=(None, 2))
        _nullterm_attr(ds, "Units", 6)
        write_fixed_string_attr(ds, "Units", "cms")
    with h5py.File(p, "r+") as f:
        new = recreate_dataset(f["T"], "Flow", np.arange(20, dtype="f8").reshape(10, 2))
        assert new.shape == (10, 2)
        with pytest.raises(ValueError):
            recreate_dataset(f["T"], "Flow", np.zeros(3))
    with h5py.File(p, "r") as f:
        ds = f["T/Flow"]
        assert ds.dtype == np.dtype("f4") and ds[9, 1] == 19.0
        assert ds.chunks == (2, 2) and ds.compression == "gzip" and ds.compression_opts == 4
        assert ds.maxshape == (None, 2)
        assert read_fixed_string(ds, "Units") == "cms"
        assert ds.attrs.get_id("Units").get_type().get_size() == 6


def test_guarded_refuses_before_writing(tmp_path: Path) -> None:
    p = tmp_path / "a.h5"
    with h5py.File(p, "w") as f:
        f.create_dataset("x", data=np.zeros(2))
    fp = fingerprint(walk(p))
    with guarded(p, fp) as f:
        f["x"][0] = 1.0
    with h5py.File(p, "r") as f:
        assert f["x"][0] == 1.0
    before = p.read_bytes()
    with pytest.raises(SchemaMismatch):
        with guarded(p, "0000000000000000") as f:
            f["x"][1] = 2.0
    assert p.read_bytes() == before

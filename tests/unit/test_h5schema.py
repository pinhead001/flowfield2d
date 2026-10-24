from pathlib import Path

import h5py
import numpy as np
import pytest

from flowfield2d.engines.ras2025.h5schema import (
    SchemaMismatch,
    diff,
    fingerprint,
    guard,
    load_baseline,
    save_baseline,
    walk,
)


def _fixed_str(n: int) -> h5py.Datatype:
    tid = h5py.h5t.C_S1.copy()
    tid.set_size(n)
    tid.set_strpad(h5py.h5t.STR_NULLTERM)
    return h5py.Datatype(tid)


def _make(path: Path, rows: int = 3, extra: bool = False, f64: bool = False) -> Path:
    with h5py.File(path, "w") as f:
        g = f.create_group("Event Conditions/Unsteady")
        g.attrs.create("Name", np.array(b"bc1", dtype="S16"), dtype=_fixed_str(16))
        g.create_dataset("Flow", data=np.zeros((rows, 2), dtype="f8" if f64 else "f4"),
                         chunks=(1, 2), compression="gzip")
        if extra:
            f.create_dataset("Extra", data=np.arange(3))
    return path


def test_fingerprint_ignores_shapes_and_values(tmp_path: Path) -> None:
    a = walk(_make(tmp_path / "a.h5", rows=3))
    b = walk(_make(tmp_path / "b.h5", rows=50))
    assert fingerprint(a) == fingerprint(b)
    assert len(fingerprint(a)) == 16


def test_walk_records_string_padding(tmp_path: Path) -> None:
    objs = walk(_make(tmp_path / "a.h5"))
    attr = objs["/Event Conditions/Unsteady"]["attrs"]["Name"]
    assert "NULLTERM" in str(attr)


def test_diff_and_guard(tmp_path: Path) -> None:
    base = tmp_path / "base.json"
    fp = save_baseline(_make(tmp_path / "a.h5"), base)
    exp_fp, exp_objs = load_baseline(base)
    assert exp_fp == fp
    guard(_make(tmp_path / "same.h5", rows=9), exp_fp, exp_objs)

    changed = _make(tmp_path / "c.h5", extra=True, f64=True)
    d = diff(exp_objs, walk(changed))
    assert d.added == ["/Extra"]
    assert "/Event Conditions/Unsteady/Flow" in d.type_changed
    assert not d.empty
    with pytest.raises(SchemaMismatch) as e:
        guard(changed, exp_fp, exp_objs)
    assert "/Extra" in str(e.value) and e.value.diff.added == ["/Extra"]


def test_guard_without_objects_names_fingerprints(tmp_path: Path) -> None:
    with pytest.raises(SchemaMismatch, match="0000000000000000"):
        guard(_make(tmp_path / "a.h5"), "0000000000000000")

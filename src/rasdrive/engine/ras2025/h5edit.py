"""Guarded HDF5 edits (REQUIREMENTS 3.3).

Recreate datasets, exact NULLTERM strings, 100-ns ticks.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import h5py
import h5py.h5a
import h5py.h5s
import h5py.h5t
import numpy as np

from rasdrive.engine.ras2025 import h5schema

# ---------------------------------------------------------------------------
# Time constants
# ---------------------------------------------------------------------------

TICKS_PER_SECOND: int = 10_000_000
DOTNET_EPOCH: datetime = datetime(1, 1, 1)


# ---------------------------------------------------------------------------
# Tick conversion helpers
# ---------------------------------------------------------------------------


def to_ticks(x: datetime | timedelta) -> int:
    """Convert *x* to 100-ns ticks using exact integer arithmetic.

    A :class:`~datetime.timedelta` gives its duration in ticks.
    A naive :class:`~datetime.datetime` gives ticks elapsed since
    :data:`DOTNET_EPOCH` (0001-01-01 00:00:00).
    """
    if isinstance(x, timedelta):
        total_us = (
            x.days * 86_400 * 1_000_000
            + x.seconds * 1_000_000
            + x.microseconds
        )
        return total_us * 10
    # datetime: delta since DOTNET_EPOCH
    delta = x - DOTNET_EPOCH
    total_us = (
        delta.days * 86_400 * 1_000_000
        + delta.seconds * 1_000_000
        + delta.microseconds
    )
    return total_us * 10


def from_ticks(t: int) -> datetime:
    """Return the naive datetime for *t* 100-ns ticks since :data:`DOTNET_EPOCH`."""
    total_us, remainder = divmod(t, 10)
    # remainder (sub-microsecond) is discarded — datetime resolution is 1 µs
    days, rem_us = divmod(total_us, 86_400 * 1_000_000)
    seconds, microseconds = divmod(rem_us, 1_000_000)
    return DOTNET_EPOCH + timedelta(
        days=int(days), seconds=int(seconds), microseconds=int(microseconds)
    )


# ---------------------------------------------------------------------------
# Fixed-width NULLTERM string helpers
# ---------------------------------------------------------------------------


def _encode_for(tid: Any, value: str) -> bytes:
    cset = tid.get_cset()
    encoding = "utf-8" if cset == h5py.h5t.CSET_UTF8 else "ascii"
    try:
        encoded = value.encode(encoding)
    except UnicodeEncodeError as exc:
        raise ValueError(f"Value {value!r} cannot be encoded as {encoding}") from exc
    size = int(tid.get_size())
    if len(encoded) > size:
        raise ValueError(f"Value {value!r} ({len(encoded)} bytes) exceeds the type size {size}")
    return encoded


def write_fixed_string_attr(
    obj: Any,
    name: str,
    value: str,
    size: int | None = None,
) -> None:
    """Write *value* to the scalar fixed-width string attribute *name* on *obj*.

    An existing attribute keeps its exact HDF5 type (size, padding, cset) and is written in place;
    nothing is deleted. A new attribute needs *size* and gets a fixed-length ASCII NULLTERM type.
    The memory type passed to the write is the file type itself, so no padding conversion happens
    and a full-width value (as many bytes as the size) keeps its last character.

    Raises ValueError if the value is longer than the size or not encodable in the cset, if an
    existing attribute is not a scalar fixed-length string, or if *size* is missing for a new one.
    """
    bname = name.encode("utf-8")
    if name in obj.attrs:
        aid = h5py.h5a.open(obj.id, bname)
        try:
            tid = aid.get_type()
            if tid.get_class() != h5py.h5t.STRING or tid.is_variable_str():
                raise ValueError(f"Attribute {name!r} is not a fixed-length string")
            if aid.get_space().get_simple_extent_type() != h5py.h5s.SCALAR:
                raise ValueError(f"Attribute {name!r} is not scalar; refusing to flatten it")
            encoded = _encode_for(tid, value)
            aid.write(np.array(encoded, dtype=f"S{tid.get_size()}"), mtype=tid)
        finally:
            aid.close()
        return

    if size is None:
        raise ValueError(f"Attribute {name!r} does not exist; 'size' must be supplied to create it")
    tid = h5py.h5t.C_S1.copy()
    tid.set_size(size)
    tid.set_strpad(h5py.h5t.STR_NULLTERM)
    tid.set_cset(h5py.h5t.CSET_ASCII)
    encoded = _encode_for(tid, value)
    aid = h5py.h5a.create(obj.id, bname, tid, h5py.h5s.create(h5py.h5s.SCALAR))
    try:
        aid.write(np.array(encoded, dtype=f"S{size}"), mtype=tid)
    finally:
        aid.close()


def read_fixed_string(obj: Any, name: str) -> str:
    """Read a scalar fixed-width string attribute with its own type as memory type; strip NULs."""
    aid = h5py.h5a.open(obj.id, name.encode("utf-8"))
    try:
        tid = aid.get_type()
        buf = np.empty((), dtype=f"S{tid.get_size()}")
        aid.read(buf, mtype=tid)
        cset = tid.get_cset()
    finally:
        aid.close()
    raw = bytes(buf[()]).rstrip(b"\x00")
    return raw.decode("utf-8" if cset == h5py.h5t.CSET_UTF8 else "ascii", errors="replace")


# ---------------------------------------------------------------------------
# Dataset recreation
# ---------------------------------------------------------------------------

_TMP_SUFFIX = ".__rasdrive_new"


def _snapshot_attrs(obj: Any) -> list[tuple[bytes, Any, Any, np.ndarray[Any, np.dtype[Any]]]]:
    """Read every attribute with its own file type as memory type. Any failure raises."""
    out: list[tuple[bytes, Any, Any, np.ndarray[Any, np.dtype[Any]]]] = []
    for attr_name in obj.attrs.keys():
        bname = attr_name.encode("utf-8")
        aid = h5py.h5a.open(obj.id, bname)
        try:
            tid = aid.get_type()
            space = aid.get_space()
            buf = np.empty(space.shape, dtype=tid.dtype)
            aid.read(buf, mtype=tid)
        except Exception as exc:
            raise ValueError(f"cannot copy attribute {attr_name!r} exactly: {exc}") from exc
        finally:
            aid.close()
        out.append((bname, tid, space, buf))
    return out


def recreate_dataset(group: Any, name: str, data: np.ndarray[Any, np.dtype[Any]]) -> Any:
    """Replace *name* inside *group* with *data*, preserving layout and attributes.

    The original dataset's dtype, chunking (chunk shape clipped to the new shape), compression,
    shuffle, fletcher32, ``maxshape`` and every attribute (exact HDF5 type) are carried over. The
    dataset is recreated, never resized. The new dataset is fully built under a temporary name
    before the old one is removed, so a failure leaves the original untouched.

    Raises ValueError on a rank mismatch, a failed cast, or an attribute that can't be copied
    exactly.
    """
    old: h5py.Dataset = group[name]
    if data.ndim != len(old.shape):
        raise ValueError(
            f"Rank mismatch: existing dataset has rank {len(old.shape)}, "
            f"new data has rank {data.ndim}"
        )
    try:
        cast = np.asarray(data).astype(old.dtype)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"cannot cast new data to {old.dtype}: {exc}") from exc

    kwargs: dict[str, Any] = {
        "data": cast,
        "maxshape": tuple(None if ms is None else data.shape[i]
                          for i, ms in enumerate(old.maxshape or old.shape)),
    }
    if old.chunks is not None:
        kwargs["chunks"] = tuple(min(c, max(s, 1))
                                 for c, s in zip(old.chunks, data.shape, strict=True))
    if old.compression is not None:
        kwargs["compression"] = old.compression
        if old.compression_opts is not None:
            kwargs["compression_opts"] = old.compression_opts
    if old.shuffle:
        kwargs["shuffle"] = True
    if old.fletcher32:
        kwargs["fletcher32"] = True
    attrs = _snapshot_attrs(old)

    tmp = name + _TMP_SUFFIX
    if tmp in group:
        del group[tmp]
    try:
        new_ds: h5py.Dataset = group.create_dataset(tmp, **kwargs)
        for bname, tid, space, buf in attrs:
            aid = h5py.h5a.create(new_ds.id, bname, tid, space)
            try:
                aid.write(buf, mtype=tid)
            finally:
                aid.close()
    except Exception:
        if tmp in group:
            del group[tmp]
        raise
    del group[name]
    group.move(tmp, name)
    return group[name]


# ---------------------------------------------------------------------------
# Guarded context manager
# ---------------------------------------------------------------------------


@contextmanager
def guarded(
    path: Path,
    fingerprint: str,
    objects: dict[str, dict[str, Any]] | None = None,
) -> Iterator[h5py.File]:
    """Open *path* for writing only after passing the schema guard.

    Calls :func:`h5schema.guard` before opening the file (so a mismatch raises
    :class:`~rasdrive.engine.ras2025.h5schema.SchemaMismatch` without touching
    the file), then yields an ``h5py.File`` opened in ``"r+"`` mode and closes
    it on exit.

    Parameters
    ----------
    path:
        HDF5 file to open.
    fingerprint:
        Expected structural fingerprint (16-char hex).
    objects:
        Optional pre-computed object map for a richer diff on mismatch.
    """
    h5schema.guard(path, fingerprint, objects)
    f = h5py.File(path, "r+", locking=False)
    try:
        yield f
    finally:
        f.close()

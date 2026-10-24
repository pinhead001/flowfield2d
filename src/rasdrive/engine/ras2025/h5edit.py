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


def write_fixed_string_attr(
    obj: Any,
    name: str,
    value: str,
    size: int | None = None,
) -> None:
    """Write *value* to the fixed-width string attribute *name* on *obj*.

    If the attribute already exists its exact HDF5 type (size, padding, cset)
    is preserved.  If the attribute does not exist, *size* must be supplied and
    a fixed-length ASCII NULLTERM type of that length is created.

    The write uses the low-level API (``h5py.h5a.create`` / ``attr.write``)
    with **identical file and memory types** so no character is silently
    dropped.

    Raises
    ------
    ValueError
        If *value* is longer than the type's size, cannot be encoded in the
        type's character set, or the attribute does not exist and *size* was
        not supplied.
    """
    h5t = h5py.h5t

    if name in obj.attrs:
        # Reuse the existing file type exactly.
        aid = h5py.h5a.open(obj.id, name.encode("utf-8"))
        tid = aid.get_type()
        attr_size: int = tid.get_size()
        strpad = tid.get_strpad()
        cset = tid.get_cset()
        aid.close()

        # Encode and validate length.
        encoding = "utf-8" if cset == h5t.CSET_UTF8 else "ascii"
        try:
            encoded = value.encode(encoding)
        except UnicodeEncodeError as exc:
            raise ValueError(
                f"Value {value!r} cannot be encoded as {encoding}"
            ) from exc
        if len(encoded) > attr_size:
            raise ValueError(
                f"Value {value!r} ({len(encoded)} bytes) exceeds attribute size {attr_size}"
            )

        # Delete and recreate with the same type so the file type is preserved.
        h5py.h5a.delete(obj.id, name.encode("utf-8"))

        # Build file type identical to original.
        file_tid = h5t.C_S1.copy()
        file_tid.set_size(attr_size)
        file_tid.set_strpad(strpad)
        file_tid.set_cset(cset)

        space = h5py.h5s.create(h5py.h5s.SCALAR)
        attr = h5py.h5a.create(obj.id, name.encode("utf-8"), file_tid, space)

        buf = np.array(encoded, dtype=f"S{attr_size}")
        attr.write(buf)
        attr.close()

    else:
        # New attribute — size must be provided.
        if size is None:
            raise ValueError(
                f"Attribute {name!r} does not exist; 'size' must be supplied to create it"
            )

        try:
            encoded = value.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError(
                f"Value {value!r} cannot be encoded as ascii"
            ) from exc
        if len(encoded) > size:
            raise ValueError(
                f"Value {value!r} ({len(encoded)} bytes) exceeds requested size {size}"
            )

        file_tid = h5t.C_S1.copy()
        file_tid.set_size(size)
        file_tid.set_strpad(h5t.STR_NULLTERM)
        file_tid.set_cset(h5t.CSET_ASCII)

        space = h5py.h5s.create(h5py.h5s.SCALAR)
        attr = h5py.h5a.create(obj.id, name.encode("utf-8"), file_tid, space)

        buf = np.array(encoded, dtype=f"S{size}")
        attr.write(buf)
        attr.close()


def read_fixed_string(obj: Any, name: str) -> str:
    """Read the fixed-width string attribute *name* from *obj* and strip trailing NULs."""
    raw: bytes = obj.attrs[name]
    if isinstance(raw, np.bytes_):
        raw = bytes(raw)
    return raw.rstrip(b"\x00").decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Dataset recreation
# ---------------------------------------------------------------------------


def recreate_dataset(group: Any, name: str, data: np.ndarray[Any, np.dtype[Any]]) -> Any:
    """Replace *name* inside *group* with *data*, preserving layout and attributes.

    The original dataset's dtype, chunking (chunk shape clipped to new shape),
    compression, shuffle, fletcher32, ``maxshape`` and every attribute (with
    its exact HDF5 type) are all carried over.  The dataset is deleted and
    re-created; it is **never** resized.

    Raises
    ------
    ValueError
        If *data*'s rank (ndim) differs from the original dataset's rank.
    """
    old: h5py.Dataset = group[name]
    old_rank = len(old.shape)
    if data.ndim != old_rank:
        raise ValueError(
            f"Rank mismatch: existing dataset has rank {old_rank}, "
            f"new data has rank {data.ndim}"
        )

    # --- Collect properties from the old dataset --------------------------
    old_dtype = old.dtype
    old_chunks = old.chunks  # None if contiguous
    old_compression = old.compression
    old_compression_opts = old.compression_opts
    old_shuffle = old.shuffle
    old_fletcher32 = old.fletcher32
    old_maxshape = old.maxshape  # tuple with None for unlimited dims

    # Clip chunk shape to new shape (each chunk dim must not exceed new dim).
    new_chunks: tuple[int, ...] | None = None
    if old_chunks is not None:
        new_chunks = tuple(
            min(c, s) for c, s in zip(old_chunks, data.shape, strict=True)
        )

    # Build maxshape: None dims stay None; fixed dims become the new shape dim.
    new_maxshape: tuple[int | None, ...] = tuple(
        None if ms is None else data.shape[i]
        for i, ms in enumerate(old_maxshape)
    )

    # --- Snapshot attributes at the low level so exact types are preserved ---
    # We capture: (name_bytes, low-level TypeID, numpy buf matching the HDF5 type).
    attr_snapshots: list[tuple[bytes, Any, np.ndarray[Any, np.dtype[Any]]]] = []
    for attr_name in old.attrs.keys():
        aid = h5py.h5a.open(old.id, attr_name.encode("utf-8"))
        tid = aid.get_type()
        spc = aid.get_space()
        shape = spc.shape  # () for scalar

        # Determine numpy dtype for reading that matches the HDF5 file type.
        cls = tid.get_class()
        h5t = h5py.h5t
        if cls == h5t.STRING:
            if tid.is_variable_str():
                arr_dtype: Any = np.dtype(object)
            else:
                arr_dtype = np.dtype(f"S{tid.get_size()}")
        elif cls == h5t.INTEGER:
            sz = tid.get_size()
            sign = "i" if tid.get_sign() == h5t.SGN_2 else "u"
            arr_dtype = np.dtype(f"{sign}{sz}")
        elif cls == h5t.FLOAT:
            arr_dtype = np.dtype(f"f{tid.get_size()}")
        else:
            # Compound, enum, opaque, etc. — use raw bytes.
            arr_dtype = np.dtype(f"V{tid.get_size()}")

        try:
            buf: np.ndarray[Any, np.dtype[Any]]
            if shape:
                buf = np.empty(shape, dtype=arr_dtype)
            else:
                buf = np.empty((), dtype=arr_dtype)
            aid.read(buf)
        except Exception:  # pragma: no cover
            aid.close()
            continue
        attr_snapshots.append((attr_name.encode("utf-8"), tid, buf))
        aid.close()

    # --- Delete old, create new -------------------------------------------
    del group[name]

    kwargs: dict[str, Any] = {
        "data": data.astype(old_dtype),
        "maxshape": new_maxshape,
    }
    if new_chunks is not None:
        kwargs["chunks"] = new_chunks
    if old_compression is not None:
        kwargs["compression"] = old_compression
        if old_compression_opts is not None:
            kwargs["compression_opts"] = old_compression_opts
    if old_shuffle:
        kwargs["shuffle"] = True
    if old_fletcher32:
        kwargs["fletcher32"] = True

    new_ds: h5py.Dataset = group.create_dataset(name, **kwargs)

    # --- Restore attributes with exact types --------------------------------
    for attr_name_b, tid, buf in attr_snapshots:
        space = h5py.h5s.create(h5py.h5s.SCALAR) if buf.shape == () else \
                h5py.h5s.create_simple(buf.shape)
        attr = h5py.h5a.create(new_ds.id, attr_name_b, tid, space)
        attr.write(buf)
        attr.close()

    return new_ds


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

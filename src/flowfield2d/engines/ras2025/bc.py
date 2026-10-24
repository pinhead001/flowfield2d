"""Boundary-condition layer edits for RAS 2025 BC files (template edits under REQUIREMENTS 3.3).

Layout observed at probe step D:
- `/Boundary Conditions` attrs `Start Time` / `End Time` (i8, 100-ns ticks since 0001-01-01) with
  fixed-width `(DESC)` text twins in .NET short format (`1/1/2000 12:00:00 AM`).
- `/Boundary Conditions/BC Lines/Attributes`: one row per BC line (`Name`, `Enabled`, `Start`,
  `Count`); `Start`/`Count` select that line's rows in `Payloads`.
- `.../Payloads/Payloads`: one row per payload (`Variable` e.g. "Flow" / "Normal Depth"; `Mode`
  "TimeSeries" / "Constant"; `Constant`; `Row` indexing `Time Series Definitions`).
- `.../Payloads/Time Series Definitions`: per series `Start (Time)`, `Start (Value)`, `Count` into
  the shared `Times` (i8 tick offsets from `Start Time`) and `Values` (f8) arrays; `Regular` series
  also carry `RTS Interval` (+ DESC `HH:MM:SS`).
All edits go through `h5edit.recreate_dataset` / `write_fixed_string_attr`, which keep dtypes,
chunking, filters and exact fixed-width string types, and never resize. Callers run the schema guard
first (`h5edit.guarded`); these functions edit a path directly for scratch copies and tests.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import h5py
import numpy as np

from flowfield2d.engines.ras2025.h5edit import (
    TICKS_PER_SECOND,
    recreate_dataset,
    to_ticks,
    write_fixed_string_attr,
)

BC = "/Boundary Conditions"
LINES = BC + "/BC Lines/Attributes"
PAYLOADS = BC + "/BC Lines/Payloads"
TSD = "Time Series Definitions"


@dataclass(frozen=True)
class BcPayload:
    index: int
    variable: str
    mode: str
    enabled: bool
    constant: float
    row: int


@dataclass(frozen=True)
class BcLine:
    index: int
    name: str
    enabled: bool
    payload_start: int
    payload_count: int


def _s(x: bytes | str) -> str:
    return x.decode("ascii", "replace").rstrip("\x00") if isinstance(x, bytes) else str(x)


def payloads(path: Path) -> list[BcPayload]:
    with h5py.File(path, "r", locking=False) as f:
        arr = f[PAYLOADS]["Payloads"][:]
    return [BcPayload(i, _s(r["Variable"]), _s(r["Mode"]), bool(r["Enabled"]),
                      float(r["Constant"]), int(r["Row"])) for i, r in enumerate(arr)]


def bc_lines(path: Path) -> list[BcLine]:
    with h5py.File(path, "r", locking=False) as f:
        if LINES not in f:
            return []
        arr = f[LINES][:]
    return [BcLine(i, _s(r["Name"]), bool(r["Enabled"]), int(r["Start"]), int(r["Count"]))
            for i, r in enumerate(arr)]


def _pick(path: Path, variable: str, mode: str, what: str, line: str | None) -> BcPayload:
    rows = [r for r in payloads(path) if r.variable == variable and r.mode == mode]
    if line is not None:
        match = [ln for ln in bc_lines(path) if ln.name == line]
        if not match:
            raise ValueError(f"no BC line named {line!r}")
        ln = match[0]
        lo, hi = ln.payload_start, ln.payload_start + ln.payload_count
        rows = [r for r in rows if lo <= r.index < hi]
    if len(rows) != 1:
        raise ValueError(f"expected exactly one {what} payload, found {len(rows)} {what}")
    return rows[0]


def scale_flow_series(path: Path, factor: float, line: str | None = None) -> None:
    """Multiply a flow time series by `factor` (> 0); the only one, or the one on `line`."""
    if not factor > 0:
        raise ValueError("factor must be positive")
    p = _pick(path, "Flow", "TimeSeries", "flow", line)
    with h5py.File(path, "r+", locking=False) as f:
        g = f[PAYLOADS]
        values = g["Values"][:]
        if TSD in g:
            d = g[TSD][p.row]
            sl = slice(int(d["Start (Value)"]), int(d["Start (Value)"]) + int(d["Count"]))
        else:
            sl = slice(None)
        values[sl] = values[sl] * factor
        recreate_dataset(g, "Values", values)


def set_normal_depth_slope(path: Path, slope: float, allow_invalid: bool = False,
                           line: str | None = None) -> None:
    """Set a normal-depth BC's friction slope; `allow_invalid` permits 0 (probe E6b only)."""
    if slope < 0 or (slope == 0 and not allow_invalid):
        raise ValueError("normal-depth slope must be positive")
    target = _pick(path, "Normal Depth", "Constant", "normal-depth", line)
    with h5py.File(path, "r+", locking=False) as f:
        g = f[PAYLOADS]
        arr = np.array(g["Payloads"][:])
        arr["Constant"][target.index] = slope
        recreate_dataset(g, "Payloads", arr)


def _hms(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def write_flow_series(path: Path, line: str, offsets_s: Sequence[float],
                      values: Sequence[float]) -> None:
    """Replace the flow series on BC line `line` (offsets in seconds from the BC start time).

    The shared `Times`/`Values` arrays are rebuilt and every series definition's start/count is
    recomputed, so other lines' series are kept. Regular series need uniform spacing.
    """
    t = np.asarray(offsets_s, dtype=np.float64)
    v = np.asarray(values, dtype=np.float64)
    if t.size < 2 or t.size != v.size:
        raise ValueError("need at least two times and one value per time")
    if t[0] != 0 or not np.all(np.diff(t) > 0):
        raise ValueError("offsets must start at 0 and strictly increase")
    if not np.all(np.isfinite(v)) or v.min() < 0:
        raise ValueError("flows must be finite and >= 0")
    p = _pick(path, "Flow", "TimeSeries", "flow", line)
    ticks = np.rint(t * TICKS_PER_SECOND).astype(np.int64)
    with h5py.File(path, "r+", locking=False) as f:
        g = f[PAYLOADS]
        defs = np.array(g[TSD][:])
        old_t, old_v = g["Times"][:], g["Values"][:]
        if _s(defs["TS Type"][p.row]) == "Regular":
            steps = np.diff(ticks)
            if not np.all(steps == steps[0]):
                raise ValueError("this is a regular time series: offsets must be evenly spaced")
            defs["RTS Interval"][p.row] = steps[0]
            desc = _hms(int(steps[0] // TICKS_PER_SECOND)).encode("ascii")
            if len(desc) > defs.dtype["RTS Interval (DESC)"].itemsize:
                raise ValueError("RTS interval text does not fit its fixed width")
            defs["RTS Interval (DESC)"][p.row] = desc
        new_t: list[np.ndarray] = []
        new_v: list[np.ndarray] = []
        pos = 0
        for i, d in enumerate(defs):
            if i == p.row:
                seg_t, seg_v = ticks, v
            else:
                st, sv, n = int(d["Start (Time)"]), int(d["Start (Value)"]), int(d["Count"])
                seg_t, seg_v = old_t[st:st + n], old_v[sv:sv + n]
            defs["Start (Time)"][i] = pos
            defs["Start (Value)"][i] = pos
            defs["Count"][i] = len(seg_t)
            new_t.append(seg_t)
            new_v.append(seg_v)
            pos += len(seg_t)
        recreate_dataset(g, "Times", np.concatenate(new_t).astype(old_t.dtype))
        recreate_dataset(g, "Values", np.concatenate(new_v).astype(old_v.dtype))
        recreate_dataset(g, TSD, defs)


def _net_short(d: datetime) -> str:
    h12 = d.hour % 12 or 12
    return f"{d.month}/{d.day}/{d.year} {h12}:{d.minute:02d}:{d.second:02d} " \
           f"{'AM' if d.hour < 12 else 'PM'}"


def set_time_window(path: Path, start: datetime, end: datetime) -> None:
    """Set the BC simulation window (ticks plus fixed-width DESC text). The DESC attrs keep their
    exact width; a date whose text does not fit raises rather than changing the schema."""
    if not end > start:
        raise ValueError("end must be after start")
    texts = {"Start Time (DESC)": _net_short(start), "End Time (DESC)": _net_short(end)}
    with h5py.File(path, "r+", locking=False) as f:
        b = f[BC]
        for name, text in texts.items():
            width = b.attrs.get_id(name).get_type().get_size()
            if len(text) > width:
                raise ValueError(f"{name} text {text!r} exceeds its fixed width {width}")
        b.attrs["Start Time"] = np.int64(to_ticks(start))
        b.attrs["End Time"] = np.int64(to_ticks(end))
        for name, text in texts.items():
            write_fixed_string_attr(b, name, text)

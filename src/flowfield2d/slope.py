"""Slope estimates for normal-depth boundary conditions at domain cuts (REQUIREMENTS 4, BC rows).

Chainage increases downstream along a centerline; slopes are returned as positive drop per unit
length. Four sources, chosen per project (an engineering decision):
- "terrain":   DEM elevation sampled along the centerline;
- "thalweg":   minimum DEM elevation on transects perpendicular to the centerline;
- "wse":       water-surface profile from a reference run (e.g. the full domain);
- "specified": a value given per cut.
A straight line is fitted to the profile within `window` of the cut (both sides, or only the
upstream/downstream side). An adverse or flat fit is an error, never silently used.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from numpy.typing import ArrayLike, NDArray
from shapely.geometry import LineString

from flowfield2d.domains import bc_line

F = NDArray[np.float64]
SOURCES = ("terrain", "thalweg", "wse", "specified")


def fit_slope(chainage: ArrayLike, z: ArrayLike, at: float, window: float,
              side: str = "both") -> float:
    """Least-squares drop per unit chainage of `z` within `window` of `at`."""
    ch = np.asarray(chainage, dtype=np.float64)
    zz = np.asarray(z, dtype=np.float64)
    if side == "both":
        sel = np.abs(ch - at) <= window
    elif side == "downstream":
        sel = (ch >= at) & (ch <= at + window)
    elif side == "upstream":
        sel = (ch <= at) & (ch >= at - window)
    else:
        raise ValueError(f"side must be both/upstream/downstream, not {side!r}")
    sel &= np.isfinite(zz)
    if sel.sum() < 3:
        raise ValueError(f"fewer than 3 profile points within {window} of chainage {at}")
    slope = -float(np.polyfit(ch[sel], zz[sel], 1)[0])
    return slope


def _sample(dem: Path, pts: F) -> F:
    with rasterio.open(dem) as ds:
        vals = np.array([v[0] for v in ds.sample([tuple(p) for p in pts], masked=True)],
                        dtype=object)
        nod = ds.nodata
    out = np.array([np.nan if (v is np.ma.masked or (nod is not None and v == nod)) else float(v)
                    for v in vals], dtype=np.float64)
    return out


def terrain_profile(dem: Path, centerline: LineString, spacing: float) -> tuple[F, F]:
    ch = np.arange(0.0, centerline.length + 1e-9, spacing)
    pts = np.array([(p.x, p.y) for p in (centerline.interpolate(c) for c in ch)])
    return ch, _sample(dem, pts)


def thalweg_profile(dem: Path, centerline: LineString, spacing: float,
                    half_width: float) -> tuple[F, F]:
    with rasterio.open(dem) as ds:
        step = float(min(abs(ds.res[0]), abs(ds.res[1])))
    ch = np.arange(0.0, centerline.length + 1e-9, spacing)
    zmin = np.full(ch.size, np.nan)
    for i, c in enumerate(ch):
        t = bc_line(centerline, float(c), half_width)
        n = max(2, int(t.length / step) + 1)
        along = np.linspace(0, t.length, n)
        pts = np.array([(p.x, p.y) for p in (t.interpolate(d) for d in along)])
        z = _sample(dem, pts)
        if np.isfinite(z).any():
            zmin[i] = np.nanmin(z)
    return ch, zmin


def cut_slope(source: str, *, at: float, window: float, side: str = "both",
              **kw: Any) -> float:
    """Slope for a cut at chainage `at` from one of SOURCES (see module docstring)."""
    if source == "specified":
        if "value" not in kw:
            raise ValueError("specified source needs value=")
        s = float(kw["value"])
    elif source in ("terrain", "thalweg"):
        if "dem" not in kw or "centerline" not in kw:
            raise ValueError(f"{source} source needs dem= and centerline=")
        spacing = float(kw.get("spacing", window / 10))
        if source == "terrain":
            ch, z = terrain_profile(Path(kw["dem"]), kw["centerline"], spacing)
        else:
            if "half_width" not in kw:
                raise ValueError("thalweg source needs half_width=")
            ch, z = thalweg_profile(Path(kw["dem"]), kw["centerline"], spacing,
                                    float(kw["half_width"]))
        s = fit_slope(ch, z, at, window, side)
    elif source == "wse":
        if "chainage" not in kw or "wse" not in kw:
            raise ValueError("wse source needs chainage= and wse=")
        s = fit_slope(kw["chainage"], kw["wse"], at, window, side)
    else:
        raise ValueError(f"unknown slope source {source!r}; use one of {SOURCES}")
    if not s > 0:
        raise ValueError(f"{source} slope {s:.6g} is not positive (flat or adverse)")
    return s

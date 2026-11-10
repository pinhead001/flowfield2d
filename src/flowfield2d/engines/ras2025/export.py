"""RAS 2025 results as the engine-neutral flow state that `flowfield2d.export` writers take."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import h5py
import numpy as np
from shapely.geometry import Polygon

from flowfield2d.engines.ras2025.results import ResultsReader
from flowfield2d.export.iric import FlowState
from flowfield2d.results import cell_table_from_results


def flow_state(results: ResultsReader, area: str, t: int, unit_m: float, *,
               inflow_lines: Sequence[str] = (), tol: float = 0.0,
               discharge: float | None = None, min_depth: float = 0.0) -> FlowState:
    """The state at output `t` (negative counts from the end) in SI.

    Discharge is `discharge` (m3/s) when given, else the sum of |flow| through `inflow_lines`
    at `t` (BC line names; faces matched within `tol`, model units), converted with `unit_m`^3.
    Results without face-flow output fall back to flows rebuilt from face velocities. The caller
    decides which lines count: a solver with one inflow takes their total."""
    n_out = len(results.time_days())
    k = t if t >= 0 else n_out + t
    if not 0 <= k < n_out:
        raise IndexError(f"output {t} out of range (file has {n_out})")
    if discharge is None:
        if not inflow_lines:
            raise ValueError("give discharge or at least one inflow line")
        total = 0.0
        for line in inflow_lines:
            try:
                q = float(results.boundary_flow(area, line, tol)[k])
            except KeyError as e:
                if "unknown BC line" in str(e):
                    raise
                q = 0.0
            if q == 0.0:
                q = float(results.boundary_flow_reconstructed(area, line, tol)[k])
            total += abs(q)
        discharge = total * float(unit_m) ** 3
    table = cell_table_from_results(results, area, k, unit_m, min_depth)
    return FlowState(discharge=float(discharge),
                     cell_xy=np.column_stack([table["x"], table["y"]]),
                     wse=table["wse_m"], depth=table["depth_m"], speed=table["vel_mps"])


def _text(v: Any) -> str:
    return v.decode("utf-8", "replace").strip() if isinstance(v, bytes) else str(v).strip()


def terrain_sources(terrain_layer: Path) -> list[Path]:
    """The rasters of a terrain layer (`/Terrain/Attributes`), in the layer's order: where they
    overlap, a later raster covers an earlier one (probe 2026-11-10: mesh cell minimum elevations
    follow the later raster). Files are looked up beside the layer by their recorded names."""
    layer = Path(terrain_layer)
    out: list[Path] = []
    with h5py.File(layer, "r", locking=False) as f:
        for row in f["/Terrain/Attributes"][()]:
            if _text(row["Type"]) != "Raster":
                raise ValueError(f"{layer}: terrain source {_text(row['Name'])!r} is not a raster")
            name = _text(f[_text(row["Location"])].attrs["Filename"])
            path = layer.parent / name
            if not path.is_file():
                raise FileNotFoundError(f"{layer}: terrain raster {name!r} not found beside it")
            out.append(path)
    if not out:
        raise ValueError(f"{layer}: no terrain rasters")
    return out


def class_polygons(class_layer: Path) -> list[tuple[str, Polygon]]:
    """(class name, polygon) for each polygon of a classification layer's polygon classifier,
    in file order (layout in `landcover`)."""
    with h5py.File(class_layer, "r", locking=False) as f:
        g = f["/Classification/Classification Polygons"]
        names = [_text(r["Classification"]) for r in g["Attributes"][()]]
        ds = g["Polygon"]
        pts = np.asarray(ds[()], dtype=np.float64)[:, :2]
        start, count = np.asarray(ds.attrs["Start"]), np.asarray(ds.attrs["Count"])
    return [(n, Polygon(pts[int(s):int(s) + int(c)]))
            for n, s, c in zip(names, start, count, strict=True)]


def n_values(n_layer: Path) -> tuple[dict[str, float], float]:
    """(class name -> Manning's n, n where no class applies) of an n layer."""
    with h5py.File(n_layer, "r", locking=False) as f:
        g = f["/NValues"]
        table = {_text(r["Class"]): float(r["N Value"]) for r in g["Table"][()]}
        default = float(g.attrs["Constant Value"])
    return table, default


def polygon_n(class_layer: Path, n_layer: Path) -> tuple[list[tuple[Polygon, float]], float]:
    """Polygons with their n, in file order, and the n outside every polygon: the input of
    `roughness.rasterize_n`. KeyError for a polygon class the n table lacks."""
    table, default = n_values(n_layer)
    out = []
    for name, poly in class_polygons(class_layer):
        if name not in table:
            raise KeyError(f"class {name!r} has no n value in {Path(n_layer).name}")
        out.append((poly, table[name]))
    return out, default

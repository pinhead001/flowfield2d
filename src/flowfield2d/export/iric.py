"""Inputs for iRIC structured-grid solvers (FaSTMECH, Nays2DH and others) from a model's terrain,
roughness and results. Engine-neutral: the engine adapter supplies a `FlowState`.

iRIC solvers work in metres, so this is a units boundary (REQUIREMENTS 5): `prepare` takes the
metres per horizontal unit (`xy_unit_m`) and per terrain value unit (`z_unit_m`) and returns a
`Package` in SI. With a CRS in feet the exported coordinates are that CRS scaled to metres, which
is not a registered CRS; the summary records the scale so results map back.

Files written by `write_package`:
- `grid.csv`       iRIC grid CSV (Import > Grid): `IMAX,JMAX,KMAX` / counts / `I,J,K,X,Y,Z` plus
                   `N_<name>` (node) and `C_<name>` (cell) attribute columns, j outer, i inner.
- `elevation.tif`  terrain in metres (geographic data, raster), clipped to the grid; one
                   numbered file per raster for a terrain stack.
- `elevation.tpo`  the same as a point cloud (count line, then `x y z`), optional.
- `manning_n.tif`  Manning's n raster, when a roughness raster is given.
- `wse.csv`        `X,Y,WaterSurfaceElevation,...` at wet model cells (measured data).
- `summary.json`   discharge, stages, WSE profile by section, units, attribute meanings.

Roughness: Nays2DH takes Manning's n per cell. FaSTMECH takes a drag coefficient per node; the
conversion Cd = g n^2 / h^(1/3) needs a depth, which the caller chooses (`drag_depth`): a value in
metres, or "local" for the model depth at each node. Without it no FaSTMECH roughness is written.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import rasterio
import rasterio.windows
from numpy.typing import ArrayLike, NDArray
from rasterio import Affine
from scipy.spatial import cKDTree

from flowfield2d.curvigrid import CurviGrid, sample_raster

F = NDArray[np.float64]
G: float = 9.80665
SOLVERS = ("fastmech", "nays2dh")


def drag_from_manning(n: ArrayLike, depth_m: ArrayLike, g: float = G) -> F:
    """Drag coefficient Cd = g n^2 / h^(1/3) (SI n, depth in metres); NaN where depth <= 0."""
    na = np.asarray(n, dtype=np.float64)
    h = np.asarray(depth_m, dtype=np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.asarray(np.where(h > 0, g * na**2 / np.cbrt(h), np.nan), dtype=np.float64)


def nearest_values(src_xy: ArrayLike, values: ArrayLike, query_xy: ArrayLike,
                   max_dist: float) -> F:
    """Value of the nearest finite source point for each query point (any leading shape, last
    axis 2); NaN when none lies within `max_dist`."""
    v = np.asarray(values, dtype=np.float64)
    src = np.asarray(src_xy, dtype=np.float64)
    q = np.asarray(query_xy, dtype=np.float64)
    ok = np.isfinite(v)
    out = np.full(q.shape[:-1], np.nan)
    if not ok.any():
        return out
    dist, idx = cKDTree(src[ok]).query(q.reshape(-1, 2), distance_upper_bound=max_dist)
    hit = np.isfinite(dist)
    flat = out.reshape(-1)
    flat[hit] = v[ok][idx[hit]]
    return out


@dataclass(frozen=True)
class FlowState:
    """One steady model state in SI: total inflow and per-cell results (NaN where dry).
    `cell_xy` stays in CRS units."""

    discharge: float
    cell_xy: F
    wse: F
    depth: F | None = None
    velocity: F | None = None


@dataclass(frozen=True)
class Package:
    """Everything a structured-grid solver needs, in SI. Arrays are (ni, nj) on nodes unless
    noted; `xy` is (ni, nj, 2) in metres; `n_cell` is (ni-1, nj-1)."""

    xy: F
    chainage: F
    elevation: F
    n_node: F | None = None
    n_cell: F | None = None
    wse: F | None = None
    depth: F | None = None
    discharge: float | None = None
    stage_downstream: float | None = None
    stage_upstream: float | None = None
    xy_unit_m: float = 1.0

    @property
    def ni(self) -> int:
        return int(self.xy.shape[0])

    @property
    def nj(self) -> int:
        return int(self.xy.shape[1])


def _spacing(flow: FlowState) -> float:
    """Median distance from a wet cell to its nearest wet neighbour (0 with fewer than two)."""
    ok = np.isfinite(np.asarray(flow.wse, dtype=np.float64))
    pts = np.asarray(flow.cell_xy, dtype=np.float64)[ok]
    if len(pts) < 2:
        return 0.0
    dist, _ = cKDTree(pts).query(pts, k=2)
    return float(np.median(dist[:, 1]))


def _end_stage(wse: F, dist: F, limit: float) -> float | None:
    """Mean water surface of the first section (in the order given) that has any, no farther
    than `limit` from the end: model cell centres sit inside the boundary, so on a fine grid
    the end section itself can have none within reach."""
    for row, d in zip(wse, dist, strict=True):
        if d > limit:
            break
        ok = np.isfinite(row)
        if ok.any():
            return float(row[ok].mean())
    return None


def prepare(grid: CurviGrid, terrain: Path | Sequence[Path], *, xy_unit_m: float, z_unit_m: float,
            roughness: Path | float | None = None, flow: FlowState | None = None,
            wse_max_dist: float | None = None) -> Package:
    """`terrain` is one raster or a stack (later rasters win where they have values).
    Sample terrain (bilinear) and Manning's n (nearest; a raster or one value) onto `grid` and
    attach the flow state. Node WSE and depth come from the nearest wet cell within
    `wse_max_dist` (CRS units; default the larger of 2 section spacings and 1.5 times the
    typical spacing of the wet cells, so a grid finer than the source model still finds
    them); the stages are the mean node WSE of the end sections, or of the nearest section
    within twice that distance when an end section has none. ValueError if any node has no
    terrain value."""
    x, y = grid.xy[..., 0], grid.xy[..., 1]
    z = sample_raster(terrain, x, y) * z_unit_m
    if not np.isfinite(z).all():
        raise ValueError(f"{int((~np.isfinite(z)).sum())} of {z.size} grid nodes have no terrain "
                         "value (outside the raster or nodata); narrow or shorten the grid")
    n_node: F | None = None
    n_cell: F | None = None
    if roughness is not None:
        c = grid.cell_centres()
        if isinstance(roughness, Path):
            n_node = sample_raster(roughness, x, y, method="nearest")
            n_cell = sample_raster(roughness, c[..., 0], c[..., 1], method="nearest")
            for name, a in (("nodes", n_node), ("cells", n_cell)):
                if not np.isfinite(a).all():
                    raise ValueError(f"{int((~np.isfinite(a)).sum())} grid {name} have no "
                                     "roughness value")
        else:
            n_node = np.full(x.shape, float(roughness))
            n_cell = np.full(c.shape[:2], float(roughness))
    wse = depth = None
    q = ds = us = None
    if flow is not None:
        if wse_max_dist is None:
            reach = max(2.0 * float(grid.s[1] - grid.s[0]), 1.5 * _spacing(flow))
        else:
            reach = float(wse_max_dist)
        wse = nearest_values(flow.cell_xy, flow.wse, grid.xy, reach)
        depth = np.where(np.isfinite(wse), np.maximum(wse - z, 0.0), np.nan)
        q = float(flow.discharge)
        ds = _end_stage(wse[::-1], grid.s[-1] - grid.s[::-1], 2.0 * reach)
        us = _end_stage(wse, grid.s - grid.s[0], 2.0 * reach)
    return Package(xy=grid.xy * xy_unit_m, chainage=grid.s * xy_unit_m, elevation=z,
                   n_node=n_node, n_cell=n_cell, wse=wse, depth=depth, discharge=q,
                   stage_downstream=ds, stage_upstream=us, xy_unit_m=float(xy_unit_m))


def grid_attributes(pkg: Package, solver: str, *, drag_depth: float | Literal["local"] | None = None
                    ) -> tuple[dict[str, F], dict[str, F]]:
    """(node, cell) grid attributes named as the solver's definition names them.

    fastmech: node `Elevation`; node `roughness` (drag coefficient) only when `drag_depth` is
    given and the package has n. "local" uses the node depth, and nodes that are dry in the model
    state take the median wet depth. nays2dh: node `Elevation`; node `Elevation_zb` (fixed bed)
    equal to it, i.e. no erodible layer, which only matters with bed deformation on; cell
    `roughness_cell` (n)."""
    if solver not in SOLVERS:
        raise ValueError(f"unknown solver {solver!r} (known: {', '.join(SOLVERS)})")
    node: dict[str, F] = {"Elevation": pkg.elevation}
    cell: dict[str, F] = {}
    if solver == "fastmech":
        if drag_depth is not None and pkg.n_node is not None:
            if drag_depth == "local":
                if pkg.depth is None:
                    raise ValueError('drag_depth="local" needs a flow state')
                wet = np.isfinite(pkg.depth) & (pkg.depth > 0)
                if not wet.any():
                    raise ValueError("no wet grid nodes to take a local depth from")
                h = np.where(wet, pkg.depth, float(np.median(pkg.depth[wet])))
            else:
                if not float(drag_depth) > 0:
                    raise ValueError("drag_depth must be positive")
                h = np.full(pkg.elevation.shape, float(drag_depth))
            node["roughness"] = drag_from_manning(pkg.n_node, h)
    else:
        node["Elevation_zb"] = pkg.elevation
        if pkg.n_cell is not None:
            cell["roughness_cell"] = pkg.n_cell
    return node, cell


def _fmt(v: float, precision: int) -> str:
    return f"{v:.{precision}g}"


def write_grid_csv(path: Path, xy: ArrayLike, node_attrs: Mapping[str, ArrayLike] | None = None,
                   cell_attrs: Mapping[str, ArrayLike] | None = None, *, precision: int = 12
                   ) -> Path:
    """iRIC grid CSV. Indices are 0-based, K and Z are 0; cell values sit on the row of the
    cell's lowest (i, j) node and are blank on the last i and j rows. Non-finite values are
    refused: the importer needs a value everywhere."""
    a = np.asarray(xy, dtype=np.float64)
    if a.ndim != 3 or a.shape[2] != 2 or a.shape[0] < 2 or a.shape[1] < 2:
        raise ValueError(f"xy must be (ni, nj, 2) with ni, nj >= 2 (got {a.shape})")
    ni, nj = a.shape[:2]
    nodes = {k: np.asarray(v, dtype=np.float64) for k, v in (node_attrs or {}).items()}
    cells = {k: np.asarray(v, dtype=np.float64) for k, v in (cell_attrs or {}).items()}
    for kind, d, shape in (("node", nodes, (ni, nj)), ("cell", cells, (ni - 1, nj - 1))):
        for k, v in d.items():
            if v.shape != shape:
                raise ValueError(f"{kind} attribute {k!r} has shape {v.shape}, expected {shape}")
            if not np.isfinite(v).all():
                raise ValueError(f"{kind} attribute {k!r} has non-finite values")
    if not np.isfinite(a).all():
        raise ValueError("xy has non-finite values")
    head = ["I", "J", "K", "X", "Y", "Z"] + [f"N_{k}" for k in nodes] + [f"C_{k}" for k in cells]
    lines = ["IMAX,JMAX,KMAX", f"{ni},{nj},1", ",".join(head)]
    for j in range(nj):
        for i in range(ni):
            row = [str(i), str(j), "0", _fmt(a[i, j, 0], precision), _fmt(a[i, j, 1], precision),
                   "0"]
            row += [_fmt(v[i, j], precision) for v in nodes.values()]
            inside = i < ni - 1 and j < nj - 1
            row += [_fmt(v[i, j], precision) if inside else "" for v in cells.values()]
            lines.append(",".join(row))
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\r\n")
    return out


def write_tpo(path: Path, x: ArrayLike, y: ArrayLike, z: ArrayLike, *, precision: int = 12
              ) -> Path:
    """Topography point file: the point count, then `x y z` per line. Non-finite points are
    dropped."""
    xa, ya, za = (np.asarray(v, dtype=np.float64).ravel() for v in (x, y, z))
    ok = np.isfinite(xa) & np.isfinite(ya) & np.isfinite(za)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="ascii", newline="\r\n") as f:
        f.write(f"{int(ok.sum())}\n")
        for px, py, pz in zip(xa[ok], ya[ok], za[ok], strict=True):
            f.write(f"{_fmt(px, precision)} {_fmt(py, precision)} {_fmt(pz, precision)}\n")
    return out


def write_points_csv(path: Path, x: ArrayLike, y: ArrayLike, columns: Mapping[str, ArrayLike],
                     *, precision: int = 12) -> Path:
    """`X,Y,<columns>` point table (iRIC measured data). Rows where the first column is not
    finite are dropped; other non-finite values are written blank."""
    xa, ya = (np.asarray(v, dtype=np.float64).ravel() for v in (x, y))
    cols = {k: np.asarray(v, dtype=np.float64).ravel() for k, v in columns.items()}
    if not cols:
        raise ValueError("at least one value column is required")
    first = next(iter(cols.values()))
    keep = np.flatnonzero(np.isfinite(first) & np.isfinite(xa) & np.isfinite(ya))
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="ascii", newline="\r\n") as f:
        f.write(",".join(["X", "Y", *cols]) + "\n")
        for k in keep:
            vals = [_fmt(c[k], precision) if np.isfinite(c[k]) else "" for c in cols.values()]
            f.write(",".join([_fmt(xa[k], precision), _fmt(ya[k], precision), *vals]) + "\n")
    return out


def write_raster_scaled(src: Path, dst: Path, *, xy_scale: float, value_scale: float,
                        bounds: tuple[float, float, float, float] | None = None) -> Path:
    """Copy band 1 of `src` as float32 GeoTIFF with values times `value_scale` and georeferencing
    times `xy_scale`, clipped to `bounds` (minx, miny, maxx, maxy in the source CRS units). The
    CRS is kept only when `xy_scale` is 1; scaled coordinates are not a registered CRS."""
    nodata = -9999.0
    with rasterio.open(src) as ds:
        win = rasterio.windows.Window(0, 0, ds.width, ds.height)
        if bounds is not None:
            want = rasterio.windows.from_bounds(*bounds, transform=ds.transform)
            c0 = max(int(np.floor(want.col_off + 1e-9)), 0)
            r0 = max(int(np.floor(want.row_off + 1e-9)), 0)
            c1 = min(int(np.ceil(want.col_off + want.width - 1e-9)), ds.width)
            r1 = min(int(np.ceil(want.row_off + want.height - 1e-9)), ds.height)
            if c1 <= c0 or r1 <= r0:
                raise ValueError(f"{src}: bounds {bounds} do not overlap the raster")
            win = rasterio.windows.Window(c0, r0, c1 - c0, r1 - r0)
        a = ds.read(1, window=win, masked=True).astype("f8").filled(np.nan)
        t = ds.window_transform(win)
        crs = ds.crs if xy_scale == 1.0 else None
    data = np.where(np.isfinite(a), a * value_scale, nodata).astype("float32")
    k = float(xy_scale)
    t2 = Affine(t.a * k, t.b * k, t.c * k, t.d * k, t.e * k, t.f * k)
    out = Path(dst)
    out.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out, "w", driver="GTiff", height=data.shape[0], width=data.shape[1],
                       count=1, dtype="float32", transform=t2, crs=crs, nodata=nodata,
                       compress="deflate") as o:
        o.write(data, 1)
    return out


def summary(pkg: Package, solver: str, node: Mapping[str, Any], cell: Mapping[str, Any],
            drag_depth: float | str | None, extra: Mapping[str, Any] | None = None
            ) -> dict[str, Any]:
    """What a person needs to finish the solver setup, as JSON-ready data."""
    profile = []
    if pkg.wse is not None:
        ok = np.isfinite(pkg.wse)
        count = ok.sum(axis=1)
        mean = np.where(count > 0, np.where(ok, pkg.wse, 0.0).sum(axis=1) / np.maximum(count, 1),
                        np.nan)
        profile = [{"chainage_m": float(s), "wse_m": (float(w) if np.isfinite(w) else None)}
                   for s, w in zip(pkg.chainage, mean, strict=True)]
    return {
        "solver": solver,
        "grid": {"ni": pkg.ni, "nj": pkg.nj, "i": "along the centerline as given",
                 "j": "right bank to left bank looking along i"},
        "units": {"length": "m", "discharge": "m3/s", "xy_unit_m": pkg.xy_unit_m,
                  "xy_note": "x, y are the source coordinates times xy_unit_m"},
        "discharge_cms": pkg.discharge,
        "stage_downstream_m": pkg.stage_downstream,
        "stage_upstream_m": pkg.stage_upstream,
        "wse_profile": profile,
        "node_attributes": sorted(node),
        "cell_attributes": sorted(cell),
        "roughness": {
            "manning_n_available": pkg.n_node is not None,
            "fastmech_drag_depth": drag_depth,
            "note": "FaSTMECH roughness is Cd = g n^2 / h^(1/3) with h = fastmech_drag_depth",
        },
        **dict(extra or {}),
    }


def write_package(pkg: Package, out_dir: Path, *, solver: str = "fastmech",
                  drag_depth: float | Literal["local"] | None = None,
                  terrain: Path | Sequence[Path] | None = None, z_unit_m: float = 1.0,
                  roughness: Path | None = None, flow: FlowState | None = None,
                  tpo_spacing: float = 0.0, margin: float = 0.0,
                  extra: Mapping[str, Any] | None = None) -> dict[str, Path]:
    """Write the files listed in the module docstring to `out_dir`; returns name -> path.
    Rasters are clipped to the grid's bounding box plus `margin` (source CRS units).
    A terrain stack is written one file per raster that overlaps the grid, `elevation_1.tif`
    upward in stack order (import them all; the highest number has priority). `tpo_spacing` > 0
    (source CRS units) also writes the stack sampled on a square lattice as `elevation.tpo`."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    node, cell = grid_attributes(pkg, solver, drag_depth=drag_depth)
    paths = {"grid": write_grid_csv(out / "grid.csv", pkg.xy, node, cell)}
    k = pkg.xy_unit_m
    src_xy = pkg.xy / k
    bounds = (float(src_xy[..., 0].min()) - margin, float(src_xy[..., 1].min()) - margin,
              float(src_xy[..., 0].max()) + margin, float(src_xy[..., 1].max()) + margin)
    if terrain is not None:
        stack = [terrain] if isinstance(terrain, (str, Path)) else list(terrain)
        written = 0
        for one in stack:
            name = "elevation" if len(stack) == 1 else f"elevation_{written + 1}"
            try:
                paths[name] = write_raster_scaled(Path(one), out / f"{name}.tif", xy_scale=k,
                                                  value_scale=z_unit_m, bounds=bounds)
            except ValueError:
                continue                         # this raster does not reach the grid
            written += 1
        if tpo_spacing > 0:
            gx, gy = np.meshgrid(np.arange(bounds[0], bounds[2] + tpo_spacing / 2, tpo_spacing),
                                 np.arange(bounds[1], bounds[3] + tpo_spacing / 2, tpo_spacing))
            gz = sample_raster(stack, gx, gy) * z_unit_m
            paths["elevation_points"] = write_tpo(out / "elevation.tpo", gx * k, gy * k, gz)
    if roughness is not None:
        paths["manning_n"] = write_raster_scaled(roughness, out / "manning_n.tif", xy_scale=k,
                                                 value_scale=1.0, bounds=bounds)
    if flow is not None:
        columns: dict[str, ArrayLike] = {"WaterSurfaceElevation": flow.wse}
        if flow.depth is not None:
            columns["Depth"] = flow.depth
        if flow.velocity is not None:
            columns["Velocity"] = flow.velocity
        paths["wse"] = write_points_csv(out / "wse.csv", flow.cell_xy[:, 0] * k,
                                        flow.cell_xy[:, 1] * k, columns)
    info = summary(pkg, solver, node, cell, drag_depth, extra)
    paths["summary"] = out / "summary.json"
    paths["summary"].write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return paths

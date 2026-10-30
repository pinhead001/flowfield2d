"""Results reader for RAS 2025 output HDF5 (layout: probe step D; values checked in the GUI at E8).

- Depth: `/Results/Output Blocks/Base Output/2D Flow Areas/<area>/Cell Depth` [time, cell] (f4)
- Velocity: `.../Face Velocity` [time, face] (f4, face-normal scalar)
- Face flow: `.../DEBUG/FaceFlow` [time, face] (f4)
- Coordinates: `/Geometry/2D Flow Areas/<area>/Cell Coordinates` [cell, 2] (f8)
- Perimeter faces and nodes: `/Geometry/2D Flow Areas/<area>/Face Data` [face, 4],
  `.../Node Coordinates` [node, 2]
- BC lines: `/Boundary Conditions/BC Lines/Polyline` with attrs `Count`, `Start`
- WSE is not stored; WSE = depth + `/Geometry/2D Flow Areas/<area>/Property Tables/Cell Minimum
  Elevation`; dry cells (depth <= min_depth) give NaN
- Time: `/Results/Output Blocks/Base Output/Time` in days from the plan start
- Run status: `/Results/Compute Summary` attrs `Success`, `Solver`, `Compute Log`
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import shapely
from numpy.typing import NDArray
from shapely.geometry import LineString

from flowfield2d.engines.ras2025.split import bc_polylines
from flowfield2d.ml.graph import MeshGraph

BASE = "/Results/Output Blocks/Base Output"
GEOM = "/Geometry/2D Flow Areas"


@dataclass(frozen=True)
class ComputeSummary:
    success: bool
    solver: str
    log: str


def _text(v: Any) -> str:
    return v.decode("utf-8", "replace").rstrip("\x00") if isinstance(v, bytes) else str(v)


def face_flows(face_data: NDArray[Any], zmin: NDArray[Any], depth: NDArray[Any],
               velocity: NDArray[Any], tables: NDArray[Any], start: NDArray[Any],
               faces: NDArray[Any]) -> NDArray[np.float64]:
    """Flow through `faces` = face velocity x face area; the area from the face's elevation-area
    table (`Face Tables` columns elevation, area; rows from `start`) at the higher water surface of
    its wet adjacent cells, extrapolated linearly above the table top; 0 where both are dry."""
    n = len(zmin)
    ends = np.append(np.asarray(start)[1:], len(tables))
    out = np.zeros(len(faces), dtype=np.float64)
    for i, j in enumerate(np.asarray(faces, dtype=np.int64)):
        ws = [float(zmin[c] + depth[c]) for c in face_data[j, :2] if 0 <= c < n and depth[c] > 0]
        if not ws:
            continue
        tab = tables[start[j]:ends[j]]
        z, a, w = tab[:, 0], tab[:, 1], max(ws)
        if w <= z[-1] or len(z) < 2:
            area = float(np.interp(w, z, a, left=0.0))
        else:
            area = float(a[-1] + (a[-1] - a[-2]) / (z[-1] - z[-2]) * (w - z[-1]))
        out[i] = float(velocity[j]) * area
    return out


class _CellTables:
    """Cell elevation-volume tables (`Cell Tables` columns elevation, volume; rows from `start`)
    padded to a dense array for vectorised lookups."""

    def __init__(self, tables: NDArray[Any], start: NDArray[Any]) -> None:
        start = np.asarray(start, dtype=np.int64)
        n = len(start)
        ends = np.append(start[1:], len(tables))
        counts = ends - start
        m = int(counts.max())
        rows = start[:, None] + np.minimum(np.arange(m)[None, :], counts[:, None] - 1)
        self.z = np.asarray(tables, dtype=np.float64)[rows, 0]
        self.v = np.asarray(tables, dtype=np.float64)[rows, 1]
        self.z[np.arange(m)[None, :] >= counts[:, None]] = np.inf    # padding never brackets
        r, last = np.arange(n), counts - 1
        prev = np.maximum(last - 1, 0)
        self.ztop, self.vtop = self.z[r, last], self.v[r, last]
        dz = self.ztop - self.z[r, prev]
        self.slope = np.where(dz > 0, (self.vtop - self.v[r, prev]) / np.where(dz > 0, dz, 1.0),
                              0.0)

    def volume(self, wse: NDArray[np.float64], wet: NDArray[np.bool_]) -> float:
        n, m = self.z.shape
        r = np.arange(n)
        i = np.clip((self.z < wse[:, None]).sum(axis=1), 1, m - 1)
        z0, z1, v0, v1 = self.z[r, i - 1], self.z[r, i], self.v[r, i - 1], self.v[r, i]
        inside = np.isfinite(z1) & (wse <= self.ztop)
        frac = np.where(inside, (wse - z0) / np.where(inside & (z1 > z0), z1 - z0, 1.0), 0.0)
        vol = np.where(inside, v0 + (v1 - v0) * frac, self.vtop + self.slope * (wse - self.ztop))
        return float(np.where(wet, np.maximum(vol, 0.0), 0.0).sum())


def storage_volume(zmin: NDArray[Any], depth: NDArray[Any], tables: NDArray[Any],
                   start: NDArray[Any]) -> NDArray[np.float64]:
    """Water stored in the area per output (`depth` outputs x cells): each wet cell's
    elevation-volume table at its water surface, extrapolated linearly above the table top. For
    results without boundary flows or cell volumes (RAS 2025 GPU): outflow = inflow - dV/dt."""
    ct = _CellTables(tables, start)
    z = np.asarray(zmin, dtype=np.float64)
    d = np.asarray(depth, dtype=np.float64)
    return np.array([ct.volume(z + row, row > 0) for row in d], dtype=np.float64)


def cell_max_face_speed(face_data: NDArray[Any], velocity: NDArray[Any],
                        n_cells: int) -> NDArray[np.float64]:
    """Largest |face velocity| over each cell's faces (0 for a cell whose faces carry nothing:
    a stagnant, disconnected cell)."""
    out = np.zeros(int(n_cells), dtype=np.float64)
    speed = np.abs(np.asarray(velocity, dtype=np.float64))
    for side in (0, 1):
        c = np.asarray(face_data[:, side], dtype=np.int64)
        ok = (c >= 0) & (c < n_cells)
        np.maximum.at(out, c[ok], speed[ok])
    return out


def cell_velocity_vectors(face_data: NDArray[Any], nodes: NDArray[Any], velocity: NDArray[Any],
                          n_cells: int, depth: NDArray[Any] | None = None,
                          min_depth: float = 0.0) -> NDArray[np.float64]:
    """Cell velocity vectors (n_cells, 2) reconstructed from the face-normal velocities: per
    cell the least-squares vector whose normal components best match its faces' velocities,
    weighted by face length (the file carries no cell vectors; this is the mapper's picture).

    Convention (checked on a production result, 2026-10-30: the reconstructed speed matches the
    mapper's velocity raster at the cell centres, median ratio 1.016, r 0.987, and the vectors
    point down the centerline): `Face Data` rows are (cell_a, cell_b, node_i, node_j), the
    face normal is the tangent node_i -> node_j turned clockwise, (ty, -tx), and a positive
    face velocity flows from cell_a to cell_b along it. Faces with cell_b < 0 are perimeter
    faces of cell_a. A cell whose faces do not span two directions, or a dry cell when
    `depth` is given (depth <= `min_depth`), gets NaN."""
    n = int(n_cells)
    fd = np.asarray(face_data, dtype=np.int64)
    xy = np.asarray(nodes, dtype=np.float64)
    v = np.asarray(velocity, dtype=np.float64)
    d = xy[fd[:, 3]] - xy[fd[:, 2]]
    length = np.hypot(d[:, 0], d[:, 1])
    ok = length > 0
    safe = np.where(ok, length, 1.0)
    nx, ny = d[:, 1] / safe, -d[:, 0] / safe
    a = np.zeros((n, 3))                        # symmetric normal matrix: xx, xy, yy
    b = np.zeros((n, 2))
    for side, sign in ((0, 1.0), (1, -1.0)):    # outward normal: +n for cell_a, -n for cell_b
        c = fd[:, side]
        m = ok & (c >= 0) & (c < n)
        ox, oy, w, vo = sign * nx[m], sign * ny[m], length[m], sign * v[m]
        np.add.at(a, (c[m], 0), w * ox * ox)
        np.add.at(a, (c[m], 1), w * ox * oy)
        np.add.at(a, (c[m], 2), w * oy * oy)
        np.add.at(b, (c[m], 0), w * ox * vo)
        np.add.at(b, (c[m], 1), w * oy * vo)
    det = a[:, 0] * a[:, 2] - a[:, 1] ** 2
    trace = a[:, 0] + a[:, 2]
    good = det > 1e-9 * np.maximum(trace, 1e-300) ** 2
    out = np.full((n, 2), np.nan)
    inv = np.where(good, det, 1.0)
    out[good, 0] = ((a[:, 2] * b[:, 0] - a[:, 1] * b[:, 1]) / inv)[good]
    out[good, 1] = ((a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) / inv)[good]
    if depth is not None:
        h = np.asarray(depth, dtype=np.float64)[:n]
        with np.errstate(invalid="ignore"):
            out[~(np.isfinite(h) & (h > min_depth))] = np.nan
    return out


class ResultsReader:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _read(self, dataset: str) -> NDArray[Any]:
        with h5py.File(self.path, "r", locking=False) as f:
            return np.asarray(f[dataset][()])

    def areas(self) -> list[str]:
        with h5py.File(self.path, "r", locking=False) as f:
            return sorted(f[BASE + "/2D Flow Areas"].keys())

    def time_days(self) -> NDArray[np.float64]:
        return self._read(BASE + "/Time").astype(np.float64)

    def cell_coordinates(self, area: str) -> NDArray[np.float64]:
        path = f"{GEOM}/{area}/Cell Coordinates"
        return self._read(path).astype(np.float64)

    def cell_depth(self, area: str, t: int) -> NDArray[np.float64]:
        with h5py.File(self.path, "r", locking=False) as f:
            return np.asarray(f[f"{BASE}/2D Flow Areas/{area}/Cell Depth"][t], dtype=np.float64)

    def face_velocity(self, area: str, t: int) -> NDArray[np.float64]:
        with h5py.File(self.path, "r", locking=False) as f:
            return np.asarray(f[f"{BASE}/2D Flow Areas/{area}/Face Velocity"][t], dtype=np.float64)

    def face_flow(self, area: str, t: int) -> NDArray[np.float64]:
        with h5py.File(self.path, "r", locking=False) as f:
            return np.asarray(f[f"{BASE}/2D Flow Areas/{area}/DEBUG/FaceFlow"][t], dtype=np.float64)

    def cell_min_elevation(self, area: str) -> NDArray[np.float64]:
        path = f"{GEOM}/{area}/Property Tables/Cell Minimum Elevation"
        return self._read(path).astype(np.float64)

    def cell_wse(self, area: str, t: int, min_depth: float = 0.0) -> NDArray[np.float64]:
        d = self.cell_depth(area, t)
        wse = d + self.cell_min_elevation(area)
        return np.where(d > min_depth, wse, np.nan)

    def cell_wse_series(
        self, area: str, cells: Sequence[int], min_depth: float = 0.0
    ) -> NDArray[np.float64]:
        idx = np.asarray(cells, dtype=np.int64)
        depth = self._read(f"{BASE}/2D Flow Areas/{area}/Cell Depth").astype(np.float64)[:, idx]
        wse = depth + self.cell_min_elevation(area)[idx]
        return np.where(depth > min_depth, wse, np.nan)

    def boundary_faces(self, area: str, line: str, tol: float) -> NDArray[np.int64]:
        bcs = bc_polylines(self.path)
        if line not in bcs:
            raise KeyError(f"unknown BC line: {line}")
        poly = bcs[line]

        with h5py.File(self.path, "r", locking=False) as f:
            face_data = np.asarray(f[f"{GEOM}/{area}/Face Data"][()])
            nodes = np.asarray(f[f"{GEOM}/{area}/Node Coordinates"][()], dtype=np.float64)

        perim = np.flatnonzero(face_data[:, 1] == -1)
        near_a = shapely.distance(poly, shapely.points(nodes[face_data[perim, 2]])) <= tol
        near_b = shapely.distance(poly, shapely.points(nodes[face_data[perim, 3]])) <= tol
        keep = np.asarray(near_a & near_b, dtype=bool)
        matching: NDArray[np.int64] = perim[keep].astype(np.int64)
        if matching.size == 0:
            raise ValueError(f"no faces qualify for boundary line {line!r} within tolerance {tol}")
        return matching

    def boundary_flow(self, area: str, line: str, tol: float) -> NDArray[np.float64]:
        faces = self.boundary_faces(area, line, tol)
        flows = self._read(f"{BASE}/2D Flow Areas/{area}/DEBUG/FaceFlow").astype(np.float64)
        return np.asarray(flows[:, faces].sum(axis=1), dtype=np.float64)

    def boundary_flow_reconstructed(self, area: str, line: str, tol: float
                                    ) -> NDArray[np.float64]:
        """Boundary flow per output rebuilt from face velocity and the face property tables
        (`face_flows`): for results without face-flow output (the RAS 2025 GPU solver writes
        zeros). Within ~0.2-2.5% of RAS's own face flow on the pilot (probe 2026-10-25)."""
        faces = self.boundary_faces(area, line, tol)
        g, b = f"{GEOM}/{area}", f"{BASE}/2D Flow Areas/{area}"
        with h5py.File(self.path, "r", locking=False) as f:
            ft = f[f"{g}/Property Tables/Face Tables"]
            tables, start = np.asarray(ft[()]), np.asarray(ft.attrs["Start"])
            face_data = np.asarray(f[f"{g}/Face Data"][()])
            zmin = np.asarray(f[f"{g}/Property Tables/Cell Minimum Elevation"][()])
            depth = np.asarray(f[f"{b}/Cell Depth"][()])
            vel = np.asarray(f[f"{b}/Face Velocity"][()])
        return np.array([face_flows(face_data, zmin, depth[k], vel[k], tables, start, faces).sum()
                         for k in range(depth.shape[0])], dtype=np.float64)

    def storage_volume(self, area: str) -> NDArray[np.float64]:
        """Water stored in `area` per output, from the cell elevation-volume tables (see
        `storage_volume`); read one output at a time."""
        g, b = f"{GEOM}/{area}/Property Tables", f"{BASE}/2D Flow Areas/{area}"
        with h5py.File(self.path, "r", locking=False) as f:
            zmin = np.asarray(f[f"{g}/Cell Minimum Elevation"][()], dtype=np.float64)
            ct = f[f"{g}/Cell Tables"]
            tables = _CellTables(np.asarray(ct[()]), np.asarray(ct.attrs["Start"]))
            depth = f[f"{b}/Cell Depth"]
            n = len(zmin)
            out = []
            for k in range(depth.shape[0]):
                row = np.asarray(depth[k], dtype=np.float64)[:n]
                out.append(tables.volume(zmin + row, row > 0))
        return np.array(out, dtype=np.float64)

    def cell_max_face_speed(self, area: str, t: int) -> NDArray[np.float64]:
        """Per real cell, the largest |face velocity| at output `t` (0 = stagnant cell)."""
        g = f"{GEOM}/{area}"
        with h5py.File(self.path, "r", locking=False) as f:
            face_data = np.asarray(f[f"{g}/Face Data"][()])
            n = int(f[f"{g}/Property Tables/Cell Minimum Elevation"].shape[0])
            vel = np.asarray(f[f"{BASE}/2D Flow Areas/{area}/Face Velocity"][t])
        return cell_max_face_speed(face_data, vel, n)

    def cell_velocity(self, area: str, t: int, min_depth: float = 0.0) -> NDArray[np.float64]:
        """Per real cell, the velocity vector (n, 2) at output `t` reconstructed from the face
        velocities (`cell_velocity_vectors`); dry cells (depth <= `min_depth`) are NaN."""
        g = f"{GEOM}/{area}"
        with h5py.File(self.path, "r", locking=False) as f:
            face_data = np.asarray(f[f"{g}/Face Data"][()])
            nodes = np.asarray(f[f"{g}/Node Coordinates"][()], dtype=np.float64)
            n = int(f[f"{g}/Property Tables/Cell Minimum Elevation"].shape[0])
            vel = np.asarray(f[f"{BASE}/2D Flow Areas/{area}/Face Velocity"][t])
            depth = np.asarray(f[f"{BASE}/2D Flow Areas/{area}/Cell Depth"][t])
        return cell_velocity_vectors(face_data, nodes, vel, n, depth=depth, min_depth=min_depth)

    def boundary_lines(self) -> dict[str, LineString]:
        """BC lines as run (the result file carries the BC layer)."""
        return bc_polylines(self.path)

    def mesh_graph(self, area: str) -> MeshGraph:
        """The mesh as a graph: cells -> nodes, interior faces -> edges (see `flowfield2d.ml`)."""
        with h5py.File(self.path, "r", locking=False) as f:
            fd = np.asarray(f[f"{GEOM}/{area}/Face Data"][()], dtype=np.int64)
            nodes = np.asarray(f[f"{GEOM}/{area}/Node Coordinates"][()], dtype=np.float64)
        xy = self.cell_coordinates(area)
        bed = self.cell_min_elevation(area)
        n = min(len(xy), len(bed))
        a, b = fd[:, 0], fd[:, 1]
        interior = (a >= 0) & (b >= 0) & (a < n) & (b < n)
        lengths = np.hypot(*(nodes[fd[:, 2]] - nodes[fd[:, 3]]).T)
        boundary = np.zeros(n, dtype=bool)
        perim = (b < 0) & (a >= 0) & (a < n)
        boundary[a[perim]] = True
        return MeshGraph(xy=xy[:n], bed=bed[:n], edges=np.vstack([a[interior], b[interior]]),
                         face_length=lengths[interior], boundary=boundary)

    def compute_summary(self) -> ComputeSummary:
        with h5py.File(self.path, "r", locking=False) as f:
            a = f["/Results/Compute Summary"].attrs
            return ComputeSummary(bool(a.get("Success", 0)), _text(a.get("Solver", "")),
                                  _text(a.get("Compute Log", "")))

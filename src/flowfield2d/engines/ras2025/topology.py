"""RAS 2025 mesh topology under /Geometry/Mesh Topology: `Nodes` (n, 2), `Arc Connectivity`
(start node, end node; int32), `Arc Internal Points` (all arcs' interior vertices stacked;
attributes `Count` and `Start` hold one entry per arc), `Arc Attributes` (compound row per
arc), `Control Points` and `Control Point Attributes` (one region per control point;
`PatchType` Quad=0, TrianglePaver=1, Cartesian=2). A quad patch needs a region bounded by
at least 4 arcs (probe 2026-10-25). `geometry modify` cannot create arcs or regions.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any

import h5py
import numpy as np
from shapely.geometry import LineString, Point

from flowfield2d.channel_patches import ChannelPatches
from flowfield2d.engines.ras2025.h5edit import recreate_dataset

__all__ = ["Arc", "PatchType", "Region", "add_channel", "add_topology"]

_TOPO: str = "/Geometry/Mesh Topology"


class PatchType(IntEnum):
    """Patch generation algorithm for a mesh region."""

    QUAD = 0
    TRIANGLE_PAVER = 1
    CARTESIAN = 2


@dataclass(frozen=True)
class Arc:
    """Breakline or patch edge arc in mesh topology."""

    line: LineString
    cell_size: float | None = None
    follow_exactly: bool = True


@dataclass(frozen=True)
class Region:
    """Control point and patch specification for a mesh region."""

    point: Point
    patch: PatchType
    cell_size: float


def _validate_arc(arc: Arc, snap_tol: float) -> None:
    if arc.line.is_empty:
        raise ValueError("Arc LineString is empty")
    coords = list(arc.line.coords)
    if len(coords) < 2:
        raise ValueError("Arc must have at least 2 points")
    if len(set(coords)) < 2:
        raise ValueError("Arc has fewer than 2 distinct points")
    if arc.line.length <= 0.0:
        raise ValueError("Arc has zero length")
    start = coords[0]
    end = coords[-1]
    if math.hypot(start[0] - end[0], start[1] - end[1]) <= snap_tol:
        raise ValueError("Arc is closed (start == end within snap_tol)")
    if arc.cell_size is not None and (arc.cell_size <= 0.0 or np.isnan(arc.cell_size)):
        raise ValueError(f"Arc cell_size must be positive, got {arc.cell_size}")


def _validate_region(region: Region) -> None:
    if region.point.is_empty:
        raise ValueError("Region Point is empty")
    if region.cell_size <= 0.0 or np.isnan(region.cell_size):
        raise ValueError(f"Region cell_size must be positive, got {region.cell_size}")


def _find_or_add_node(
    pt: tuple[float, float],
    nodes: list[list[float]],
    snap_tol: float,
) -> int:
    px, py = pt
    for idx, node in enumerate(nodes):
        if math.hypot(node[0] - px, node[1] - py) <= snap_tol:
            return idx
    nodes.append([px, py])
    return len(nodes) - 1


def _append_arcs(topo: Any, arcs: Sequence[Arc], snap_tol: float) -> None:
    old_nodes = topo["Nodes"][()]
    nodes_list: list[list[float]] = [list(map(float, row)) for row in old_nodes]

    old_conn = topo["Arc Connectivity"][()]
    conn_dtype = old_conn.dtype
    new_conn_rows: list[list[int]] = []

    old_aip = topo["Arc Internal Points"]
    old_internal_points = old_aip[()]
    old_count = old_aip.attrs["Count"]
    old_start = old_aip.attrs["Start"]
    count_dtype = old_count.dtype
    start_dtype = old_start.dtype

    internal_points_list: list[list[float]] = []
    new_counts: list[int] = []
    new_starts: list[int] = []
    current_internal_offset = len(old_internal_points)

    for arc in arcs:
        coords = list(arc.line.coords)
        start_pt = (float(coords[0][0]), float(coords[0][1]))
        end_pt = (float(coords[-1][0]), float(coords[-1][1]))

        start_node = _find_or_add_node(start_pt, nodes_list, snap_tol)
        end_node = _find_or_add_node(end_pt, nodes_list, snap_tol)
        new_conn_rows.append([start_node, end_node])

        interior = coords[1:-1]
        new_starts.append(current_internal_offset)
        new_counts.append(len(interior))
        for pt in interior:
            internal_points_list.append([float(pt[0]), float(pt[1])])
        current_internal_offset += len(interior)

    # 1. Nodes
    new_nodes = np.array(nodes_list, dtype=old_nodes.dtype).reshape(-1, 2)
    recreate_dataset(topo, "Nodes", new_nodes)

    # 2. Arc Connectivity
    conn_array = np.array(new_conn_rows, dtype=conn_dtype).reshape(-1, 2)
    if len(old_conn) > 0:
        combined_conn = np.vstack([old_conn, conn_array])
    else:
        combined_conn = conn_array
    recreate_dataset(topo, "Arc Connectivity", combined_conn)

    # 3. Arc Internal Points and Count / Start attributes
    if internal_points_list:
        appended_pts = np.array(
            internal_points_list, dtype=old_internal_points.dtype
        ).reshape(-1, 2)
        if len(old_internal_points) > 0:
            combined_aip = np.vstack([old_internal_points, appended_pts])
        else:
            combined_aip = appended_pts
    else:
        combined_aip = old_internal_points

    combined_counts = np.concatenate([
        np.atleast_1d(old_count),
        np.array(new_counts, dtype=count_dtype),
    ])
    combined_starts = np.concatenate([
        np.atleast_1d(old_start),
        np.array(new_starts, dtype=start_dtype),
    ])

    new_aip = recreate_dataset(topo, "Arc Internal Points", combined_aip)
    if "Count" in new_aip.attrs:
        del new_aip.attrs["Count"]
    new_aip.attrs.create("Count", combined_counts, dtype=count_dtype)
    if "Start" in new_aip.attrs:
        del new_aip.attrs["Start"]
    new_aip.attrs.create("Start", combined_starts, dtype=start_dtype)

    # 4. Arc Attributes
    old_arc_attrs = topo["Arc Attributes"][()]
    row0 = old_arc_attrs[0]
    new_arc_attrs = np.empty(len(old_arc_attrs) + len(arcs), dtype=old_arc_attrs.dtype)
    new_arc_attrs[:len(old_arc_attrs)] = old_arc_attrs
    for idx, arc in enumerate(arcs):
        row = row0.copy()
        row["ConstantSize"] = np.nan if arc.cell_size is None else float(arc.cell_size)
        row["FollowExactly"] = 1 if arc.follow_exactly else 0
        new_arc_attrs[len(old_arc_attrs) + idx] = row
    recreate_dataset(topo, "Arc Attributes", new_arc_attrs)


def _append_regions(topo: Any, regions: Sequence[Region]) -> None:
    old_cp = topo["Control Points"][()]
    cp_coords = [[float(r.point.x), float(r.point.y)] for r in regions]
    cp_array = np.array(cp_coords, dtype=old_cp.dtype).reshape(-1, 2)
    if len(old_cp) > 0:
        combined_cp = np.vstack([old_cp, cp_array])
    else:
        combined_cp = cp_array
    recreate_dataset(topo, "Control Points", combined_cp)

    old_cpa = topo["Control Point Attributes"][()]
    cpa_row0 = old_cpa[0]
    new_cpa = np.empty(len(old_cpa) + len(regions), dtype=old_cpa.dtype)
    new_cpa[:len(old_cpa)] = old_cpa
    for idx, region in enumerate(regions):
        row = cpa_row0.copy()
        row["PatchType"] = int(region.patch)
        row["ConstantSize"] = float(region.cell_size)
        new_cpa[len(old_cpa) + idx] = row
    recreate_dataset(topo, "Control Point Attributes", new_cpa)


def _check_schema(topo: Any, has_arcs: bool, has_regions: bool) -> None:
    if has_arcs:
        required_arc_datasets = (
            "Nodes",
            "Arc Connectivity",
            "Arc Internal Points",
            "Arc Attributes",
        )
        for name in required_arc_datasets:
            if name not in topo:
                raise KeyError(name)
        aip = topo["Arc Internal Points"]
        if "Count" not in aip.attrs:
            raise KeyError("Arc Internal Points Count")
        if "Start" not in aip.attrs:
            raise KeyError("Arc Internal Points Start")
        if len(topo["Arc Attributes"]) == 0:
            raise KeyError("Arc Attributes")

    if has_regions:
        required_region_datasets = (
            "Control Points",
            "Control Point Attributes",
        )
        for name in required_region_datasets:
            if name not in topo:
                raise KeyError(name)
        if len(topo["Control Point Attributes"]) == 0:
            raise KeyError("Control Point Attributes")


def add_topology(
    geom: Path,
    arcs: Sequence[Arc],
    regions: Sequence[Region] = (),
    snap_tol: float = 1e-6,
) -> None:
    """Append arcs and regions to a geometry's /Geometry/Mesh Topology."""
    if snap_tol <= 0.0:
        raise ValueError(f"snap_tol must be positive, got {snap_tol}")

    for arc in arcs:
        _validate_arc(arc, snap_tol)
    for region in regions:
        _validate_region(region)

    with h5py.File(geom, "r+", locking=False) as f:
        if _TOPO not in f:
            raise KeyError(f"Group {_TOPO!r} not found in {geom}")
        topo = f[_TOPO]

        _check_schema(topo, has_arcs=bool(arcs), has_regions=bool(regions))

        if arcs:
            _append_arcs(topo, arcs, snap_tol)

        if regions:
            _append_regions(topo, regions)


def add_channel(
    geom: Path,
    patches: ChannelPatches,
    cell_size: float,
    snap_tol: float = 1e-6,
) -> None:
    """Neighbouring patches share cross-section end nodes (snapped), each region is
    bounded by four arcs as RAS requires for a quad patch.
    """
    arcs: list[Arc] = []
    for cs in patches.cross_sections:
        arcs.append(Arc(cs, cell_size=cell_size, follow_exactly=True))
    for left_piece in patches.left:
        arcs.append(Arc(left_piece, cell_size=cell_size, follow_exactly=True))
    for right_piece in patches.right:
        arcs.append(Arc(right_piece, cell_size=cell_size, follow_exactly=True))

    regions: list[Region] = []
    for patch in patches.patches:
        centroid = patch.centroid
        pt = (
            centroid
            if patch.contains(centroid)
            else patch.representative_point()
        )
        regions.append(Region(pt, PatchType.QUAD, cell_size))

    add_topology(geom, arcs, regions, snap_tol=snap_tol)

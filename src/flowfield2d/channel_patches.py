"""A channel meshed as a chain of patches (e.g. quad patches in RAS 2025), each bounded by four
arcs: a left-bank piece, a right-bank piece and the cross-sections at its two ends; neighbours share
a cross-section and its end nodes exactly, so a topology writer can snap them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from shapely.geometry import LineString, Polygon
from shapely.ops import substring


@dataclass(frozen=True)
class ChannelPatches:
    """A chain of channel patches bounded by bank lines and cross-sections."""

    cross_sections: list[LineString]
    left: list[LineString]
    right: list[LineString]
    patches: list[Polygon]


def smooth_line(line: LineString, iterations: int = 2) -> LineString:
    """Chaikin corner cutting keeping the original first and last coordinates."""
    if iterations < 0:
        raise ValueError(f"iterations must be non-negative, got {iterations}")
    if iterations == 0 or line.is_empty or len(line.coords) <= 2:
        return line

    coords: list[tuple[float, ...]] = [tuple(float(v) for v in c) for c in line.coords]
    for _ in range(iterations):
        if len(coords) < 2:
            break
        refined: list[tuple[float, ...]] = []
        for i in range(len(coords) - 1):
            p0 = np.asarray(coords[i], dtype=float)
            p1 = np.asarray(coords[i + 1], dtype=float)
            q = 0.75 * p0 + 0.25 * p1
            r = 0.25 * p0 + 0.75 * p1
            refined.append(tuple(float(v) for v in q))
            refined.append(tuple(float(v) for v in r))
        refined[0] = coords[0]
        refined[-1] = coords[-1]
        coords = refined

    return LineString(coords)


def channel_patches(
    left: LineString,
    right: LineString,
    centre: LineString,
    spacing: float,
) -> ChannelPatches:
    """Mesh a channel between left and right banks as a chain of quad patches."""
    if spacing <= 0:
        raise ValueError(f"spacing must be positive, got {spacing}")
    total_len = centre.length
    if total_len < spacing:
        raise ValueError(
            f"centreline length {total_len} is shorter than spacing {spacing} "
            "(fewer than one patch)"
        )

    stations = [0.0]
    k = 1
    while True:
        st = k * spacing
        if st > total_len and not np.isclose(st, total_len):
            break
        stations.append(st)
        if np.isclose(st, total_len):
            break
        k += 1

    remainder = total_len - stations[-1]
    if not np.isclose(remainder, 0.0):
        if remainder < spacing / 2.0:
            stations.pop()
        stations.append(total_len)
    else:
        stations[-1] = total_len

    cross_sections: list[LineString] = []
    left_dists: list[float] = []
    right_dists: list[float] = []

    for s in stations:
        p = centre.interpolate(s)
        ld = float(left.project(p))
        rd = float(right.project(p))
        left_dists.append(ld)
        right_dists.append(rd)

        l_pt = left.interpolate(ld)
        r_pt = right.interpolate(rd)
        l_end = (float(l_pt.x), float(l_pt.y))
        r_end = (float(r_pt.x), float(r_pt.y))
        cross_sections.append(LineString([l_end, r_end]))

    left_pieces: list[LineString] = []
    right_pieces: list[LineString] = []
    patches: list[Polygon] = []

    for i in range(len(cross_sections) - 1):
        cs_curr = cross_sections[i]
        cs_next = cross_sections[i + 1]

        raw_left = substring(left, left_dists[i], left_dists[i + 1])
        if isinstance(raw_left, LineString):
            l_coords: list[tuple[float, float]] = [
                (float(c[0]), float(c[1])) for c in raw_left.coords
            ]
        else:
            l_coords = []
        if len(l_coords) >= 2:
            l_coords[0] = (float(cs_curr.coords[0][0]), float(cs_curr.coords[0][1]))
            l_coords[-1] = (float(cs_next.coords[0][0]), float(cs_next.coords[0][1]))
        else:
            l_coords = [
                (float(cs_curr.coords[0][0]), float(cs_curr.coords[0][1])),
                (float(cs_next.coords[0][0]), float(cs_next.coords[0][1])),
            ]
        left_piece = LineString(l_coords)
        left_pieces.append(left_piece)

        raw_right = substring(right, right_dists[i], right_dists[i + 1])
        if isinstance(raw_right, LineString):
            r_coords: list[tuple[float, float]] = [
                (float(c[0]), float(c[1])) for c in raw_right.coords
            ]
        else:
            r_coords = []
        if len(r_coords) >= 2:
            r_coords[0] = (float(cs_curr.coords[-1][0]), float(cs_curr.coords[-1][1]))
            r_coords[-1] = (float(cs_next.coords[-1][0]), float(cs_next.coords[-1][1]))
        else:
            r_coords = [
                (float(cs_curr.coords[-1][0]), float(cs_curr.coords[-1][1])),
                (float(cs_next.coords[-1][0]), float(cs_next.coords[-1][1])),
            ]
        right_piece = LineString(r_coords)
        right_pieces.append(right_piece)

        ring_coords = (
            list(left_piece.coords)
            + list(cs_next.coords)[1:]
            + list(reversed(right_piece.coords))[1:]
            + list(reversed(cs_curr.coords))[1:]
        )
        deduped: list[tuple[float, float]] = []
        for pt in ring_coords:
            pt_xy = (float(pt[0]), float(pt[1]))
            if not deduped or pt_xy != deduped[-1]:
                deduped.append(pt_xy)
        if len(deduped) > 1 and deduped[0] != deduped[-1]:
            deduped.append(deduped[0])

        patch = Polygon(deduped)
        patches.append(patch)

    return ChannelPatches(
        cross_sections=cross_sections,
        left=left_pieces,
        right=right_pieces,
        patches=patches,
    )

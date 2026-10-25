"""Split a stream line at flow-change points; domain extents; BC line placement (REQUIREMENTS 4).

Chainage runs along the line from 0 at its upstream end. Each analysis segment between flow-change
points gets a model domain that adds an upstream lead-in of `n_widths` bankfull widths and a
downstream extension of max(L_min, k * D_bf / S), so BC effects stay outside the analysis reach.
Where the line ends first, the domain is clipped and flagged; QA reports clipped ends.
All lengths are in the line's linear units; defaults are generic (REQUIREMENTS 4).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import split


@dataclass(frozen=True)
class Domain:
    id: str
    start_m: float
    end_m: float
    analysis_start_m: float
    analysis_end_m: float
    upstream_clipped: bool
    downstream_clipped: bool


def upstream_lead_in(w_bf: float, n_widths: float = 5.0) -> float:
    return n_widths * w_bf


def downstream_extension(d_bf: float, slope: float, l_min: float = 1000.0, k: float = 2.0) -> float:
    if slope <= 0:
        raise ValueError("slope must be positive")
    return max(l_min, k * d_bf / slope)


def _per_segment(value: float | Sequence[float], n: int, name: str) -> list[float]:
    if isinstance(value, int | float):
        return [float(value)] * n
    vals = [float(v) for v in value]
    if len(vals) != n:
        raise ValueError(f"{name}: expected {n} values (one per segment), got {len(vals)}")
    return vals


def plan_domains(length_m: float, split_at_m: Sequence[float], *,
                 w_bf: float | Sequence[float], d_bf: float | Sequence[float],
                 slope: float | Sequence[float], n_widths: float = 5.0, l_min: float = 1000.0,
                 k: float = 2.0, id_prefix: str = "D") -> list[Domain]:
    """One domain per analysis segment between the split points (chainages, strictly increasing)."""
    splits = [float(s) for s in split_at_m]
    if any(not 0 < s < length_m for s in splits) or splits != sorted(set(splits)):
        raise ValueError("split points must be strictly increasing and inside (0, length)")
    edges = [0.0, *splits, float(length_m)]
    n = len(edges) - 1
    ws = _per_segment(w_bf, n, "w_bf")
    ds = _per_segment(d_bf, n, "d_bf")
    ss = _per_segment(slope, n, "slope")
    out = []
    for i in range(n):
        a0, a1 = edges[i], edges[i + 1]
        want_start = a0 - upstream_lead_in(ws[i], n_widths)
        want_end = a1 + downstream_extension(ds[i], ss[i], l_min, k)
        out.append(Domain(f"{id_prefix}{i + 1:02d}", max(0.0, want_start),
                          min(float(length_m), want_end), a0, a1,
                          want_start < 0.0, want_end > length_m))
    return out


def overlaps(domains: Sequence[Domain]) -> list[tuple[str, str, float]]:
    """Overlap length between consecutive domains (input order = downstream order)."""
    pairs = zip(domains, domains[1:], strict=False)
    return [(a.id, b.id, max(0.0, a.end_m - b.start_m)) for a, b in pairs]


def bc_line(line: LineString, chainage_m: float, half_width_m: float) -> LineString:
    """A straight line perpendicular to `line` at `chainage_m`, `half_width_m` to each side."""
    if not 0.0 <= chainage_m <= line.length:
        raise ValueError(f"chainage {chainage_m} outside the line (length {line.length})")
    eps = min(1e-6 * max(line.length, 1.0), line.length / 2)
    p0 = line.interpolate(max(0.0, chainage_m - eps))
    p1 = line.interpolate(min(line.length, chainage_m + eps))
    dx, dy = p1.x - p0.x, p1.y - p0.y
    norm = math.hypot(dx, dy)
    nx, ny = -dy / norm, dx / norm
    c = line.interpolate(chainage_m)
    return LineString([(c.x + nx * half_width_m, c.y + ny * half_width_m),
                       (c.x - nx * half_width_m, c.y - ny * half_width_m)])


def cut_line(
    area: Polygon,
    centerline: LineString,
    chainage_m: float,
    half_width_m: float,
) -> LineString:
    """Perpendicular cut line at chainage_m clipped to area (longest piece if multi-part)."""
    line = bc_line(centerline, chainage_m, half_width_m)
    inter = line.intersection(area)
    if isinstance(inter, LineString) and not inter.is_empty:
        return inter
    lines: list[LineString] = []
    if hasattr(inter, "geoms"):
        for g in inter.geoms:
            if isinstance(g, LineString) and not g.is_empty:
                lines.append(g)
    if lines:
        return max(lines, key=lambda g: g.length)
    raise ValueError(f"Cut line at chainage {chainage_m} did not intersect area")


def keep_polygon(
    area: Polygon,
    centerline: LineString,
    start_m: float,
    end_m: float,
    half_width_m: float,
) -> Polygon:
    """Subset area between start_m and end_m chainages along centerline."""
    if start_m >= end_m:
        raise ValueError(f"start_m ({start_m}) must be strictly less than end_m ({end_m})")

    minx, miny, maxx, maxy = area.bounds
    diag = math.hypot(maxx - minx, maxy - miny)
    hw = max(half_width_m, diag * 2.0)

    current_pieces: list[Polygon] = [area]
    cutters: list[LineString] = []
    if start_m > 0.0:
        cutters.append(bc_line(centerline, start_m, hw))
    if end_m < centerline.length:
        cutters.append(bc_line(centerline, end_m, hw))

    for cutter in cutters:
        next_pieces: list[Polygon] = []
        for poly in current_pieces:
            res = split(poly, cutter)
            geoms = getattr(res, "geoms", [res])
            for g in geoms:
                if isinstance(g, Polygon) and not g.is_empty:
                    next_pieces.append(g)
                elif isinstance(g, MultiPolygon):
                    for sub_p in g.geoms:
                        if isinstance(sub_p, Polygon) and not sub_p.is_empty:
                            next_pieces.append(sub_p)
        current_pieces = next_pieces

    # Assumes each extended cut crosses the area only near its own chainage (straight-ish reach at
    # the cut); on a tight meander a stray crossing can trim the kept piece.
    mid_pt = centerline.interpolate((start_m + end_m) / 2.0)
    for poly in current_pieces:
        if poly.covers(mid_pt):
            return poly
    raise ValueError(f"no piece of the area contains the centerline between {start_m} and {end_m}")

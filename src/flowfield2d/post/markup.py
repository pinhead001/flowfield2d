"""Markup drawn on a multi-panel review figure, read back into data coordinates.

A reviewer draws lines on the PDF of a figure (a PDF reader's Line or PolyLine annotation,
with a note). To put those lines on the map they were drawn over, the plot code records each
panel's position on the page and its data view (`PanelLayout`, saved beside the figure), and
`annotations_to_geo` maps every annotation vertex: PDF points -> figure fraction (PDF origin at
the top left, page = figure size x 72) -> the one panel whose box holds all the vertices -> that
panel's data coordinates. Annotations of other kinds are returned as skipped, never dropped
silently; a vertex set inside no panel or more than one raises `MarkupError`.

`layout_from_figure` is the only function that touches matplotlib (lazily), and
`annotations_to_geo` the only one that touches pymupdf (optional extra `markup`).
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

Box = tuple[float, float, float, float]


class MarkupError(ValueError):
    """An annotation that cannot be placed on one panel."""


@dataclass(frozen=True)
class Panel:
    box: Box      # figure fraction: x0, y0, width, height (origin bottom left)
    view: Box     # data limits: xmin, xmax, ymin, ymax

    def contains(self, fx: float, fy: float) -> bool:
        x0, y0, w, h = self.box
        return x0 <= fx <= x0 + w and y0 <= fy <= y0 + h

    def to_data(self, fx: float, fy: float) -> tuple[float, float]:
        (x0, y0, w, h), (vx0, vx1, vy0, vy1) = self.box, self.view
        return vx0 + (fx - x0) / w * (vx1 - vx0), vy0 + (fy - y0) / h * (vy1 - vy0)


@dataclass
class PanelLayout:
    """Page order and, per page, each panel's box and view (the sidecar of a multi-page figure)."""

    figsize_in: tuple[float, float]
    pages: list[str]
    axes: dict[str, list[Panel]] = field(default_factory=dict)

    def write(self, path: Path) -> None:
        data = {"figsize_in": list(self.figsize_in), "pages": list(self.pages),
                "axes": {p: [asdict(a) for a in panels] for p, panels in self.axes.items()}}
        Path(path).write_text(json.dumps(data, indent=1), encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> PanelLayout:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        axes = {p: [Panel(box=_box4(a["box"]), view=_box4(a["view"])) for a in panels]
                for p, panels in d["axes"].items()}
        return cls(figsize_in=(float(d["figsize_in"][0]), float(d["figsize_in"][1])),
                   pages=list(d["pages"]), axes=axes)


def layout_from_figure(layout: PanelLayout, fig: Any, axes: Sequence[Any], page: str) -> None:
    """Record the panels of `fig` for `page`: the boxes after `fig.canvas.draw()` (the aspect-
    adjusted positions, not the ones set before drawing) and the current view limits."""
    fig.canvas.draw()
    layout.axes[page] = [
        Panel(box=_box4(ax.get_position().bounds), view=_box4((*ax.get_xlim(), *ax.get_ylim())))
        for ax in axes]


def _box4(values: Sequence[Any]) -> Box:
    a, b, c, d = (float(v) for v in values)
    return a, b, c, d


@dataclass
class Markup:
    page: str
    panel: int
    kind: str
    content: str
    xy: list[tuple[float, float]]


def annotations_to_geo(pdf: Path, layout: PanelLayout,
                       kinds: Sequence[str] = ("Line", "PolyLine"),
                       ) -> tuple[list[Markup], list[tuple[str, str, str]]]:
    """The `kinds` annotations of `pdf` in the data coordinates of the panel each one lies on;
    page i of the PDF is `layout.pages[i]`. Returns (markups, skipped) where skipped lists the
    other annotations as (page, kind, content). Raises MarkupError when an annotation's
    vertices do not lie inside exactly one panel."""
    pymupdf: Any = importlib.import_module("pymupdf")      # optional extra `markup`

    w_pt, h_pt = (72.0 * s for s in layout.figsize_in)
    markups: list[Markup] = []
    skipped: list[tuple[str, str, str]] = []
    with pymupdf.open(str(pdf)) as doc:
        for i, page in enumerate(doc):
            _check_page(page, i, layout, w_pt, h_pt)
            name = layout.pages[i]
            _page_markups(page, name, layout.axes.get(name, []), kinds, w_pt, h_pt, markups,
                          skipped)
    return markups, skipped


def _check_page(page: Any, i: int, layout: PanelLayout, w_pt: float, h_pt: float) -> None:
    """The page must be the figure's page: `figsize x 72` points, unrotated. A figure saved
    with `bbox_inches="tight"`, or a cropped or rotated page, would shift every fraction."""
    if i >= len(layout.pages):
        raise MarkupError(f"PDF page {i + 1} has no entry in the layout's pages")
    r = page.rect
    if abs(r.width - w_pt) > 1.0 or abs(r.height - h_pt) > 1.0 or page.rotation:
        raise MarkupError(
            f"page {i + 1} ({layout.pages[i]}): page size {r.width:.1f} x {r.height:.1f} pt, "
            f"rotation {page.rotation}, is not the figure's {w_pt:.1f} x {h_pt:.1f} pt (save the "
            "figure without bbox_inches='tight' and do not crop or rotate pages)")


def _page_markups(page: Any, name: str, panels: Sequence[Panel], kinds: Sequence[str],
                  w_pt: float, h_pt: float, markups: list[Markup],
                  skipped: list[tuple[str, str, str]]) -> None:
    for a in page.annots():
        kind = a.type[1]
        content = str(a.info.get("content", ""))
        if kind not in kinds:
            skipped.append((name, kind, content))
            continue
        fxy = [(p[0] / w_pt, 1.0 - p[1] / h_pt) for p in a.vertices]
        hits = [k for k, panel in enumerate(panels)
                if all(panel.contains(fx, fy) for fx, fy in fxy)]
        if len(hits) != 1:
            where = "no panel" if not hits else f"panels {hits}"
            raise MarkupError(f"page {name}: {kind} annotation {content!r} lies in {where}")
        panel = panels[hits[0]]
        markups.append(Markup(name, hits[0], kind, content,
                              [panel.to_data(fx, fy) for fx, fy in fxy]))


def to_geojson(markups: Sequence[Markup]) -> dict[str, Any]:
    """A FeatureCollection of LineStrings (in the panels' data CRS) with properties page,
    panel, content and length."""
    feats = []
    for m in markups:
        length = sum(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
                     for (x0, y0), (x1, y1) in zip(m.xy, m.xy[1:], strict=False))
        feats.append({"type": "Feature",
                      "properties": {"page": m.page, "panel": m.panel, "content": m.content,
                                     "length": length},
                      "geometry": {"type": "LineString", "coordinates": [list(p) for p in m.xy]}})
    return {"type": "FeatureCollection", "features": feats}

"""PDF line annotations drawn on a multi-panel figure, read back into the panels' data
coordinates through the figure's panel layout (round trip through matplotlib + pymupdf)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flowfield2d.post.markup import (
    MarkupError,
    Panel,
    PanelLayout,
    annotations_to_geo,
    layout_from_figure,
    to_geojson,
)

pymupdf = pytest.importorskip("pymupdf")
matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

VIEWS = ((0.0, 1000.0, 0.0, 500.0), (2000.0, 3000.0, 2000.0, 2500.0))
FIGSIZE = (10.0, 5.0)


def _figure_pdf(tmp_path: Path) -> tuple[Path, PanelLayout]:
    """Two pages, two panels each, with known views; the layout as the plot code records it."""
    layout = PanelLayout(figsize_in=FIGSIZE, pages=["pageA", "pageB"], axes={})
    pdf = tmp_path / "fig.pdf"
    with PdfPages(pdf) as pp:
        for page in layout.pages:
            fig, axs = plt.subplots(1, 2, figsize=FIGSIZE)
            for ax, v in zip(axs, VIEWS, strict=True):
                ax.set_xlim(v[0], v[1])
                ax.set_ylim(v[2], v[3])
            layout_from_figure(layout, fig, list(axs), page)
            pp.savefig(fig)
            plt.close(fig)
    return pdf, layout


def _pdf_point(layout: PanelLayout, page: str, k: int, x: float, y: float) -> tuple[float, float]:
    panel = layout.axes[page][k]
    (x0, y0, w, h), (vx0, vx1, vy0, vy1) = panel.box, panel.view
    fx = x0 + (x - vx0) / (vx1 - vx0) * w
    fy = y0 + (y - vy0) / (vy1 - vy0) * h
    return fx * layout.figsize_in[0] * 72, (1 - fy) * layout.figsize_in[1] * 72


def _annotate(pdf: Path, layout: PanelLayout, extra_line: tuple | None = None) -> Path:
    doc = pymupdf.open(pdf)
    page = doc[0]
    a = page.add_line_annot(_pdf_point(layout, "pageA", 0, 250, 125),
                            _pdf_point(layout, "pageA", 0, 750, 375))
    a.set_info(content="new inflow line")
    a.update()
    b = page.add_polyline_annot([_pdf_point(layout, "pageA", 1, 2100, 2400),
                                 _pdf_point(layout, "pageA", 1, 2500, 2100),
                                 _pdf_point(layout, "pageA", 1, 2900, 2450)])
    b.set_info(content="reach")
    b.update()
    c = page.add_rect_annot(pymupdf.Rect(10, 10, 40, 40))
    c.set_info(content="box")
    c.update()
    if extra_line is not None:
        d = page.add_line_annot(*extra_line)
        d.set_info(content="stray")
        d.update()
    out = pdf.with_name("marked.pdf")
    doc.save(out)
    return out


def test_layout_round_trips_through_json(tmp_path: Path) -> None:
    _, layout = _figure_pdf(tmp_path)
    path = tmp_path / "axes.json"
    layout.write(path)
    back = PanelLayout.read(path)
    assert back == layout and back.pages == ["pageA", "pageB"]
    assert [p.view for p in back.axes["pageA"]] == [VIEWS[0], VIEWS[1]]
    assert all(0 <= p.box[0] < p.box[0] + p.box[2] <= 1 for p in back.axes["pageA"])
    assert json.loads(path.read_text())["figsize_in"] == [10.0, 5.0]


def test_annotations_map_back_to_data_coordinates(tmp_path: Path) -> None:
    pdf, layout = _figure_pdf(tmp_path)
    marked = _annotate(pdf, layout)
    markups, skipped = annotations_to_geo(marked, layout)
    assert [m.kind for m in markups] == ["Line", "PolyLine"]
    line = markups[0]
    assert line.page == "pageA" and line.panel == 0 and line.content == "new inflow line"
    assert line.xy[0] == pytest.approx((250, 125), abs=5)
    assert line.xy[1] == pytest.approx((750, 375), abs=5)
    poly = markups[1]
    assert poly.panel == 1 and len(poly.xy) == 3
    assert poly.xy[1] == pytest.approx((2500, 2100), abs=5)
    assert skipped == [("pageA", "Square", "box")]


def test_annotation_outside_every_panel_raises(tmp_path: Path) -> None:
    pdf, layout = _figure_pdf(tmp_path)
    w, h = FIGSIZE[0] * 72, FIGSIZE[1] * 72
    marked = _annotate(pdf, layout, extra_line=((0.4 * w, 0.05 * h), (0.6 * w, 0.05 * h)))
    with pytest.raises(MarkupError, match="pageA.*stray"):
        annotations_to_geo(marked, layout)


def test_to_geojson_features(tmp_path: Path) -> None:
    pdf, layout = _figure_pdf(tmp_path)
    markups, _ = annotations_to_geo(_annotate(pdf, layout), layout)
    fc = to_geojson(markups)
    assert fc["type"] == "FeatureCollection" and len(fc["features"]) == 2
    f0 = fc["features"][0]
    assert f0["geometry"]["type"] == "LineString" and len(f0["geometry"]["coordinates"]) == 2
    assert f0["properties"]["page"] == "pageA" and f0["properties"]["panel"] == 0
    assert f0["properties"]["content"] == "new inflow line"
    assert f0["properties"]["length"] == pytest.approx((500**2 + 250**2) ** 0.5, rel=0.01)


def test_panel_is_a_plain_record() -> None:
    p = Panel(box=(0.1, 0.1, 0.4, 0.8), view=(0.0, 1.0, 0.0, 1.0))
    assert p.box[2] == 0.4 and p.view[1] == 1.0

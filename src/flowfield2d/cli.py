"""`flowfield2d` command."""

from pathlib import Path
from typing import Literal

import typer

from flowfield2d import __version__

app = typer.Typer(no_args_is_help=True, add_completion=False)
WORKER_TIMEOUT_S = 72 * 3600.0
bc_app = typer.Typer(no_args_is_help=True, help="Edit RAS 2025 BC files (use on scratch copies).")
app.add_typer(bc_app, name="bc")
runs_app = typer.Typer(no_args_is_help=True, help="Background, resumable run scheduler.")
app.add_typer(runs_app, name="runs")
export_app = typer.Typer(no_args_is_help=True, help="Export a model to other tools' formats.")
app.add_typer(export_app, name="export")


@runs_app.command("submit")
def runs_submit(registry: Path, run_id: str, domain: str, scenario: str, plan: Path) -> None:
    """Queue a plan (already in its own cloned project) as a run."""
    from flowfield2d.runs import Registry

    Registry(registry).add(run_id, domain, scenario, str(plan))
    typer.echo(f"queued {run_id}")


@runs_app.command("tick")
def runs_tick(
    registry: Path,
    ras: list[str] = typer.Option(..., help="RAS command (repeat for multi-token commands)."),
    max_parallel: int = typer.Option(2, help="Concurrent runs (ADR-0001: start at 2)."),
    core_count: int = typer.Option(0, help="Cores per run (0 = plan value)."),
    processor: str = typer.Option("CPU", help="CPU or GPU (GPU: SWE explicit only)."),
) -> None:
    """Mark dead runs interrupted, then start runnable runs in detached workers."""
    from flowfield2d.runs import Registry
    from flowfield2d.scheduler import launch_worker, tick

    reg = Registry(registry)
    started = tick(reg, max_parallel,
                   lambda rec: launch_worker(reg, rec, ras, core_count or None, processor))
    typer.echo("started: " + (", ".join(started) if started else "none"))


@runs_app.command("status")
def runs_status(registry: Path) -> None:
    """One line per run."""
    from flowfield2d.runs import Registry

    for r in Registry(registry).all():
        typer.echo(f"{r.run_id}\t{r.state.value}\t{r.domain}\t{r.scenario}\tattempts={r.attempts}")


@runs_app.command("requeue")
def runs_requeue(registry: Path, run_id: str) -> None:
    """Put a FAILED or INTERRUPTED run back in the queue."""
    from flowfield2d.runs import Registry

    Registry(registry).requeue(run_id)
    typer.echo(f"requeued {run_id}")


@runs_app.command("worker", hidden=True)
def runs_worker(
    registry: Path = typer.Option(...),
    run_id: str = typer.Option(...),
    ras: list[str] = typer.Option(...),
    core_count: int = typer.Option(0),
    processor: str = typer.Option("CPU"),
) -> None:
    """Internal: run one registered plan (started by `tick`)."""
    from flowfield2d.engines.ras2025.cli import RasCli
    from flowfield2d.engines.ras2025.engine import RasEngine
    from flowfield2d.runs import Registry
    from flowfield2d.scheduler import run_worker

    # A production solve can take many hours; the timeout only guards against a hung solver.
    cli = RasCli(ras, timeout_s=WORKER_TIMEOUT_S)
    run_worker(Registry(registry), run_id, RasEngine(cli, core_count or None, processor))


@export_app.command("iric")
def export_iric(
    out: Path = typer.Option(..., help="Output folder."),
    terrain: Path = typer.Option(..., help="Terrain raster."),
    centerline: Path = typer.Option(..., help="Line along the flow, upstream to downstream: a "
                                              "WKT text file, or a GeoPackage with --layer."),
    width: float = typer.Option(..., help="Grid width across the line (terrain CRS units)."),
    ni: int = typer.Option(..., help="Sections along the line."),
    nj: int = typer.Option(..., help="Nodes across each section."),
    xy_unit: str = typer.Option(..., help="Horizontal unit of the terrain CRS (e.g. metre, "
                                          "foot, US survey foot)."),
    z_unit: str = typer.Option(..., help="Unit of the terrain values."),
    layer: str = typer.Option("", help="GeoPackage layer holding the centerline."),
    roughness: Path | None = typer.Option(None, help="Manning's n raster."),
    manning_n: float | None = typer.Option(None, help="One Manning's n for the whole grid."),
    results: Path | None = typer.Option(None, help="RAS 2025 result file for the flow state."),
    area: str = typer.Option("", help="2D area name (default: the only one)."),
    time_index: int = typer.Option(-1, help="Output index (negative counts from the end)."),
    model_unit: str = typer.Option("", help="Length unit of the RAS results."),
    inflow_line: list[str] = typer.Option([], help="BC line whose flow counts as inflow "
                                                   "(repeat)."),
    discharge: float | None = typer.Option(None, help="Discharge in m3/s (instead of "
                                                      "--inflow-line)."),
    tol: float = typer.Option(0.0, help="BC line to face matching distance (model units)."),
    solver: str = typer.Option("fastmech", help="fastmech or nays2dh."),
    drag_depth: str = typer.Option("", help="FaSTMECH only: depth in m for Cd = g n^2/h^(1/3), "
                                            "or 'local' for the model depth at each node."),
    tpo_stride: int = typer.Option(0, help="Also write every Nth terrain cell as a .tpo cloud."),
    margin: float = typer.Option(0.0, help="Raster clip margin around the grid (CRS units)."),
    template: Path | None = typer.Option(None, help="iRIC project (.ipro) saved by iRIC for the "
                                                    "solver; writes project.ipro from it."),
    definition: Path | None = typer.Option(None, help="The solver's definition.xml (fills "
                                                      "grid attributes left at defaults)."),
) -> None:
    """Write an iRIC grid, geographic data and flow summary (and, with --template, a project)."""
    from shapely import wkt
    from shapely.geometry import LineString

    from flowfield2d.curvigrid import build_grid
    from flowfield2d.export import iric
    from flowfield2d.units import length_unit_m

    try:
        if centerline.suffix.lower() == ".gpkg":
            from flowfield2d.post.gpkg import read_gpkg_layer

            if not layer:
                raise ValueError("--layer is required with a GeoPackage centerline")
            geoms = read_gpkg_layer(centerline, layer)[0]
            lines = [g for g in geoms if isinstance(g, LineString)]
            if len(lines) != 1:
                raise ValueError(f"layer {layer!r} must hold one LineString (has {len(lines)})")
            line = lines[0]
        else:
            geom = wkt.loads(centerline.read_text(encoding="utf-8"))
            if not isinstance(geom, LineString):
                raise ValueError(f"{centerline}: expected a LINESTRING")
            line = geom
        if roughness is not None and manning_n is not None:
            raise ValueError("give --roughness or --manning-n, not both")
        k_xy, k_z = length_unit_m(xy_unit), length_unit_m(z_unit)
        flow = None
        extra: dict[str, object] = {"terrain": terrain.name}
        if results is not None:
            from flowfield2d.engines.ras2025.export import flow_state
            from flowfield2d.engines.ras2025.results import ResultsReader

            reader = ResultsReader(results)
            areas = reader.areas()
            if not area and len(areas) != 1:
                raise ValueError(f"--area is required (areas: {', '.join(areas)})")
            if not model_unit:
                raise ValueError("--model-unit is required with --results")
            flow = flow_state(reader, area or areas[0], time_index, length_unit_m(model_unit),
                              inflow_lines=inflow_line, tol=tol, discharge=discharge)
            extra.update({"results": results.name, "area": area or areas[0],
                          "time_index": time_index, "inflow_lines": list(inflow_line)})
        depth: float | Literal["local"] | None = None
        if drag_depth:
            depth = "local" if drag_depth == "local" else float(drag_depth)
        grid = build_grid(line, width, ni, nj)
        rough: Path | float | None = roughness if roughness is not None else manning_n
        pkg = iric.prepare(grid, terrain, xy_unit_m=k_xy, z_unit_m=k_z, roughness=rough,
                           flow=flow)
        paths = iric.write_package(pkg, out, solver=solver, drag_depth=depth,
                                   terrain=terrain, z_unit_m=k_z, roughness=roughness, flow=flow,
                                   tpo_stride=tpo_stride, margin=margin, extra=extra)
        if template is not None:
            from flowfield2d.export.iric_project import fastmech_conditions, write_project

            node, cell = iric.grid_attributes(pkg, solver, drag_depth=depth)
            conditions = (fastmech_conditions(pkg, roughness_by_node="roughness" in node)
                          if solver == "fastmech" and flow is not None else None)
            paths["project"] = write_project(template, out / "project.ipro", pkg.xy, node, cell,
                                             conditions, definition=definition)
    except (ValueError, KeyError, IndexError) as e:
        raise typer.BadParameter(str(e)) from e
    for name, p in paths.items():
        typer.echo(f"{name}\t{p}")


@app.command()
def version() -> None:
    """Print the flowfield2d version."""
    typer.echo(__version__)


@bc_app.command("show")
def bc_show(path: Path) -> None:
    """List the BC payload rows."""
    from flowfield2d.engines.ras2025.bc import payloads

    for p in payloads(path):
        typer.echo(f"{p.index}\t{p.variable}\t{p.mode}\tenabled={p.enabled}\tconstant={p.constant}")


@bc_app.command("scale-flow")
def bc_scale_flow(path: Path, factor: float) -> None:
    """Multiply the single flow time series by FACTOR."""
    from flowfield2d.engines.ras2025.bc import scale_flow_series

    try:
        scale_flow_series(path, factor)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e


@bc_app.command("set-slope")
def bc_set_slope(
    path: Path,
    slope: float,
    allow_invalid: bool = typer.Option(False, help="Permit 0 (probe E6b only)."),
) -> None:
    """Set the single normal-depth BC's friction slope."""
    from flowfield2d.engines.ras2025.bc import set_normal_depth_slope

    try:
        set_normal_depth_slope(path, slope, allow_invalid=allow_invalid)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e


if __name__ == "__main__":
    app()

"""`flowfield2d` command."""

from pathlib import Path

import typer

from flowfield2d import __version__

app = typer.Typer(no_args_is_help=True, add_completion=False)
WORKER_TIMEOUT_S = 72 * 3600.0
bc_app = typer.Typer(no_args_is_help=True, help="Edit RAS 2025 BC files (use on scratch copies).")
app.add_typer(bc_app, name="bc")
runs_app = typer.Typer(no_args_is_help=True, help="Background, resumable run scheduler.")
app.add_typer(runs_app, name="runs")


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
) -> None:
    """Mark dead runs interrupted, then start runnable runs in detached workers."""
    from flowfield2d.runs import Registry
    from flowfield2d.scheduler import launch_worker, tick

    reg = Registry(registry)
    started = tick(reg, max_parallel,
                   lambda rec: launch_worker(reg, rec, ras, core_count or None))
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
) -> None:
    """Internal: run one registered plan (started by `tick`)."""
    from flowfield2d.engines.ras2025.cli import RasCli
    from flowfield2d.engines.ras2025.engine import RasEngine
    from flowfield2d.runs import Registry
    from flowfield2d.scheduler import run_worker

    # A production solve can take many hours; the timeout only guards against a hung solver.
    cli = RasCli(ras, timeout_s=WORKER_TIMEOUT_S)
    run_worker(Registry(registry), run_id, RasEngine(cli, core_count or None))


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

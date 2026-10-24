"""`flowfield2d` command."""

from pathlib import Path

import typer

from flowfield2d import __version__

app = typer.Typer(no_args_is_help=True, add_completion=False)
bc_app = typer.Typer(no_args_is_help=True, help="Edit RAS 2025 BC files (use on scratch copies).")
app.add_typer(bc_app, name="bc")


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

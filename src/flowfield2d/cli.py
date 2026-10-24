"""`flowfield2d` command."""

import typer

from flowfield2d import __version__

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def version() -> None:
    """Print the flowfield2d version."""
    typer.echo(__version__)

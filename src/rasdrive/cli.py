"""`rasdrive` command."""

import typer

from rasdrive import __version__

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def version() -> None:
    """Print the rasdrive version."""
    typer.echo(__version__)

"""Typer application entrypoint."""

from __future__ import annotations

import typer

from fabric_tools import __version__

app = typer.Typer(
    name="fabric-tools",
    help="CLI for working with Microsoft Fabric artifacts.",
    no_args_is_help=True,
)

notebook_app = typer.Typer(
    name="notebook",
    help="Download and upload Fabric notebooks.",
    no_args_is_help=True,
)
app.add_typer(notebook_app, name="notebook")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"fabric-tools {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """fabric-tools — Microsoft Fabric CLI."""


@notebook_app.command("download")
def notebook_download() -> None:
    """Download notebook(s) from Fabric to local files (coming soon)."""
    typer.echo("notebook download is not implemented yet.")
    raise typer.Exit(code=1)


@notebook_app.command("upload")
def notebook_upload() -> None:
    """Upload notebook(s) from local files to Fabric (coming soon)."""
    typer.echo("notebook upload is not implemented yet.")
    raise typer.Exit(code=1)

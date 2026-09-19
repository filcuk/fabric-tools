"""Typer commands: manifest."""

from __future__ import annotations

from pathlib import Path

import typer

from fabric_tools.cli.options import FILTER_HELP, HELP_CONTEXT, silent_opt
from fabric_tools.colours import FG_OK, print_warn_panel
from fabric_tools.exit_codes import EXIT_OK
from fabric_tools.manifest import (
    ManifestError,
    delete_manifest_file,
    format_inspect,
    format_inspect_line,
    list_manifest_paths,
    load_manifest,
    move_manifest_file,
    resolve_inspect_target,
    resolve_manifest_path,
)
from fabric_tools.sync.common import _exit_error, _exit_warn

manifest_app = typer.Typer(
    name="manifest",
    help="Manage deployment manifests (.ftdep).",
    no_args_is_help=True,
    context_settings=HELP_CONTEXT,
)


def _inspect_manifest_dir(directory: Path | None) -> None:
    """Print one-line summaries for each ``.ftdep`` in *directory* (default: cwd)."""
    try:
        paths = list_manifest_paths(directory)
    except ManifestError as exc:
        _exit_error(str(exc))

    if not paths:
        if directory is None:
            typer.echo("No .ftdep manifests in the current folder.")
        else:
            typer.echo(f"No .ftdep manifests in {directory}.")
        return

    for path in paths:
        try:
            loaded = load_manifest(path)
        except ManifestError as exc:
            print_warn_panel(f"{path.name}  error: {exc}")
            continue
        typer.echo(format_inspect_line(loaded, path=path))


@manifest_app.command(
    "inspect",
    short_help="[-m <PATH>]  Summaries for a folder, or dump one manifest.",
)
def manifest_inspect(
    manifest: str | None = typer.Option(
        None,
        "--manifest",
        "-m",
        help=(
            "Manifest stem/path (.ftdep), or a folder of manifests. "
            "Omit to inspect the current folder."
        ),
    ),
) -> None:
    """Show one-line summaries for a folder, or the full contents of one manifest."""
    if not manifest:
        _inspect_manifest_dir(None)
        raise typer.Exit(code=EXIT_OK)

    try:
        target = resolve_inspect_target(manifest)
    except ManifestError as exc:
        _exit_error(str(exc))

    if target.is_dir():
        _inspect_manifest_dir(target)
        raise typer.Exit(code=EXIT_OK)

    try:
        loaded = load_manifest(target)
    except ManifestError as exc:
        _exit_error(str(exc))
    typer.echo(format_inspect(loaded, path=target))
    raise typer.Exit(code=EXIT_OK)


@manifest_app.command("list")
def manifest_list() -> None:
    """List .ftdep filenames in the current folder."""
    try:
        paths = list_manifest_paths()
    except ManifestError as exc:
        _exit_error(str(exc))

    if not paths:
        typer.echo("No .ftdep manifests in the current folder.")
        raise typer.Exit(code=EXIT_OK)

    for path in paths:
        typer.echo(path.name)
    raise typer.Exit(code=EXIT_OK)


@manifest_app.command(
    "delete",
    short_help="-m <manifest>  Delete a local .ftdep file.",
)
def manifest_delete(
    manifest: str = typer.Option(
        ...,
        "--manifest",
        "-m",
        help="Deployment manifest stem or path (.ftdep) to delete locally.",
    ),
    name_filter: str | None = typer.Option(
        None,
        "--filter",
        "-f",
        help=FILTER_HELP,
    ),
    silent: bool = silent_opt(),
) -> None:
    """Delete a local deployment manifest file (not a Fabric item)."""
    from fabric_tools.confirm import ConfirmationAborted, confirm_or_abort

    try:
        path = resolve_manifest_path(manifest)
        if not path.is_file():
            raise ManifestError(f"manifest not found: {path}")
        confirm_or_abort(
            f"Delete local manifest file {path}?",
            silent=silent,
        )
        delete_manifest_file(path)
    except ConfirmationAborted as exc:
        _exit_warn(str(exc))
    except ManifestError as exc:
        _exit_error(str(exc))

    typer.secho(f"Deleted local manifest file {path}", fg=FG_OK)
    raise typer.Exit(code=EXIT_OK)


@manifest_app.command(
    "move",
    short_help="-m <manifest> <DEST>  Move or rename a local .ftdep file.",
)
def manifest_move(
    destination: str = typer.Argument(
        help="Destination stem or path (.ftdep). Parent folders are created.",
    ),
    manifest: str = typer.Option(
        ...,
        "--manifest",
        "-m",
        help="Deployment manifest stem or path (.ftdep) to move.",
    ),
    silent: bool = silent_opt(),
) -> None:
    """Move or rename a local deployment manifest file."""
    from fabric_tools.confirm import ConfirmationAborted, confirm_or_abort

    try:
        source = resolve_manifest_path(manifest)
        dest = resolve_manifest_path(destination)
        if not source.is_file():
            raise ManifestError(f"manifest not found: {source}")
        overwrite = dest.is_file()
        if overwrite:
            message = (
                f"Move local manifest file {source} to {dest} "
                f"(overwrite existing {dest})?"
            )
        else:
            message = f"Move local manifest file {source} to {dest}?"
        confirm_or_abort(message, silent=silent)
        move_manifest_file(source, dest)
    except ConfirmationAborted as exc:
        _exit_warn(str(exc))
    except ManifestError as exc:
        _exit_error(str(exc))

    typer.secho(
        f"Moved local manifest file {source} to {dest}",
        fg=FG_OK,
    )
    raise typer.Exit(code=EXIT_OK)

"""Typer application entrypoint."""

from __future__ import annotations

from typing import Optional

import typer

from fabric_tools import __version__
from fabric_tools.client import FabricClient
from fabric_tools.confirm import (
    ConfirmationAborted,
    confirm_download_overwrites,
    confirm_upload_actions,
)
from fabric_tools.exit_codes import EXIT_API, EXIT_OK, EXIT_USER
from fabric_tools.notebook.definition import display_name_from_path
from fabric_tools.notebook.ops import OpResult, run_download_batch, run_upload_batch
from fabric_tools.parsing import (
    CommandMode,
    ParseError,
    build_work_items,
    parse_file_values,
    parse_target_values,
)
from fabric_tools.validate import run_dry_run

app = typer.Typer(
    name="fabric-tools",
    help="CLI for working with Microsoft Fabric artifacts.",
    no_args_is_help=True,
)

notebook_app = typer.Typer(
    name="notebook",
    help="Download, upload, and compare Fabric notebooks.",
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
def notebook_download(
    target: Optional[list[str]] = typer.Option(
        None,
        "--target",
        "-t",
        help="workspace:artifact GUID pair. Repeatable or comma-separated. One workspace only.",
    ),
    file: Optional[list[str]] = typer.Option(
        None,
        "--file",
        "-f",
        help="Local .ipynb file or *.Notebook folder. Repeatable or comma-separated.",
    ),
    silent: bool = typer.Option(
        False,
        "--silent",
        help="Skip confirmation prompts.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate targets and/or files only; do not download.",
    ),
) -> None:
    """Download notebook(s) from Fabric to local files."""
    _run_notebook_command(
        CommandMode.DOWNLOAD,
        target_values=target,
        file_values=file,
        silent=silent,
        dry_run=dry_run,
    )


@notebook_app.command("upload")
def notebook_upload(
    target: Optional[list[str]] = typer.Option(
        None,
        "--target",
        "-t",
        help="workspace GUID (create) or workspace:artifact (overwrite). Repeatable or comma-separated.",
    ),
    file: Optional[list[str]] = typer.Option(
        None,
        "--file",
        "-f",
        help="Local .ipynb file or *.Notebook folder. Repeatable or comma-separated.",
    ),
    name: Optional[list[str]] = typer.Option(
        None,
        "--name",
        "-n",
        help="Display name for create uploads. Defaults to file/folder stem.",
    ),
    silent: bool = typer.Option(
        False,
        "--silent",
        help="Skip confirmation prompts.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate targets and/or files only; do not upload.",
    ),
) -> None:
    """Upload notebook(s) from local files to Fabric."""
    _run_notebook_command(
        CommandMode.UPLOAD,
        target_values=target,
        file_values=file,
        silent=silent,
        dry_run=dry_run,
        names=name,
    )


@notebook_app.command("compare")
def notebook_compare(
    target: Optional[list[str]] = typer.Option(
        None,
        "--target",
        "-t",
        help="workspace:artifact GUID pair. Repeatable or comma-separated. One workspace only.",
    ),
    file: Optional[list[str]] = typer.Option(
        None,
        "--file",
        "-f",
        help="Local .ipynb file or *.Notebook folder. Must 1:1 match targets.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate targets and/or files only; do not compare.",
    ),
) -> None:
    """Compare remote notebook(s) to local files."""
    _run_notebook_command(
        CommandMode.COMPARE,
        target_values=target,
        file_values=file,
        silent=True,
        dry_run=dry_run,
    )


def _run_notebook_command(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    file_values: list[str] | None,
    silent: bool,
    dry_run: bool,
    names: list[str] | None = None,
) -> None:
    try:
        targets = parse_target_values(target_values)
        files = parse_file_values(file_values)
        items = build_work_items(mode, targets, files, dry_run=dry_run)
    except ParseError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=EXIT_USER) from exc

    has_targets = bool(targets)
    has_files = bool(files)

    if dry_run:
        client: FabricClient | None = None
        try:
            if has_targets:
                client = FabricClient()
            results = run_dry_run(
                mode,
                items,
                client=client,
                has_targets=has_targets,
                has_files=has_files,
            )
        except Exception as exc:  # noqa: BLE001 - surface auth/client failures cleanly
            typer.secho(f"dry-run failed: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=EXIT_API) from exc
        finally:
            if client is not None:
                client.close()

        failed = False
        for result in results:
            color = typer.colors.GREEN if result.ok else typer.colors.RED
            typer.secho(result.message, fg=color)
            if not result.ok:
                failed = True
        raise typer.Exit(code=EXIT_USER if failed else EXIT_OK)

    try:
        display_names = (
            _resolve_upload_names(items, names) if mode is CommandMode.UPLOAD else None
        )
    except ParseError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=EXIT_USER) from exc

    client = FabricClient()
    try:
        if mode is CommandMode.DOWNLOAD:
            confirm_download_overwrites(client, items, silent=silent)
            op_results = run_download_batch(client, items)
            _print_op_results(op_results)
            _exit_from_op_results(op_results)
        elif mode is CommandMode.UPLOAD:
            confirm_upload_actions(
                client,
                items,
                silent=silent,
                display_names=display_names,
            )
            op_results = run_upload_batch(
                client,
                items,
                display_names=display_names,
            )
            _print_op_results(op_results)
            for result in op_results:
                if result.ok and result.workspace_id and result.item_id:
                    # Always echo created/updated GUID pairs for traceability.
                    if "created" in result.message:
                        typer.secho(
                            f"GUID: {result.workspace_id}:{result.item_id}",
                            fg=typer.colors.CYAN,
                        )
            _exit_from_op_results(op_results)
        else:
            typer.echo(
                f"notebook {mode.value}: parsed {len(items)} work item(s); "
                "compare action not implemented yet."
            )
            raise typer.Exit(code=EXIT_USER)
    except ConfirmationAborted as exc:
        typer.secho(str(exc), fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=EXIT_USER) from exc
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=EXIT_API) from exc
    finally:
        client.close()


def _print_op_results(results: list[OpResult]) -> None:
    for result in results:
        color = typer.colors.GREEN if result.ok else typer.colors.RED
        typer.secho(result.message, fg=color, err=not result.ok)


def _exit_from_op_results(results: list[OpResult]) -> None:
    if all(result.ok for result in results):
        raise typer.Exit(code=EXIT_OK)
    raise typer.Exit(code=EXIT_API)


def _resolve_upload_names(
    items: list,
    names: list[str] | None,
) -> list[str]:
    if names and len(names) not in {1, len(items)}:
        raise ParseError(
            f"--name count must be 1 or match target count ({len(items)}); got {len(names)}"
        )
    resolved: list[str] = []
    for index, item in enumerate(items):
        if names:
            resolved.append(names[0] if len(names) == 1 else names[index])
        elif item.file is not None:
            resolved.append(display_name_from_path(item.file))
        else:
            resolved.append("Notebook")
    return resolved

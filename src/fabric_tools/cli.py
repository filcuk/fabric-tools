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
from fabric_tools.notebook.compare import CompareResult, run_compare_batch
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
    invoke_without_command=True,
)

notebook_app = typer.Typer(
    name="notebook",
    help="Download, upload, and compare Fabric notebooks.",
    no_args_is_help=True,
)
app.add_typer(notebook_app, name="notebook")

path_app = typer.Typer(
    name="path",
    help="Register fabric-tools on your user PATH so you can run it as 'fabric-tools'.",
    no_args_is_help=True,
)
app.add_typer(path_app, name="path")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"fabric-tools {__version__}")
        raise typer.Exit()


def _interactive_callback(value: bool) -> bool:
    return value


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        "-i",
        "--i",
        help="Guided prompts to build and run a request.",
        callback=_interactive_callback,
    ),
) -> None:
    """fabric-tools — Microsoft Fabric CLI.

    Run without arguments to list commands. Use ``--help`` on any command
    for parameters (required vs optional).
    """
    if interactive:
        if ctx.invoked_subcommand is not None:
            typer.secho(
                "Do not combine --interactive with a subcommand. "
                "Use: fabric-tools --interactive",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=EXIT_USER)
        from fabric_tools.interactive import run_interactive_wizard

        run_interactive_wizard()
        return

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


@path_app.command("install")
def path_install() -> None:
    """Install fabric-tools into a stable folder and add it to your user PATH."""
    from fabric_tools.path_setup import PathSetupError, install_to_user_path

    try:
        result = install_to_user_path()
    except PathSetupError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=EXIT_USER) from exc

    typer.secho(f"Installed launcher: {result['launcher']}", fg=typer.colors.GREEN)
    typer.echo(f"Bin directory: {result['bin_dir']}")
    if result["path_added"]:
        typer.secho("Added bin directory to your user PATH.", fg=typer.colors.GREEN)
    elif result["already_on_path"]:
        typer.echo("Bin directory was already on your user PATH.")
    typer.echo(
        "Open a new terminal, then run: fabric-tools --help"
    )
    raise typer.Exit(code=EXIT_OK)


@path_app.command("uninstall")
def path_uninstall(
    keep_files: bool = typer.Option(
        False,
        "--keep-files",
        help="(optional) Leave installed files in place; only remove PATH entry.",
    ),
) -> None:
    """Remove fabric-tools PATH registration (and installed files by default)."""
    from fabric_tools.path_setup import PathSetupError, uninstall_from_user_path

    try:
        result = uninstall_from_user_path(delete_files=not keep_files)
    except PathSetupError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=EXIT_USER) from exc

    if result["removed_from_path"]:
        typer.secho("Removed bin directory from your user PATH.", fg=typer.colors.GREEN)
    else:
        typer.echo("Bin directory was not present on your user PATH.")
    if result["deleted_files"]:
        typer.echo(f"Deleted: {result['deleted_files']}")
    typer.echo("Open a new terminal for PATH changes to take effect.")
    raise typer.Exit(code=EXIT_OK)


@path_app.command("status")
def path_status_cmd() -> None:
    """Show whether fabric-tools is registered on PATH."""
    from fabric_tools.path_setup import PathSetupError, path_status

    try:
        status = path_status()
    except PathSetupError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=EXIT_USER) from exc

    typer.echo(f"Bin directory: {status['bin_dir']}")
    typer.echo(f"Exe present:   {status['exe_present']}")
    typer.echo(f"Cmd present:   {status['cmd_present']}")
    typer.echo(f"On user PATH:  {status['bin_dir_on_user_path']}")
    typer.echo(f"Running frozen exe: {status['frozen']}")
    which = status["which_fabric_tools"]
    typer.echo(f"shutil.which('fabric-tools'): {which or '(not found in this process PATH)'}")
    raise typer.Exit(code=EXIT_OK)


@notebook_app.command("download")
def notebook_download(
    target: Optional[list[str]] = typer.Option(
        None,
        "--target",
        "-t",
        "--t",
        help="(required unless --dry-run files-only) workspace:artifact GUID. "
        "Repeatable or comma-separated. One workspace only.",
    ),
    file: Optional[list[str]] = typer.Option(
        None,
        "--file",
        "-f",
        "--f",
        help="(required unless --dry-run targets-only) Local .ipynb or *.Notebook folder. "
        "Repeatable or comma-separated. One file may broadcast to all targets.",
    ),
    silent: bool = typer.Option(
        False,
        "--silent",
        "-s",
        "--s",
        help="(optional) Skip confirmation prompts.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "--dr",
        help="(optional) Validate targets and/or files only; do not download.",
    ),
) -> None:
    """Download notebook(s) from Fabric to local files."""
    run_notebook_command(
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
        "--t",
        help="(required unless --dry-run files-only) workspace GUID (create) or "
        "workspace:artifact (overwrite). Repeatable or comma-separated.",
    ),
    file: Optional[list[str]] = typer.Option(
        None,
        "--file",
        "-f",
        "--f",
        help="(required unless --dry-run targets-only) Local .ipynb or *.Notebook folder. "
        "Repeatable or comma-separated. One file may broadcast to all targets.",
    ),
    name: Optional[list[str]] = typer.Option(
        None,
        "--name",
        "-n",
        help="(optional, create only) Display name. Defaults to file/folder stem.",
    ),
    silent: bool = typer.Option(
        False,
        "--silent",
        "-s",
        "--s",
        help="(optional) Skip confirmation prompts.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "--dr",
        help="(optional) Validate targets and/or files only; do not upload.",
    ),
) -> None:
    """Upload notebook(s) from local files to Fabric (create or overwrite)."""
    run_notebook_command(
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
        "--t",
        help="(required unless --dry-run files-only) workspace:artifact GUID. "
        "Repeatable or comma-separated. One workspace only. Must 1:1 match --file.",
    ),
    file: Optional[list[str]] = typer.Option(
        None,
        "--file",
        "-f",
        "--f",
        help="(required unless --dry-run targets-only) Local .ipynb or *.Notebook folder. "
        "Must 1:1 match --target (no broadcast).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "--dr",
        help="(optional) Validate targets and/or files only; do not compare.",
    ),
    ignore_outputs: bool = typer.Option(
        True,
        "--ignore-outputs/--include-outputs",
        help="(optional) For .ipynb diffs, ignore cell outputs (default: ignore).",
    ),
) -> None:
    """Compare remote notebook(s) to local files (nbdime for .ipynb)."""
    run_notebook_command(
        CommandMode.COMPARE,
        target_values=target,
        file_values=file,
        silent=True,
        dry_run=dry_run,
        ignore_outputs=ignore_outputs,
    )


def run_notebook_command(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    file_values: list[str] | None,
    silent: bool,
    dry_run: bool,
    names: list[str | None] | list[str] | None = None,
    ignore_outputs: bool = True,
) -> None:
    """Shared entry used by CLI commands and the interactive wizard."""
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
                    if "created" in result.message:
                        typer.secho(
                            f"GUID: {result.workspace_id}:{result.item_id}",
                            fg=typer.colors.CYAN,
                        )
            _exit_from_op_results(op_results)
        elif mode is CommandMode.COMPARE:
            compare_results = run_compare_batch(
                client,
                items,
                ignore_outputs=ignore_outputs,
            )
            _print_compare_results(compare_results)
            _exit_from_compare_results(compare_results)
        else:
            typer.secho(f"Unknown mode: {mode}", fg=typer.colors.RED, err=True)
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


def _print_compare_results(results: list[CompareResult]) -> None:
    for result in results:
        typer.secho(result.header, fg=typer.colors.CYAN, bold=True)
        if result.error:
            typer.secho(result.error, fg=typer.colors.RED, err=True)
            continue
        if result.identical:
            typer.secho("identical", fg=typer.colors.GREEN)
        else:
            typer.secho("differences found", fg=typer.colors.YELLOW)
            if result.diff_text:
                typer.echo(result.diff_text.rstrip())
        typer.echo("")


def _exit_from_compare_results(results: list[CompareResult]) -> None:
    if any(not result.ok for result in results):
        raise typer.Exit(code=EXIT_API)
    if any(not result.identical for result in results):
        raise typer.Exit(code=EXIT_USER)
    raise typer.Exit(code=EXIT_OK)


def _resolve_upload_names(
    items: list,
    names: list[str | None] | list[str] | None,
) -> list[str]:
    if names and len(names) not in {1, len(items)}:
        raise ParseError(
            f"--name count must be 1 or match target count ({len(items)}); got {len(names)}"
        )
    resolved: list[str] = []
    for index, item in enumerate(items):
        chosen: str | None = None
        if names:
            chosen = names[0] if len(names) == 1 else names[index]
        if chosen:
            resolved.append(chosen)
        elif item.file is not None:
            resolved.append(display_name_from_path(item.file))
        else:
            resolved.append("Notebook")
    return resolved

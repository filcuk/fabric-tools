"""Typer application entrypoint."""

from __future__ import annotations

from typing import Callable, Optional

import typer
from typer.core import TyperGroup

from fabric_tools import __version__
from fabric_tools.client import FabricClient
from fabric_tools.confirm import (
    ConfirmationAborted,
    confirm_download_overwrites,
    confirm_upload_actions,
)
from fabric_tools.exit_codes import EXIT_API, EXIT_OK, EXIT_USER
from fabric_tools.manifest import (
    ManifestError,
    format_inspect,
    item_id_overrides_from_results,
    load_manifest,
    manifest_from_work_items,
    resolve_manifest_path,
    save_manifest,
    work_items_from_manifest,
)
from fabric_tools.notebook.compare import CompareResult, run_compare_batch
from fabric_tools.notebook.cells import (
    CellSelectionError,
    parse_cell_indices,
    validate_cells_usage,
)
from fabric_tools.notebook.definition import display_name_from_path
from fabric_tools.notebook.ops import OpResult, run_download_batch, run_upload_batch
from fabric_tools.parsing import (
    CommandMode,
    ParseError,
    WorkItem,
    build_work_items,
    parse_file_values,
    parse_target_values,
    rejoin_spaced_csv_argv,
)
from fabric_tools.validate import run_dry_run

_MANIFEST_HELP = (
    "(optional) Deployment manifest stem or path (.ftdep). "
    "Alone: load targets/files. With a successful run: write/update the manifest."
)

_BANNER = r"""
 _____     _       _         _____         _     
|   __|___| |_ ___|_|___ ___|_   _|___ ___| |___ 
|   __| .'| . |  _| |  _|___| | | | . | . | |_ -|
|__|  |__,|___|_| |_|___|     |_| |___|___|_|___|
"""


class _BannerGroup(TyperGroup):
    """Root help: banner, then subtitle, then Usage / options."""

    def format_help(self, ctx, formatter) -> None:
        typer.echo(_BANNER)
        subtitle = (self.help or "").strip()
        if subtitle:
            typer.echo(subtitle)
            typer.echo()
        saved_help = self.help
        self.help = None
        try:
            super().format_help(ctx, formatter)
        finally:
            self.help = saved_help


_HELP_CONTEXT = {"help_option_names": ["--help", "-h"]}

app = typer.Typer(
    name="fabric-tools",
    help="CLI for working with Microsoft Fabric artifacts.",
    no_args_is_help=False,
    invoke_without_command=True,
    cls=_BannerGroup,
    context_settings=_HELP_CONTEXT,
)

notebook_app = typer.Typer(
    name="notebook",
    help="Download, upload, and compare Fabric notebooks.",
    no_args_is_help=True,
    context_settings=_HELP_CONTEXT,
)
app.add_typer(notebook_app, name="notebook")

path_app = typer.Typer(
    name="path",
    help="Register fabric-tools on your user PATH so you can run it as 'fabric-tools'.",
    no_args_is_help=True,
    context_settings=_HELP_CONTEXT,
)
app.add_typer(path_app, name="path")


@app.command("inspect")
def inspect_manifest(
    manifest: str = typer.Option(
        ...,
        "--manifest",
        "-m",
        help="(required) Deployment manifest stem or path (.ftdep).",
    ),
) -> None:
    """Show the contents of a deployment manifest (no Fabric API calls)."""
    try:
        path = resolve_manifest_path(manifest)
        loaded = load_manifest(path)
    except ManifestError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=EXIT_USER) from exc
    typer.echo(format_inspect(loaded, path=path))
    raise typer.Exit(code=EXIT_OK)


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
        "-v",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        "-i",
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

        try:
            run_interactive_wizard()
        finally:
            from fabric_tools.console_ux import pause_if_double_clicked

            pause_if_double_clicked()
        return

    if ctx.invoked_subcommand is None:
        from fabric_tools.console_ux import owns_console_alone, pause_if_double_clicked

        if owns_console_alone():
            # Double-click / Explorer launch: skip Click confirm (stdin may be EOF
            # under Windows Terminal) and go straight into the wizard.
            typer.echo(
                "Opened without arguments (double-click or empty launch).\n"
                "Starting interactive mode.\n"
            )
            try:
                from fabric_tools.interactive import run_interactive_wizard

                run_interactive_wizard()
            finally:
                pause_if_double_clicked()
        else:
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
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). One workspace only.",
    ),
    file: Optional[list[str]] = typer.Option(
        None,
        "--file",
        "-f",
        help="(required without -m or -d) Local .ipynb or *.Notebook folder. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One file may broadcast to all targets.",
    ),
    manifest: Optional[str] = typer.Option(
        None,
        "--manifest",
        "-m",
        help=_MANIFEST_HELP,
    ),
    silent: bool = typer.Option(
        False,
        "--silent",
        "-s",
        help="(optional) Skip confirmation prompts.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
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
        manifest=manifest,
    )


@notebook_app.command("upload")
def notebook_upload(
    target: Optional[list[str]] = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace GUID (create) or "
        "workspace:artifact (overwrite). Repeatable or comma-separated "
        "(spaces after commas OK).",
    ),
    file: Optional[list[str]] = typer.Option(
        None,
        "--file",
        "-f",
        help="(required without -m or -d) Local .ipynb or *.Notebook folder. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One file may broadcast to all targets.",
    ),
    name: Optional[list[str]] = typer.Option(
        None,
        "--name",
        "-n",
        help="(optional, create only) Display name. Defaults to file/folder stem.",
    ),
    cells: Optional[list[str]] = typer.Option(
        None,
        "--cells",
        "-c",
        help="(optional, overwrite .ipynb only) 1-based cell indices to replace "
        "(e.g. 1,3,5 or 1, 3, 5). Single notebook only; whole cells including outputs.",
    ),
    manifest: Optional[str] = typer.Option(
        None,
        "--manifest",
        "-m",
        help=_MANIFEST_HELP,
    ),
    silent: bool = typer.Option(
        False,
        "--silent",
        "-s",
        help="(optional) Skip confirmation prompts.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
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
        cells=cells,
        manifest=manifest,
    )


@notebook_app.command("compare")
def notebook_compare(
    target: Optional[list[str]] = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One workspace only. Must 1:1 match --file.",
    ),
    file: Optional[list[str]] = typer.Option(
        None,
        "--file",
        "-f",
        help="(required without -m or -d) Local .ipynb or *.Notebook folder. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "Must 1:1 match --target (no broadcast).",
    ),
    manifest: Optional[str] = typer.Option(
        None,
        "--manifest",
        "-m",
        help=_MANIFEST_HELP,
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="(optional) Validate targets and/or files only; do not compare.",
    ),
    include_outputs: bool = typer.Option(
        True,
        "--include-outputs",
        "-i",
        help="(optional) For .ipynb diffs, include cell outputs.",
    ),
) -> None:
    """Compare remote notebook to local file (nbdime for .ipynb)."""
    run_notebook_command(
        CommandMode.COMPARE,
        target_values=target,
        file_values=file,
        silent=True,
        dry_run=dry_run,
        ignore_outputs=not include_outputs,
        manifest=manifest,
    )


def run_notebook_command(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    file_values: list[str] | None,
    silent: bool,
    dry_run: bool,
    names: list[str | None] | list[str] | None = None,
    cells: list[str] | None = None,
    ignore_outputs: bool = False,
    manifest: str | None = None,
    on_success: Callable[..., None] | None = None,
) -> None:
    """Shared entry used by CLI commands and the interactive wizard.

    *on_success* is called after a completed successful operation (all op/compare
    results ok), before the process exit code is raised — used by interactive
    mode to offer saving a deployment manifest.
    """
    try:
        cell_indices = parse_cell_indices(cells)
        items, resolved_names, has_targets, has_files = _resolve_notebook_inputs(
            mode,
            target_values=target_values,
            file_values=file_values,
            dry_run=dry_run,
            names=names,
            manifest=manifest,
        )
        validate_cells_usage(mode, items, cell_indices, dry_run=dry_run)
    except (ParseError, ManifestError, CellSelectionError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=EXIT_USER) from exc

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
                cell_indices=cell_indices,
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
            _resolve_upload_names(items, resolved_names)
            if mode is CommandMode.UPLOAD
            else None
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
            _write_manifest_after_success(
                manifest,
                items,
                display_names=None,
                op_results=op_results,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                op_results=op_results,
            )
            _exit_from_op_results(op_results)
        elif mode is CommandMode.UPLOAD:
            confirm_upload_actions(
                client,
                items,
                silent=silent,
                display_names=display_names,
                cell_indices=cell_indices,
            )
            op_results = run_upload_batch(
                client,
                items,
                display_names=display_names,
                cell_indices=cell_indices,
            )
            _print_op_results(op_results)
            for result in op_results:
                if result.ok and result.workspace_id and result.item_id:
                    if "created" in result.message:
                        typer.secho(
                            f"GUID: {result.workspace_id}:{result.item_id}",
                            fg=typer.colors.CYAN,
                        )
            _write_manifest_after_success(
                manifest,
                items,
                display_names=display_names,
                op_results=op_results,
            )
            _notify_success(
                on_success,
                items,
                display_names=display_names,
                op_results=op_results,
            )
            _exit_from_op_results(op_results)
        elif mode is CommandMode.COMPARE:
            compare_results = run_compare_batch(
                client,
                items,
                ignore_outputs=ignore_outputs,
            )
            _print_compare_results(compare_results)
            _write_manifest_after_success(
                manifest,
                items,
                display_names=None,
                compare_results=compare_results,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                compare_results=compare_results,
            )
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


def _notify_success(
    on_success: Callable[..., None] | None,
    items: list[WorkItem],
    *,
    display_names: list[str] | None,
    op_results: list[OpResult] | None = None,
    compare_results: list[CompareResult] | None = None,
) -> None:
    if on_success is None:
        return
    if op_results is not None and not all(result.ok for result in op_results):
        return
    if compare_results is not None and not all(result.ok for result in compare_results):
        return
    on_success(
        items,
        display_names=display_names,
        op_results=op_results,
        compare_results=compare_results,
    )

def _resolve_notebook_inputs(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    file_values: list[str] | None,
    dry_run: bool,
    names: list[str | None] | list[str] | None,
    manifest: str | None,
) -> tuple[list[WorkItem], list[str | None] | list[str] | None, bool, bool]:
    """Resolve targets/files from CLI and/or a deployment manifest."""
    cli_targets = parse_target_values(target_values)
    cli_files = parse_file_values(file_values)
    manifest_names: list[str | None] | None = None

    if cli_targets or cli_files:
        targets = cli_targets
        files = cli_files
    elif manifest:
        path = resolve_manifest_path(manifest)
        loaded = load_manifest(path)
        loaded_items, manifest_names = work_items_from_manifest(loaded)
        targets = [item.target for item in loaded_items if item.target is not None]
        files = [item.file for item in loaded_items if item.file is not None]
        if len(targets) != len(loaded_items) or len(files) != len(loaded_items):
            raise ManifestError(
                f"manifest {path} has incomplete entries (need workspace and file on each)"
            )
    else:
        targets = []
        files = []

    items = build_work_items(mode, targets, files, dry_run=dry_run)
    effective_names: list[str | None] | list[str] | None = (
        names if names else manifest_names
    )
    return items, effective_names, bool(targets), bool(files)


def _write_manifest_after_success(
    manifest: str | None,
    items: list[WorkItem],
    *,
    display_names: list[str] | None,
    op_results: list[OpResult] | None = None,
    compare_results: list[CompareResult] | None = None,
) -> None:
    """Rewrite ``.ftdep`` when ``-m`` is set and the operation succeeded."""
    if not manifest:
        return
    if op_results is not None and not all(result.ok for result in op_results):
        return
    if compare_results is not None and not all(result.ok for result in compare_results):
        return

    overrides = (
        item_id_overrides_from_results(op_results) if op_results is not None else None
    )
    try:
        built = manifest_from_work_items(
            items,
            display_names=display_names,
            item_id_overrides=overrides,
        )
        path = save_manifest(manifest, built)
    except ManifestError as exc:
        typer.secho(f"manifest not written: {exc}", fg=typer.colors.YELLOW, err=True)
        return
    typer.secho(f"Wrote manifest: {path}", fg=typer.colors.GREEN)


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


def run() -> None:
    """Console / exe entrypoint with a stable Usage name (not ``*.exe``)."""
    import sys
    import warnings

    # MSAL emits this library-policy hint on interactive auth; not actionable for users.
    warnings.filterwarnings(
        "ignore",
        message=r"response_mode='form_post' is recommended for better security\..*",
        category=UserWarning,
        module=r"msal\.oauth2cli\.oauth2",
    )

    # Unquoted ``-t a, b, c`` is shell-split; rejoin before Typer/Click parses.
    sys.argv = [sys.argv[0], *rejoin_spaced_csv_argv(sys.argv[1:])]
    app(prog_name="fabric-tools")

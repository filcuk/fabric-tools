"""Typer application entrypoint."""

from __future__ import annotations

from typing import Callable, Optional

import typer
from typer.core import TyperGroup

from fabric_tools import __version__
from fabric_tools.client import FabricClient
from fabric_tools.confirm import (
    ConfirmationAborted,
    confirm_delete_actions,
    confirm_delete_dataflow_gen1,
    confirm_deploy_actions,
    confirm_deploy_create_dataflow_gen1,
    confirm_download_overwrites,
    confirm_download_overwrites_dataflow_gen1,
)
from fabric_tools.exit_codes import EXIT_API, EXIT_OK, EXIT_USER
from fabric_tools.manifest import (
    KIND_DATAFLOW_GEN1,
    KIND_NOTEBOOK,
    ManifestError,
    delete_targets_from_manifest,
    format_inspect,
    format_inspect_line,
    item_id_overrides_from_results,
    list_manifest_paths,
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
from fabric_tools.notebook.ops import (
    OpResult,
    run_delete_batch,
    run_deploy_batch,
    run_download_batch,
)
from fabric_tools.parsing import (
    CommandMode,
    ParseError,
    WorkItem,
    build_work_items,
    parse_file_values,
    parse_origin_values,
    parse_target_values,
    rejoin_spaced_csv_argv,
)
from fabric_tools.powerbi_client import PowerBiClient
from fabric_tools.status import busy
from fabric_tools.update_check import UpdateCheckError, check_for_update
from fabric_tools.validate import run_dry_run, run_dry_run_dataflow_gen1

_MANIFEST_HELP = (
    "(optional) Deployment manifest stem or path (.ftdep). "
    "Alone: load targets/files/origins. With a successful run or dry-run: write/update the manifest."
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
    help="Download, deploy, compare, and delete Fabric notebooks.",
    no_args_is_help=True,
    context_settings=_HELP_CONTEXT,
)
app.add_typer(notebook_app, name="notebook")

dataflow_gen1_app = typer.Typer(
    name="dataflow-gen1",
    help="Download, create, compare, and delete Power BI Dataflow Gen1 items.",
    no_args_is_help=True,
    context_settings=_HELP_CONTEXT,
)
app.add_typer(dataflow_gen1_app, name="dataflow-gen1")

path_app = typer.Typer(
    name="path",
    help="Register fabric-tools on your user PATH so you can run it as 'fabric-tools'.",
    no_args_is_help=True,
    context_settings=_HELP_CONTEXT,
)
app.add_typer(path_app, name="path")


@app.command("update")
def update_cmd(
    check: bool = typer.Option(
        False,
        "--check",
        "-c",
        help="Check GitHub Releases for a newer fabric-tools version.",
    ),
) -> None:
    """Check for updates from GitHub Releases."""
    if not check:
        typer.secho(
            "Specify --check / -c to check for a newer release.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=EXIT_USER)

    try:
        with busy("Checking for updates..."):
            result = check_for_update()
    except UpdateCheckError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=EXIT_API) from exc

    typer.echo(f"Current version: {result.current}")
    latest_label = f"{result.latest} ({result.tag_name})"
    if result.prerelease:
        latest_label += " [pre-release]"
    typer.echo(f"Latest release:  {latest_label}")
    if result.update_available:
        typer.secho("A newer release is available.", fg=typer.colors.GREEN)
        if result.release_url:
            typer.echo(result.release_url)
        raise typer.Exit(code=EXIT_USER)

    typer.echo("You are up to date.")
    raise typer.Exit(code=EXIT_OK)


@app.command("inspect")
def inspect_manifest(
    manifest: Optional[str] = typer.Option(
        None,
        "--manifest",
        "-m",
        help="Deployment manifest stem or path (.ftdep). Omit to list all manifests in the current folder.",
    ),
) -> None:
    """Show deployment manifest contents, or list manifests in the current folder."""
    if not manifest:
        _inspect_list_cwd()
        raise typer.Exit(code=EXIT_OK)

    try:
        path = resolve_manifest_path(manifest)
        loaded = load_manifest(path)
    except ManifestError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=EXIT_USER) from exc
    typer.echo(format_inspect(loaded, path=path))
    raise typer.Exit(code=EXIT_OK)


def _inspect_list_cwd() -> None:
    """Print one-line summaries for each ``.ftdep`` in the current directory."""
    try:
        paths = list_manifest_paths()
    except ManifestError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=EXIT_USER) from exc

    if not paths:
        typer.echo("No .ftdep manifests in the current folder.")
        return

    for path in paths:
        try:
            loaded = load_manifest(path)
        except ManifestError as exc:
            typer.secho(f"{path.name}  error: {exc}", fg=typer.colors.YELLOW, err=True)
            continue
        typer.echo(format_inspect_line(loaded, path=path))


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


@notebook_app.command("deploy")
def notebook_deploy(
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
        help="(required without -m/-o or -d) Local .ipynb or *.Notebook folder. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One file may broadcast to all targets. Mutually exclusive with --origin.",
    ),
    origin: Optional[list[str]] = typer.Option(
        None,
        "--origin",
        "-o",
        help="(alternative to --file) Fabric workspace:artifact source. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One origin may broadcast to all targets. Mutually exclusive with --file.",
    ),
    name: Optional[list[str]] = typer.Option(
        None,
        "--name",
        "-n",
        help="(optional, create only) Display name. Defaults to file/folder stem "
        "or origin display name.",
    ),
    cells: Optional[list[str]] = typer.Option(
        None,
        "--cells",
        "-c",
        help="(optional, overwrite .ipynb only) 1-based cell indices to replace "
        "(e.g. 1,3,5 or 1, 3, 5). Single notebook only; whole cells including outputs. "
        "Not valid with --origin.",
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
        help="(optional) Validate targets and/or sources only; do not deploy.",
    ),
) -> None:
    """Deploy notebook(s) from local files or a Fabric origin (create or overwrite)."""
    run_notebook_command(
        CommandMode.DEPLOY,
        target_values=target,
        file_values=file,
        origin_values=origin,
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
        "With --file: one workspace only. Must 1:1 match --file or --origin.",
    ),
    file: Optional[list[str]] = typer.Option(
        None,
        "--file",
        "-f",
        help="(required without -m/-o or -d) Local .ipynb or *.Notebook folder. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "Must 1:1 match --target (no broadcast). Mutually exclusive with --origin.",
    ),
    origin: Optional[list[str]] = typer.Option(
        None,
        "--origin",
        "-o",
        help="(alternative to --file) Fabric workspace:artifact to compare against "
        "--target. Must 1:1 match --target (no broadcast). "
        "Mutually exclusive with --file.",
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
        help="(optional) Validate targets and/or sources only; do not compare.",
    ),
    include_outputs: bool = typer.Option(
        True,
        "--include-outputs",
        "-i",
        help="(optional) For .ipynb diffs, include cell outputs.",
    ),
) -> None:
    """Compare target notebook to a local file or Fabric origin (nbdime for .ipynb)."""
    run_notebook_command(
        CommandMode.COMPARE,
        target_values=target,
        file_values=file,
        origin_values=origin,
        silent=True,
        dry_run=dry_run,
        ignore_outputs=not include_outputs,
        manifest=manifest,
    )


@notebook_app.command("delete")
def notebook_delete(
    target: Optional[list[str]] = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK).",
    ),
    manifest: Optional[str] = typer.Option(
        None,
        "--manifest",
        "-m",
        help="(optional) Load workspace:artifact targets from a .ftdep "
        "(entries must have itemId). Not rewritten after delete.",
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
        help="(optional) Validate targets only; do not delete.",
    ),
) -> None:
    """Soft-delete notebook(s) in Fabric."""
    run_notebook_command(
        CommandMode.DELETE,
        target_values=target,
        file_values=None,
        silent=silent,
        dry_run=dry_run,
        manifest=manifest,
    )


@dataflow_gen1_app.command("download")
def dataflow_gen1_download(
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
        help="(required without -m or -d) Local model.json path. "
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
    """Download Dataflow Gen1 model.json from Power BI to local files."""
    run_dataflow_gen1_command(
        CommandMode.DOWNLOAD,
        target_values=target,
        file_values=file,
        silent=silent,
        dry_run=dry_run,
        manifest=manifest,
    )


@dataflow_gen1_app.command("deploy")
def dataflow_gen1_deploy(
    target: Optional[list[str]] = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace GUID (create only). "
        "Repeatable or comma-separated (spaces after commas OK). "
        "Overwrite (workspace:artifact) is not supported.",
    ),
    file: Optional[list[str]] = typer.Option(
        None,
        "--file",
        "-f",
        help="(required without -m/-o or -d) Local model.json path. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One file may broadcast to all targets. Mutually exclusive with --origin.",
    ),
    origin: Optional[list[str]] = typer.Option(
        None,
        "--origin",
        "-o",
        help="(alternative to --file) Power BI workspace:artifact source. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One origin may broadcast to all targets. Mutually exclusive with --file.",
    ),
    name: Optional[list[str]] = typer.Option(
        None,
        "--name",
        "-n",
        help="(optional) Display name written into model.json before import. "
        "Defaults to the model name (or origin name).",
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
        help="(optional) Validate targets and/or sources only; do not deploy.",
    ),
) -> None:
    """Create Dataflow Gen1 item(s) from local model.json or a remote origin."""
    run_dataflow_gen1_command(
        CommandMode.DEPLOY,
        target_values=target,
        file_values=file,
        origin_values=origin,
        silent=silent,
        dry_run=dry_run,
        names=name,
        manifest=manifest,
    )


@dataflow_gen1_app.command("compare")
def dataflow_gen1_compare(
    target: Optional[list[str]] = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "With --file: one workspace only. Must 1:1 match --file or --origin.",
    ),
    file: Optional[list[str]] = typer.Option(
        None,
        "--file",
        "-f",
        help="(required without -m/-o or -d) Local model.json path. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "Must 1:1 match --target (no broadcast). Mutually exclusive with --origin.",
    ),
    origin: Optional[list[str]] = typer.Option(
        None,
        "--origin",
        "-o",
        help="(alternative to --file) Power BI workspace:artifact to compare against "
        "--target. Must 1:1 match --target (no broadcast). "
        "Mutually exclusive with --file.",
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
        help="(optional) Validate targets and/or sources only; do not compare.",
    ),
) -> None:
    """Compare target Dataflow Gen1 to a local model.json or remote origin."""
    run_dataflow_gen1_command(
        CommandMode.COMPARE,
        target_values=target,
        file_values=file,
        origin_values=origin,
        silent=True,
        dry_run=dry_run,
        manifest=manifest,
    )


@dataflow_gen1_app.command("delete")
def dataflow_gen1_delete(
    target: Optional[list[str]] = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK).",
    ),
    manifest: Optional[str] = typer.Option(
        None,
        "--manifest",
        "-m",
        help="(optional) Load workspace:artifact targets from a .ftdep "
        "(entries must have itemId). Not rewritten after delete.",
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
        help="(optional) Validate targets only; do not delete.",
    ),
) -> None:
    """Delete Dataflow Gen1 item(s) via the Power BI API."""
    run_dataflow_gen1_command(
        CommandMode.DELETE,
        target_values=target,
        file_values=None,
        silent=silent,
        dry_run=dry_run,
        manifest=manifest,
    )


def run_notebook_command(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    file_values: list[str] | None,
    silent: bool,
    dry_run: bool,
    origin_values: list[str] | None = None,
    names: list[str | None] | list[str] | None = None,
    cells: list[str] | None = None,
    ignore_outputs: bool = False,
    manifest: str | None = None,
    on_success: Callable[..., None] | None = None,
) -> None:
    """Shared entry used by CLI commands and the interactive wizard.

    *on_success* is called after a completed successful operation or dry-run (all
    checks/ops/compare results ok), before the process exit code is raised — used
    by interactive mode to offer saving a deployment manifest.
    """
    try:
        cell_indices = parse_cell_indices(cells)
        items, resolved_names, has_targets, has_files, has_origins = (
            _resolve_notebook_inputs(
                mode,
                target_values=target_values,
                file_values=file_values,
                origin_values=origin_values,
                dry_run=dry_run,
                names=names,
                manifest=manifest,
            )
        )
        validate_cells_usage(mode, items, cell_indices, dry_run=dry_run)
    except (ParseError, ManifestError, CellSelectionError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=EXIT_USER) from exc

    if dry_run:
        client: FabricClient | None = None
        try:
            if has_targets or has_origins:
                with busy("Authenticating..."):
                    client = FabricClient()
                    client.ensure_authenticated()
            with busy("Checking..."):
                results = run_dry_run(
                    mode,
                    items,
                    client=client,
                    has_targets=has_targets,
                    has_files=has_files,
                    has_origins=has_origins,
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
        if not failed and has_targets and (has_files or has_origins):
            try:
                display_names = (
                    _resolve_deploy_names(items, resolved_names)
                    if mode is CommandMode.DEPLOY
                    else None
                )
            except ParseError as exc:
                typer.secho(str(exc), fg=typer.colors.RED, err=True)
                raise typer.Exit(code=EXIT_USER) from exc
            _write_manifest_after_success(
                manifest,
                items,
                display_names=display_names,
                kind=KIND_NOTEBOOK,
            )
            _notify_success(
                on_success,
                items,
                display_names=display_names,
            )
        raise typer.Exit(code=EXIT_USER if failed else EXIT_OK)

    try:
        display_names = (
            _resolve_deploy_names(items, resolved_names)
            if mode is CommandMode.DEPLOY
            else None
        )
    except ParseError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=EXIT_USER) from exc

    with busy("Authenticating..."):
        client = FabricClient()
        client.ensure_authenticated()
    try:
        if mode is CommandMode.DOWNLOAD:
            confirm_download_overwrites(client, items, silent=silent)
            with busy("Downloading..."):
                op_results = run_download_batch(client, items)
            _print_op_results(op_results)
            _write_manifest_after_success(
                manifest,
                items,
                display_names=None,
                op_results=op_results,
                kind=KIND_NOTEBOOK,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                op_results=op_results,
            )
            _exit_from_op_results(op_results)
        elif mode is CommandMode.DEPLOY:
            confirm_deploy_actions(
                client,
                items,
                silent=silent,
                display_names=display_names,
                cell_indices=cell_indices,
            )
            with busy("Deploying..."):
                op_results = run_deploy_batch(
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
                kind=KIND_NOTEBOOK,
            )
            _notify_success(
                on_success,
                items,
                display_names=display_names,
                op_results=op_results,
            )
            _exit_from_op_results(op_results)
        elif mode is CommandMode.COMPARE:
            with busy("Comparing..."):
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
                kind=KIND_NOTEBOOK,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                compare_results=compare_results,
            )
            _exit_from_compare_results(compare_results)
        elif mode is CommandMode.DELETE:
            confirm_delete_actions(client, items, silent=silent)
            with busy("Deleting..."):
                op_results = run_delete_batch(client, items)
            _print_op_results(op_results)
            _notify_success(
                on_success,
                items,
                display_names=None,
                op_results=op_results,
            )
            _exit_from_op_results(op_results)
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


def run_dataflow_gen1_command(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    file_values: list[str] | None,
    silent: bool,
    dry_run: bool,
    origin_values: list[str] | None = None,
    names: list[str | None] | list[str] | None = None,
    manifest: str | None = None,
    on_success: Callable[..., None] | None = None,
) -> None:
    """Shared entry for dataflow-gen1 CLI commands and the interactive wizard."""
    from fabric_tools.dataflow_gen1.compare import run_compare_batch as run_df_compare
    from fabric_tools.dataflow_gen1.definition import (
        DefinitionError as DataflowDefinitionError,
    )
    from fabric_tools.dataflow_gen1.ops import (
        run_delete_batch as run_df_delete,
    )
    from fabric_tools.dataflow_gen1.ops import (
        run_deploy_batch as run_df_deploy,
    )
    from fabric_tools.dataflow_gen1.ops import (
        run_download_batch as run_df_download,
    )

    try:
        items, resolved_names, has_targets, has_files, has_origins = (
            _resolve_dataflow_gen1_inputs(
                mode,
                target_values=target_values,
                file_values=file_values,
                origin_values=origin_values,
                dry_run=dry_run,
                names=names,
                manifest=manifest,
            )
        )
    except (ParseError, ManifestError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=EXIT_USER) from exc

    if dry_run:
        client: PowerBiClient | None = None
        try:
            if has_targets or has_origins:
                with busy("Authenticating..."):
                    client = PowerBiClient()
                    client.ensure_authenticated()
            with busy("Checking..."):
                results = run_dry_run_dataflow_gen1(
                    mode,
                    items,
                    client=client,
                    has_targets=has_targets,
                    has_files=has_files,
                    has_origins=has_origins,
                )
        except Exception as exc:  # noqa: BLE001
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
        if not failed and has_targets and (has_files or has_origins):
            try:
                display_names = (
                    _resolve_dataflow_gen1_deploy_names(items, resolved_names)
                    if mode is CommandMode.DEPLOY
                    else None
                )
            except (ParseError, DataflowDefinitionError) as exc:
                typer.secho(str(exc), fg=typer.colors.RED, err=True)
                raise typer.Exit(code=EXIT_USER) from exc
            _write_manifest_after_success(
                manifest,
                items,
                display_names=display_names,
                kind=KIND_DATAFLOW_GEN1,
            )
            _notify_success(
                on_success,
                items,
                display_names=display_names,
            )
        raise typer.Exit(code=EXIT_USER if failed else EXIT_OK)

    try:
        display_names = (
            _resolve_dataflow_gen1_deploy_names(items, resolved_names)
            if mode is CommandMode.DEPLOY
            else None
        )
    except (ParseError, DataflowDefinitionError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=EXIT_USER) from exc

    with busy("Authenticating..."):
        client = PowerBiClient()
        client.ensure_authenticated()
    try:
        if mode is CommandMode.DOWNLOAD:
            confirm_download_overwrites_dataflow_gen1(client, items, silent=silent)
            with busy("Downloading..."):
                op_results = run_df_download(client, items)
            _print_op_results(op_results)  # type: ignore[arg-type]
            _write_manifest_after_success(
                manifest,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
                kind=KIND_DATAFLOW_GEN1,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
            )
            _exit_from_op_results(op_results)  # type: ignore[arg-type]
        elif mode is CommandMode.DEPLOY:
            confirm_deploy_create_dataflow_gen1(
                client,
                items,
                silent=silent,
                display_names=display_names,
            )
            with busy("Deploying..."):
                op_results = run_df_deploy(
                    client,
                    items,
                    display_names=display_names,
                )
            _print_op_results(op_results)  # type: ignore[arg-type]
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
                op_results=op_results,  # type: ignore[arg-type]
                kind=KIND_DATAFLOW_GEN1,
            )
            _notify_success(
                on_success,
                items,
                display_names=display_names,
                op_results=op_results,  # type: ignore[arg-type]
            )
            _exit_from_op_results(op_results)  # type: ignore[arg-type]
        elif mode is CommandMode.COMPARE:
            with busy("Comparing..."):
                compare_results = run_df_compare(client, items)
            _print_compare_results(compare_results)  # type: ignore[arg-type]
            _write_manifest_after_success(
                manifest,
                items,
                display_names=None,
                compare_results=compare_results,  # type: ignore[arg-type]
                kind=KIND_DATAFLOW_GEN1,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                compare_results=compare_results,  # type: ignore[arg-type]
            )
            _exit_from_compare_results(compare_results)  # type: ignore[arg-type]
        elif mode is CommandMode.DELETE:
            confirm_delete_dataflow_gen1(client, items, silent=silent)
            with busy("Deleting..."):
                op_results = run_df_delete(client, items)
            _print_op_results(op_results)  # type: ignore[arg-type]
            _notify_success(
                on_success,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
            )
            _exit_from_op_results(op_results)  # type: ignore[arg-type]
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


def _resolve_dataflow_gen1_inputs(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    file_values: list[str] | None,
    origin_values: list[str] | None,
    dry_run: bool,
    names: list[str | None] | list[str] | None,
    manifest: str | None,
) -> tuple[list[WorkItem], list[str | None] | list[str] | None, bool, bool, bool]:
    """Resolve Gen1 targets/files/origins from CLI and/or a deployment manifest."""
    cli_targets = parse_target_values(target_values)
    cli_files = parse_file_values(file_values)
    cli_origins = parse_origin_values(origin_values)
    manifest_names: list[str | None] | None = None

    if mode is CommandMode.DELETE:
        if cli_files or cli_origins:
            raise ParseError("delete does not support --file or --origin")
        if cli_targets:
            targets = cli_targets
        elif manifest:
            path = resolve_manifest_path(manifest)
            loaded = load_manifest(path)
            items = delete_targets_from_manifest(
                loaded, expected_kind=KIND_DATAFLOW_GEN1
            )
            return items, None, True, False, False
        else:
            targets = []
        items = build_work_items(mode, targets, [], dry_run=dry_run)
        return items, None, bool(targets), False, False

    if cli_targets or cli_files or cli_origins:
        targets = cli_targets
        files = cli_files
        origins = cli_origins
    elif manifest:
        path = resolve_manifest_path(manifest)
        loaded = load_manifest(path)
        loaded_items, manifest_names = work_items_from_manifest(
            loaded, expected_kind=KIND_DATAFLOW_GEN1
        )
        targets = [item.target for item in loaded_items if item.target is not None]
        files = [item.file for item in loaded_items if item.file is not None]
        origins = [item.origin for item in loaded_items if item.origin is not None]
        if len(targets) != len(loaded_items):
            raise ManifestError(
                f"manifest {path} has incomplete entries (need workspace on each)"
            )
        if files and origins:
            raise ManifestError(
                f"manifest {path} mixes file and origin entries in one load"
            )
        if not files and not origins:
            raise ManifestError(
                f"manifest {path} has incomplete entries (need file or origin on each)"
            )
        if files and len(files) != len(loaded_items):
            raise ManifestError(
                f"manifest {path} has incomplete entries (need file on each)"
            )
        if origins and len(origins) != len(loaded_items):
            raise ManifestError(
                f"manifest {path} has incomplete entries (need origin on each)"
            )
    else:
        targets = []
        files = []
        origins = []

    items = build_work_items(
        mode,
        targets,
        files,
        origins=origins,
        dry_run=dry_run,
        deploy_create_only=True,
    )
    effective_names: list[str | None] | list[str] | None = (
        names if names else manifest_names
    )
    return items, effective_names, bool(targets), bool(files), bool(origins)


def _resolve_dataflow_gen1_deploy_names(
    items: list[WorkItem],
    names: list[str | None] | list[str] | None,
) -> list[str]:
    from fabric_tools.dataflow_gen1.definition import (
        display_name_from_model,
        load_model,
    )

    if names and len(names) not in {1, len(items)}:
        raise ParseError(
            f"--name count must be 1 or match target count ({len(items)}); "
            f"got {len(names)}"
        )
    resolved: list[str] = []
    for index, item in enumerate(items):
        chosen: str | None = None
        if names:
            chosen = names[0] if len(names) == 1 else names[index]
        if chosen:
            resolved.append(chosen)
        elif item.file is not None:
            resolved.append(display_name_from_model(load_model(item.file)))
        else:
            resolved.append("")
    return resolved


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
    origin_values: list[str] | None,
    dry_run: bool,
    names: list[str | None] | list[str] | None,
    manifest: str | None,
) -> tuple[list[WorkItem], list[str | None] | list[str] | None, bool, bool, bool]:
    """Resolve targets/files/origins from CLI and/or a deployment manifest."""
    cli_targets = parse_target_values(target_values)
    cli_files = parse_file_values(file_values)
    cli_origins = parse_origin_values(origin_values)
    manifest_names: list[str | None] | None = None

    if mode is CommandMode.DELETE:
        if cli_files or cli_origins:
            raise ParseError("delete does not support --file or --origin")
        if cli_targets:
            targets = cli_targets
        elif manifest:
            path = resolve_manifest_path(manifest)
            loaded = load_manifest(path)
            items = delete_targets_from_manifest(loaded, expected_kind=KIND_NOTEBOOK)
            return items, None, True, False, False
        else:
            targets = []
        items = build_work_items(mode, targets, [], dry_run=dry_run)
        return items, None, bool(targets), False, False

    if cli_targets or cli_files or cli_origins:
        targets = cli_targets
        files = cli_files
        origins = cli_origins
    elif manifest:
        path = resolve_manifest_path(manifest)
        loaded = load_manifest(path)
        loaded_items, manifest_names = work_items_from_manifest(
            loaded, expected_kind=KIND_NOTEBOOK
        )
        targets = [item.target for item in loaded_items if item.target is not None]
        files = [item.file for item in loaded_items if item.file is not None]
        origins = [item.origin for item in loaded_items if item.origin is not None]
        if len(targets) != len(loaded_items):
            raise ManifestError(
                f"manifest {path} has incomplete entries (need workspace on each)"
            )
        if files and origins:
            raise ManifestError(
                f"manifest {path} mixes file and origin entries in one load"
            )
        if not files and not origins:
            raise ManifestError(
                f"manifest {path} has incomplete entries (need file or origin on each)"
            )
        if files and len(files) != len(loaded_items):
            raise ManifestError(
                f"manifest {path} has incomplete entries (need file on each)"
            )
        if origins and len(origins) != len(loaded_items):
            raise ManifestError(
                f"manifest {path} has incomplete entries (need origin on each)"
            )
    else:
        targets = []
        files = []
        origins = []

    items = build_work_items(
        mode, targets, files, origins=origins, dry_run=dry_run
    )
    effective_names: list[str | None] | list[str] | None = (
        names if names else manifest_names
    )
    return items, effective_names, bool(targets), bool(files), bool(origins)


def _write_manifest_after_success(
    manifest: str | None,
    items: list[WorkItem],
    *,
    display_names: list[str] | None,
    op_results: list[OpResult] | None = None,
    compare_results: list[CompareResult] | None = None,
    kind: str = KIND_NOTEBOOK,
) -> None:
    """Rewrite ``.ftdep`` when ``-m`` is set and the operation or dry-run succeeded."""
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
            kind=kind,
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


def _resolve_deploy_names(
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
            # Origin create resolves display name at deploy time via get_item.
            resolved.append("")
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

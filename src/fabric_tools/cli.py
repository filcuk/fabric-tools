"""Typer application entrypoint."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import typer
from typer.core import TyperGroup

from fabric_tools import __version__
from fabric_tools.auth import AuthError
from fabric_tools.colours import (
    FG_ERROR,
    FG_ID,
    FG_OK,
    FG_WARN,
    STYLE_DIM,
    STYLE_ERROR,
    STYLE_OK,
    STYLE_WARN,
    apply_help_theme,
    print_banner,
    print_error_panel,
    print_warn_panel,
)
from fabric_tools.exit_codes import EXIT_API, EXIT_OK, EXIT_USER
from fabric_tools.manifest import (
    KIND_DATAFLOW,
    KIND_DATAFLOW_GEN1,
    KIND_NOTEBOOK,
    KIND_PAGINATED_REPORT,
    KIND_PIPELINE,
    KIND_REPORT,
    KIND_SEMANTIC_MODEL,
    KIND_UDF,
    ManifestError,
    delete_manifest_file,
    delete_targets_from_manifest,
    format_inspect,
    format_inspect_line,
    item_id_overrides_from_results,
    list_manifest_paths,
    load_manifest,
    manifest_from_work_items,
    move_manifest_file,
    resolve_inspect_target,
    resolve_manifest_path,
    save_manifest,
    semantic_model_id_overrides_from_results,
    semantic_model_ids_from_manifest,
    work_items_from_manifest,
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
from fabric_tools.readonly import (
    ReadOnlyError,
    ensure_command_allowed,
    ensure_setup_mutation_allowed,
)

if TYPE_CHECKING:
    from fabric_tools.notebook.compare import CompareResult
    from fabric_tools.notebook.ops import OpResult

_MANIFEST_HELP = (
    "(optional) Deployment manifest stem or path (.ftdep). "
    "Alone: load targets/files/origins. With a successful run or dry-run: write/update the manifest."
)
_GUID_REMAP_HELP = (
    "(optional, deploy only) JSON file remapping source GUID → target GUID. "
    "Applied in memory to definition text before create/update "
    "(skips .platform). Repeatable or comma-separated; one file may broadcast "
    "to all targets, or pair 1:1 with targets."
)


def _exit_error(message: str, *, code: int = EXIT_USER) -> NoReturn:
    """Print a shared Error panel and exit (never returns)."""
    print_error_panel(message)
    raise typer.Exit(code=code)


def _exit_warn(message: str, *, code: int = EXIT_USER) -> NoReturn:
    """Print a shared Warning panel and exit (never returns)."""
    print_warn_panel(message)
    raise typer.Exit(code=code)


def _resolve_deploy_guid_maps(
    remap_values: list[str] | None,
    *,
    n_targets: int,
    has_targets: bool,
) -> list:
    """Load and pair ``--remap`` / ``-r`` files for deploy / deploy dry-run.

    When there are no targets (file-only dry-run), validates that each file
    loads and returns an empty list of per-target specs.
    """
    from fabric_tools.guid_map import GuidMapError, load_guid_map, resolve_guid_maps

    if not remap_values:
        return []
    try:
        if has_targets and n_targets > 0:
            return resolve_guid_maps(remap_values, n_targets)
        # Validate maps load even when dry-run has no targets yet.
        for raw in remap_values:
            for piece in raw.split(","):
                piece = piece.strip()
                if piece:
                    load_guid_map(piece)
        return []
    except GuidMapError as exc:
        _exit_error(str(exc))


def _enforce_readonly_command(mode: CommandMode, *, dry_run: bool) -> None:
    """Exit if ``FABRIC_TOOLS_READONLY`` blocks this mode (unless dry-run)."""
    try:
        ensure_command_allowed(mode, dry_run=dry_run)
    except ReadOnlyError as exc:
        _exit_error(str(exc))


def _enforce_readonly_setup(action: str) -> None:
    """Exit if ``FABRIC_TOOLS_READONLY`` blocks a mutating setup action."""
    try:
        ensure_setup_mutation_allowed(action)
    except ReadOnlyError as exc:
        _exit_error(str(exc))


def _fail_auth(exc: AuthError) -> NoReturn:
    """Print a short auth failure and exit (never returns)."""
    if exc.canceled:
        _exit_warn(str(exc))
    _exit_error(str(exc))


def _authenticate_client(client: object) -> None:
    """Run ``ensure_authenticated`` with a clean CLI exit on ``AuthError``."""
    try:
        client.ensure_authenticated()  # type: ignore[attr-defined]
    except AuthError as exc:
        _fail_auth(exc)


def _install_description_before_usage() -> None:
    """Reorder Typer rich help: description, then Usage, then options/commands."""
    from rich.align import Align
    from rich.padding import Padding
    from typer import rich_utils

    original = rich_utils.rich_format_help

    def rich_format_help(*, obj, ctx, markup_mode):
        help_text = obj.help
        if help_text:
            console = rich_utils._get_rich_console()
            console.print(
                Padding(
                    Align(
                        rich_utils._get_help_text(obj=obj, markup_mode=markup_mode),
                        pad=False,
                    ),
                    (1, 1, 0, 1),
                )
            )
            obj.help = None
        try:
            original(obj=obj, ctx=ctx, markup_mode=markup_mode)
        finally:
            obj.help = help_text

    rich_utils.rich_format_help = rich_format_help  # type: ignore[assignment]


apply_help_theme()
_install_description_before_usage()


class _BannerGroup(TyperGroup):
    """Root help: banner, then subtitle, then Usage / options."""

    # Help list order: setup first, then manifest, then artifact groups
    # (dataflow-gen1 before dataflow; paginated-report before pipeline;
    # report before semantic-model).
    _COMMAND_ORDER = (
        "setup",
        "manifest",
        "env",
        "inspect",
        "dataflow-gen1",
        "dataflow",
        "notebook",
        "paginated-report",
        "pipeline",
        "report",
        "semantic-model",
        "udf",
    )

    def list_commands(self, ctx) -> list[str]:
        """List commands in a stable help order (setup first)."""
        names = [name for name, _command in self.commands.items()]
        ordered = [name for name in self._COMMAND_ORDER if name in names]
        remaining = [name for name in names if name not in ordered]
        return [*ordered, *remaining]

    def get_params(self, ctx):
        """Keep registration order, but list ``--help`` first among options."""
        params = list(self.params)
        help_option = self.get_help_option(ctx)
        if help_option is not None:
            return [help_option, *params]
        return params

    def format_help(self, ctx, formatter) -> None:
        subtitle = (self.help or "").strip() or None
        print_banner(subtitle=subtitle)
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
    add_completion=False,
    cls=_BannerGroup,
    context_settings=_HELP_CONTEXT,
)

notebook_app = typer.Typer(
    name="notebook",
    help="Fabric notebooks.",
    no_args_is_help=True,
    context_settings=_HELP_CONTEXT,
)
app.add_typer(notebook_app, name="notebook", rich_help_panel="Fabric")

dataflow_app = typer.Typer(
    name="dataflow",
    help="Fabric Dataflow Gen2 items.",
    no_args_is_help=True,
    context_settings=_HELP_CONTEXT,
)
app.add_typer(dataflow_app, name="dataflow", rich_help_panel="Fabric")

semantic_model_app = typer.Typer(
    name="semantic-model",
    help="Fabric semantic model items.",
    no_args_is_help=True,
    context_settings=_HELP_CONTEXT,
)
app.add_typer(semantic_model_app, name="semantic-model", rich_help_panel="Fabric")

report_app = typer.Typer(
    name="report",
    help="Fabric report items.",
    no_args_is_help=True,
    context_settings=_HELP_CONTEXT,
)
app.add_typer(report_app, name="report", rich_help_panel="Fabric")

paginated_report_app = typer.Typer(
    name="paginated-report",
    help="Power BI paginated reports (.rdl).",
    no_args_is_help=True,
    context_settings=_HELP_CONTEXT,
)
app.add_typer(paginated_report_app, name="paginated-report", rich_help_panel="Fabric")

dataflow_gen1_app = typer.Typer(
    name="dataflow-gen1",
    help="Power BI Dataflow Gen1 items.",
    no_args_is_help=True,
    context_settings=_HELP_CONTEXT,
)
app.add_typer(dataflow_gen1_app, name="dataflow-gen1", rich_help_panel="Fabric")

pipeline_app = typer.Typer(
    name="pipeline",
    help="Fabric DataPipeline items.",
    no_args_is_help=True,
    context_settings=_HELP_CONTEXT,
)
app.add_typer(pipeline_app, name="pipeline", rich_help_panel="Fabric")

udf_app = typer.Typer(
    name="udf",
    help="Fabric User Data Functions.",
    no_args_is_help=True,
    context_settings=_HELP_CONTEXT,
)
app.add_typer(udf_app, name="udf", rich_help_panel="Fabric")

inspect_app = typer.Typer(
    name="inspect",
    help="List and inspect Fabric workspaces and items.",
    no_args_is_help=True,
    context_settings=_HELP_CONTEXT,
)
inspect_workspace_app = typer.Typer(
    name="workspace",
    help="List or get Fabric workspaces.",
    no_args_is_help=True,
    context_settings=_HELP_CONTEXT,
)
inspect_item_app = typer.Typer(
    name="item",
    help="List or get Fabric items in a workspace.",
    no_args_is_help=True,
    context_settings=_HELP_CONTEXT,
)
inspect_app.add_typer(
    inspect_workspace_app,
    name="workspace",
    short_help="list | get -t <workspaceId>",
)
inspect_app.add_typer(
    inspect_item_app,
    name="item",
    short_help="list -t <workspaceId> | get -t <workspaceId:itemId>",
)
app.add_typer(inspect_app, name="inspect", rich_help_panel="Fabric")

setup_app = typer.Typer(
    name="setup",
    help="Manage fabric-tools installation and updates.",
    no_args_is_help=True,
    context_settings=_HELP_CONTEXT,
)
app.add_typer(setup_app, name="setup", rich_help_panel="Local")

env_app = typer.Typer(
    name="env",
    help="Manage environment variables.",
    no_args_is_help=True,
    context_settings=_HELP_CONTEXT,
)
app.add_typer(env_app, name="env", rich_help_panel="Local")

manifest_app = typer.Typer(
    name="manifest",
    help="Manage deployment manifests (.ftdep).",
    no_args_is_help=True,
    context_settings=_HELP_CONTEXT,
)
app.add_typer(manifest_app, name="manifest", rich_help_panel="Local")

debug_app = typer.Typer(
    name="debug",
    help="Internal debug helpers.",
    no_args_is_help=True,
    hidden=True,
    context_settings=_HELP_CONTEXT,
)
app.add_typer(debug_app, name="debug", hidden=True)


@debug_app.command("color", help="Print the CLI colour palette swatch.")
def debug_color_cmd() -> None:
    """Show each palette colour with its usage role (see DESIGN.md)."""
    from fabric_tools.colours import print_color_swatch

    print_color_swatch()
    raise typer.Exit(code=EXIT_OK)


def _flush_update_notice(ctx: typer.Context) -> None:
    """Print a background update notice on stderr, if one is ready."""
    if ctx.meta.get("skip_bg_update"):
        return
    from fabric_tools.update_check import consume_update_notice

    notice = consume_update_notice()
    if notice:
        typer.secho(notice, fg=FG_WARN, err=True)


def _start_bg_update_check(ctx: typer.Context) -> None:
    """Register notice flush and start a once-per-day background check."""
    ctx.call_on_close(lambda: _flush_update_notice(ctx))
    if ctx.meta.get("skip_bg_update"):
        return
    from fabric_tools.update_check import start_background_update_check

    start_background_update_check()


@env_app.command("list", short_help="Show catalogued variables and current values.")
def env_list() -> None:
    """Show supported environment variables and their current values."""
    from fabric_tools.env_info import print_env_report

    print_env_report()
    raise typer.Exit(code=EXIT_OK)


@env_app.command(
    "set",
    short_help="<NAME> <VALUE>  Set a catalogued user-environment variable.",
)
def env_set(
    name: str = typer.Argument(help="Variable name (from the supported catalog)."),
    value: str = typer.Argument(help="Value to store in the user environment."),
) -> None:
    """Set a supported variable in the Windows user environment."""
    from fabric_tools.env_info import EnvError, format_set_confirmation, set_user_env

    try:
        spec = set_user_env(name, value)
    except EnvError as exc:
        _exit_error(str(exc))

    typer.secho(format_set_confirmation(spec, value), fg=FG_OK)
    raise typer.Exit(code=EXIT_OK)


@env_app.command(
    "unset",
    short_help="<NAME>  Remove a catalogued user-environment variable.",
)
def env_unset(
    name: str = typer.Argument(help="Variable name (from the supported catalog)."),
) -> None:
    """Remove a supported variable from the Windows user environment."""
    from fabric_tools.env_info import (
        EnvError,
        format_unset_confirmation,
        unset_user_env,
    )

    try:
        spec = unset_user_env(name)
    except EnvError as exc:
        _exit_error(str(exc))

    typer.secho(format_unset_confirmation(spec), fg=FG_OK)
    raise typer.Exit(code=EXIT_OK)


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
    silent: bool = typer.Option(
        False,
        "--silent",
        "-s",
        help="(optional) Skip confirmation prompts.",
    ),
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
    silent: bool = typer.Option(
        False,
        "--silent",
        "-s",
        help="(optional) Skip confirmation prompts.",
    ),
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


@inspect_workspace_app.command(
    "list",
    short_help="[-f <FILTER>] [-i <TYPE>]  List accessible Fabric workspaces.",
)
def inspect_workspace_list(
    name_filter: str | None = typer.Option(
        None,
        "--filter",
        "-f",
        help="Case-insensitive substring filter on workspace display name.",
    ),
    item_type: str | None = typer.Option(
        None,
        "--item",
        "-i",
        help="Workspace type filter (Personal, Workspace, AdminWorkspace).",
    ),
) -> None:
    """List accessible Fabric workspaces (aligned table)."""
    from fabric_tools.client import FabricApiError, FabricClient
    from fabric_tools.inspect_cmd import (
        InspectError,
        list_workspaces,
        print_workspace_table,
    )
    from fabric_tools.status import busy

    try:
        with busy("Listing workspaces..."):
            client = FabricClient()
            _authenticate_client(client)
            rows = list_workspaces(
                client,
                name_filter=name_filter,
                type_filter=item_type,
            )
    except InspectError as exc:
        _exit_error(str(exc))
    except FabricApiError as exc:
        _exit_error(str(exc), code=EXIT_API)

    if not rows:
        typer.echo("No workspaces matched.")
    else:
        print_workspace_table(rows)
    raise typer.Exit(code=EXIT_OK)


@inspect_workspace_app.command(
    "get",
    short_help="-t <workspaceId>  Show detailed information for one workspace.",
)
def inspect_workspace_get(
    target: str = typer.Option(
        ...,
        "--target",
        "-t",
        help="Workspace GUID.",
    ),
) -> None:
    """Show detailed information for one Fabric workspace."""
    from fabric_tools.client import FabricApiError, FabricClient
    from fabric_tools.inspect_cmd import (
        InspectError,
        get_workspace_detail,
        parse_workspace_get_target,
        print_workspace_detail,
    )
    from fabric_tools.status import busy

    try:
        parsed = parse_workspace_get_target(target)
        with busy("Getting workspace..."):
            client = FabricClient()
            _authenticate_client(client)
            row = get_workspace_detail(client, parsed)
    except InspectError as exc:
        _exit_error(str(exc))
    except FabricApiError as exc:
        _exit_error(str(exc), code=EXIT_API)

    print_workspace_detail(row)
    raise typer.Exit(code=EXIT_OK)


@inspect_item_app.command(
    "list",
    short_help="-t <workspaceId> [-f <FILTER>] [-i <TYPE>]  List items in a workspace.",
)
def inspect_item_list(
    target: str = typer.Option(
        ...,
        "--target",
        "-t",
        help="Workspace GUID whose items to list.",
    ),
    name_filter: str | None = typer.Option(
        None,
        "--filter",
        "-f",
        help="Case-insensitive substring filter on item display name.",
    ),
    item_type: str | None = typer.Option(
        None,
        "--item",
        "-i",
        help="Fabric item type filter (Notebook, Dataflow, Report, …).",
    ),
) -> None:
    """List Fabric items in a workspace (aligned table)."""
    from fabric_tools.client import FabricApiError, FabricClient
    from fabric_tools.inspect_cmd import (
        InspectError,
        list_items,
        parse_item_list_target,
        print_item_table,
    )
    from fabric_tools.status import busy

    try:
        parsed = parse_item_list_target(target)
        with busy("Listing items..."):
            client = FabricClient()
            _authenticate_client(client)
            rows = list_items(
                client,
                parsed,
                name_filter=name_filter,
                type_filter=item_type,
            )
    except InspectError as exc:
        _exit_error(str(exc))
    except FabricApiError as exc:
        _exit_error(str(exc), code=EXIT_API)

    if not rows:
        typer.echo("No items matched.")
    else:
        print_item_table(rows)
    raise typer.Exit(code=EXIT_OK)


@inspect_item_app.command(
    "get",
    short_help="-t <workspaceId:itemId>  Show detailed information for one item.",
)
def inspect_item_get(
    target: str = typer.Option(
        ...,
        "--target",
        "-t",
        help="Workspace and item as workspaceId:itemId.",
    ),
) -> None:
    """Show detailed information for one Fabric item."""
    from fabric_tools.client import FabricApiError, FabricClient
    from fabric_tools.inspect_cmd import (
        InspectError,
        get_item_detail,
        parse_item_get_target,
        print_item_detail,
    )
    from fabric_tools.status import busy

    try:
        parsed = parse_item_get_target(target)
        with busy("Getting item..."):
            client = FabricClient()
            _authenticate_client(client)
            row = get_item_detail(client, parsed)
    except InspectError as exc:
        _exit_error(str(exc))
    except FabricApiError as exc:
        _exit_error(str(exc), code=EXIT_API)

    print_item_detail(row)
    raise typer.Exit(code=EXIT_OK)


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
            typer.secho(f"{path.name}  error: {exc}", fg=FG_WARN, err=True)
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
            _exit_error(
                "Do not combine --interactive with a subcommand. "
                "Use: fabric-tools --interactive"
            )
        from fabric_tools.interactive import run_interactive_wizard
        from fabric_tools.update_check import start_background_update_check

        start_background_update_check()
        try:
            run_interactive_wizard()
        finally:
            _flush_update_notice(ctx)
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
            from fabric_tools.update_check import start_background_update_check

            start_background_update_check()
            try:
                from fabric_tools.interactive import run_interactive_wizard

                run_interactive_wizard()
            finally:
                _flush_update_notice(ctx)
                pause_if_double_clicked()
        else:
            typer.echo(ctx.get_help())
        raise typer.Exit()

    # Nested setup commands decide whether to start the background check.
    if ctx.invoked_subcommand != "setup":
        _start_bg_update_check(ctx)


@setup_app.callback()
def setup_main(ctx: typer.Context) -> None:
    """Manage the fabric-tools install (install / update / status / clean / uninstall)."""
    root = ctx.find_root()
    if ctx.invoked_subcommand == "update":
        root.meta["skip_bg_update"] = True
        # Still register close flush so skip is honored consistently.
        root.call_on_close(lambda: _flush_update_notice(root))
        return
    _start_bg_update_check(root)


@setup_app.command("install")
def setup_install() -> None:
    """Install fabric-tools into a stable folder and register it for your user account."""
    from fabric_tools.path_setup import PathSetupError, install_to_user_path

    _enforce_readonly_setup("install")
    try:
        result = install_to_user_path()
    except PathSetupError as exc:
        _exit_error(str(exc))

    typer.secho(f"Installed launcher: {result['launcher']}", fg=FG_OK)
    typer.echo(f"Install directory: {result['install_dir']}")
    layout = result.get("layout")
    if layout == "onefile":
        typer.echo("Unpacked one-file build into a fast installed app tree.")
    elif layout == "standalone":
        typer.echo("Installed standalone app tree.")
    elif layout == "onedir":
        typer.echo("Installed onedir build (exe + _internal).")
    if result["path_added"]:
        typer.secho("Registered install directory on your user PATH.", fg=FG_OK)
    elif result["already_on_path"]:
        typer.echo("Install directory was already on your user PATH.")
    if result.get("legacy_cleaned"):
        typer.echo("Removed previous install under fabric-tools\\bin.")
    if result.get("cache_cleaned"):
        typer.echo("Removed onefile extract cache.")
    elif result.get("cache_cleanup_scheduled"):
        typer.echo("Scheduled onefile extract cache cleanup after this process exits.")
    typer.echo(
        "Open a new terminal (restart your IDE if needed), then run: fabric-tools --help"
    )
    raise typer.Exit(code=EXIT_OK)


@setup_app.command(
    "uninstall",
    short_help="[--keep-files]  Remove registration (and files by default).",
)
def setup_uninstall(
    keep_files: bool = typer.Option(
        False,
        "--keep-files",
        help="(optional) Leave installed files in place; only remove PATH registration.",
    ),
) -> None:
    """Remove fabric-tools registration (and installed files by default)."""
    from fabric_tools.path_setup import PathSetupError, uninstall_from_user_path

    _enforce_readonly_setup("uninstall")
    try:
        result = uninstall_from_user_path(delete_files=not keep_files)
    except PathSetupError as exc:
        _exit_error(str(exc))

    if result["removed_from_path"]:
        typer.secho("Removed install directory from your user PATH.", fg=FG_OK)
    else:
        typer.echo("Install directory was not present on your user PATH.")
    if result["deleted_files"]:
        typer.echo(f"Deleted: {result['deleted_files']}")
    typer.echo("Open a new terminal for PATH changes to take effect.")
    raise typer.Exit(code=EXIT_OK)


@setup_app.command("status")
def setup_status_cmd() -> None:
    """Show whether fabric-tools is installed and registered."""
    import threading

    import httpx
    from rich.console import Console, RenderableType
    from rich.live import Live
    from rich.spinner import Spinner
    from rich.table import Table
    from rich.text import Text

    from fabric_tools.path_setup import PathSetupError, path_status
    from fabric_tools.update_check import (
        UpdateCheckError,
        UpdateCheckResult,
        check_for_update,
        is_update_check_disabled,
        save_update_cache,
    )

    try:
        status = path_status()
    except PathSetupError as exc:
        _exit_error(str(exc))

    # Same key/value layout as inspect get: dim right-aligned keys, no colon,
    # two-space gap, left-aligned values.
    _gap = "  "
    keys = ("Status", "Version", "Install", "PATH", "Cache")
    key_w = max(len(k) for k in keys)
    console = Console()

    def print_row(key: str, value: str, *, value_style: str | None = None) -> None:
        line = Text()
        line.append(f"{key:>{key_w}}", style=STYLE_DIM)
        line.append(_gap)
        line.append(value, style=value_style)
        console.print(line)

    def version_renderable(
        version: str,
        *,
        latest: str | None = None,
        up_to_date: bool = False,
        note: str | None = None,
        checking: bool = False,
    ) -> RenderableType:
        if latest:
            line = Text()
            line.append(f"{'Version':>{key_w}}", style=STYLE_DIM)
            line.append(_gap)
            line.append(f"{version} < {latest}", style=STYLE_WARN)
            return line
        left = Text()
        left.append(f"{'Version':>{key_w}}", style=STYLE_DIM)
        left.append(_gap)
        if up_to_date:
            left.append(f"{version} (up to date)", style=STYLE_OK)
            return left
        if note:
            left.append(f"{version} ({note})", style=STYLE_WARN)
            return left
        left.append(version, style=STYLE_OK)
        if not checking:
            return left
        grid = Table.grid(padding=(0, 1))
        grid.add_column()
        grid.add_column()
        grid.add_row(left, Spinner("dots", text="checking…", style=STYLE_DIM))
        return grid

    def check_failure_note(exc: BaseException) -> str:
        cause = exc.__cause__
        if isinstance(cause, httpx.TimeoutException) or "timeout" in str(exc).lower():
            return "update check timeout"
        return "update check failed"

    def run_version_check(
        version: str,
    ) -> tuple[UpdateCheckResult | None, str | None]:
        try:
            result = check_for_update(current=version)
        except UpdateCheckError as exc:
            return None, check_failure_note(exc)
        save_update_cache(result)
        return result, None

    def print_version_result(
        version: str,
        result: UpdateCheckResult | None,
        *,
        note: str | None = None,
    ) -> None:
        if result is not None and result.update_available:
            console.print(version_renderable(version, latest=result.latest))
        elif result is not None:
            console.print(version_renderable(version, up_to_date=True))
        else:
            console.print(version_renderable(version, note=note))

    state = str(status["install_state"])
    if state == "installed":
        state_style = STYLE_OK
    elif state == "incomplete":
        state_style = STYLE_WARN
    else:
        state_style = STYLE_ERROR

    print_row("Status", state, value_style=state_style)

    version = str(status.get("version") or "").strip()
    if version:
        if is_update_check_disabled():
            print_version_result(version, None)
        elif not console.is_terminal:
            result, note = run_version_check(version)
            print_version_result(version, result, note=note)
        else:
            holder: dict[str, UpdateCheckResult | None | str] = {
                "result": None,
                "note": "",
            }

            def worker() -> None:
                try:
                    holder["result"] = check_for_update(current=version)
                except UpdateCheckError as exc:
                    holder["result"] = None
                    holder["note"] = check_failure_note(exc)

            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            with Live(
                version_renderable(version, checking=True),
                console=console,
                refresh_per_second=12,
                transient=False,
            ) as live:
                while thread.is_alive():
                    live.update(version_renderable(version, checking=True))
                    thread.join(timeout=0.05)
                result = holder["result"]
                note = str(holder["note"] or "") or None
                if isinstance(result, UpdateCheckResult):
                    save_update_cache(result)
                    if result.update_available:
                        live.update(version_renderable(version, latest=result.latest))
                    else:
                        live.update(version_renderable(version, up_to_date=True))
                else:
                    live.update(version_renderable(version, note=note))

    print_row("Install", str(status["install_dir"]))

    path_line = Text()
    path_line.append(f"{'PATH':>{key_w}}", style=STYLE_DIM)
    path_line.append(_gap)
    if status["bin_dir_on_user_path"]:
        path_line.append("registered", style=STYLE_OK)
        which = str(status["which_fabric_tools"] or "")
        if which:
            path_line.append(f" → {which}")
        else:
            path_line.append(" (open a new terminal if 'fabric-tools' is not found)")
    else:
        path_line.append("not registered", style=STYLE_ERROR)
    console.print(path_line)

    cache_present = bool(status["cache_present"])
    print_row(
        "Cache",
        "yes" if cache_present else "no",
        value_style=STYLE_WARN if cache_present else STYLE_OK,
    )
    if state == "installed" and cache_present:
        typer.echo()
        typer.secho(
            "Cache is only used for portable one-file runs. Clear with: ",
            dim=True,
            nl=False,
        )
        typer.secho("fabric-tools setup clean", fg=FG_ID)
    raise typer.Exit(code=EXIT_OK)


@setup_app.command("clean")
def setup_clean() -> None:
    """Remove the portable one-file extract cache (keeps the installed app)."""
    from fabric_tools.path_setup import PathSetupError, clean_onefile_caches

    _enforce_readonly_setup("clean")
    try:
        result = clean_onefile_caches()
    except PathSetupError as exc:
        _exit_error(str(exc))

    if result["cleaned"]:
        typer.secho("Removed onefile extract cache.", fg=FG_OK)
    elif result["scheduled"]:
        typer.echo("Scheduled onefile extract cache cleanup after this process exits.")
    else:
        typer.echo("No onefile extract cache found.")
    raise typer.Exit(code=EXIT_OK)


@setup_app.command(
    "update",
    short_help="[-c] [-s]  Check for a newer release, or download and install it.",
)
def setup_update(
    check: bool = typer.Option(
        False,
        "--check",
        "-c",
        help="Check GitHub Releases for a newer fabric-tools version (no install).",
    ),
    silent: bool = typer.Option(
        False,
        "--silent",
        "-s",
        help="(optional) Skip confirmation prompts when downloading/installing.",
    ),
) -> None:
    """Check for a newer release, or download and install it."""
    from fabric_tools.status import busy
    from fabric_tools.update_check import UpdateCheckError, check_for_update

    if check:
        try:
            with busy("Checking for updates..."):
                result = check_for_update()
        except UpdateCheckError as exc:
            _exit_error(str(exc), code=EXIT_API)

        typer.echo(f"Current version: {result.current}")
        latest_label = f"{result.latest} ({result.tag_name})"
        if result.prerelease:
            latest_label += " [pre-release]"
        typer.echo(f"Latest release:  {latest_label}")
        if result.update_available:
            typer.secho("A newer release is available.", fg=FG_OK)
            if result.release_url:
                typer.echo(result.release_url)
            raise typer.Exit(code=EXIT_USER)

        typer.echo("You are up to date.")
        raise typer.Exit(code=EXIT_OK)

    from fabric_tools.confirm import ConfirmationAborted
    from fabric_tools.path_setup import PathSetupError, perform_setup_update

    _enforce_readonly_setup("update")
    try:
        result = perform_setup_update(silent=silent)
    except ConfirmationAborted as exc:
        _exit_warn(str(exc))
    except PathSetupError as exc:
        _exit_error(str(exc))
    except UpdateCheckError as exc:
        _exit_error(str(exc), code=EXIT_API)

    if result.get("up_to_date"):
        typer.echo(f"Current version: {result.get('current', '')}")
        typer.echo("You are up to date.")
        raise typer.Exit(code=EXIT_OK)

    typer.secho(
        "Update scheduled — this process will exit; install continues in the background.",
        fg=FG_OK,
    )
    if result.get("exe_path"):
        typer.echo(f"Downloaded: {result['exe_path']}")
    typer.echo("Open a new terminal afterward, then run: fabric-tools --version")
    raise typer.Exit(code=EXIT_OK)


@notebook_app.command("download")
def notebook_download(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). One workspace only.",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(optional) Local .ipynb or *.Notebook folder. "
        "Defaults to remote display name with .ipynb in the current folder. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One file may broadcast to all targets.",
    ),
    manifest: str | None = typer.Option(
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
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace GUID (create) or "
        "workspace:artifact (overwrite). Repeatable or comma-separated "
        "(spaces after commas OK).",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(required without -m/-o or -d) Local .ipynb or *.Notebook folder. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One file may broadcast to all targets. Mutually exclusive with --origin.",
    ),
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(alternative to --file) Fabric workspace:artifact source. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One origin may broadcast to all targets. Mutually exclusive with --file.",
    ),
    name: list[str] | None = typer.Option(
        None,
        "--name",
        "-n",
        help="(optional, create only) Display name. Defaults to file/folder stem "
        "or origin display name.",
    ),
    cells: list[str] | None = typer.Option(
        None,
        "--cells",
        "-c",
        help="(optional, overwrite .ipynb only) 1-based cell indices to replace "
        "(e.g. 1,3,5 or 1, 3, 5). Single notebook only; whole cells including outputs. "
        "Not valid with --origin.",
    ),
    manifest: str | None = typer.Option(
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
    remap: list[str] | None = typer.Option(
        None,
        "--remap",
        "-r",
        help=_GUID_REMAP_HELP,
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
        remap_values=remap,
    )


@notebook_app.command("compare")
def notebook_compare(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "With --file: one workspace only. Must 1:1 match --file or --origin.",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(required without -m/-o or -d) Local .ipynb or *.Notebook folder. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "Must 1:1 match --target (no broadcast). Mutually exclusive with --origin.",
    ),
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(alternative to --file) Fabric workspace:artifact to compare against "
        "--target. Must 1:1 match --target (no broadcast). "
        "Mutually exclusive with --file.",
    ),
    manifest: str | None = typer.Option(
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
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK).",
    ),
    manifest: str | None = typer.Option(
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


@dataflow_app.command("download")
def dataflow_download(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). One workspace only.",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(optional) Local *.Dataflow folder. "
        "Defaults to remote display name with .Dataflow in the current folder. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One folder may broadcast to all targets.",
    ),
    manifest: str | None = typer.Option(
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
    """Download Dataflow Gen2 definition(s) from Fabric to local folders."""
    run_dataflow_command(
        CommandMode.DOWNLOAD,
        target_values=target,
        file_values=file,
        silent=silent,
        dry_run=dry_run,
        manifest=manifest,
    )


@dataflow_app.command("deploy")
def dataflow_deploy(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace GUID (create) or "
        "workspace:artifact (overwrite). Repeatable or comma-separated "
        "(spaces after commas OK).",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(required without -m/-o or -d) Local *.Dataflow folder. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One folder may broadcast to all targets. Mutually exclusive with --origin.",
    ),
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(alternative to --file) Fabric workspace:artifact source. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One origin may broadcast to all targets. Mutually exclusive with --file.",
    ),
    name: list[str] | None = typer.Option(
        None,
        "--name",
        "-n",
        help="(optional, create only) Display name. Defaults to folder stem "
        "or origin display name.",
    ),
    manifest: str | None = typer.Option(
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
    remap: list[str] | None = typer.Option(
        None,
        "--remap",
        "-r",
        help=_GUID_REMAP_HELP,
    ),
) -> None:
    """Deploy Dataflow Gen2 item(s) from local folders or a Fabric origin."""
    run_dataflow_command(
        CommandMode.DEPLOY,
        target_values=target,
        file_values=file,
        origin_values=origin,
        silent=silent,
        dry_run=dry_run,
        names=name,
        manifest=manifest,
        remap_values=remap,
    )


@dataflow_app.command("compare")
def dataflow_compare(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "With --file: one workspace only. Must 1:1 match --file or --origin.",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(required without -m/-o or -d) Local *.Dataflow folder. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "Must 1:1 match --target (no broadcast). Mutually exclusive with --origin.",
    ),
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(alternative to --file) Fabric workspace:artifact to compare against "
        "--target. Must 1:1 match --target (no broadcast). "
        "Mutually exclusive with --file.",
    ),
    manifest: str | None = typer.Option(
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
    """Compare target Dataflow Gen2 to a local folder or Fabric origin."""
    run_dataflow_command(
        CommandMode.COMPARE,
        target_values=target,
        file_values=file,
        origin_values=origin,
        silent=True,
        dry_run=dry_run,
        manifest=manifest,
    )


@dataflow_app.command("delete")
def dataflow_delete(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK).",
    ),
    manifest: str | None = typer.Option(
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
    """Soft-delete Dataflow Gen2 item(s) in Fabric."""
    run_dataflow_command(
        CommandMode.DELETE,
        target_values=target,
        file_values=None,
        silent=silent,
        dry_run=dry_run,
        manifest=manifest,
    )


@semantic_model_app.command("download")
def semantic_model_download(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). One workspace only.",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(optional) Local *.SemanticModel folder. "
        "Defaults to remote name with .SemanticModel in the current folder. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One folder may broadcast to all targets.",
    ),
    manifest: str | None = typer.Option(
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
        help="(optional) Validate targets and/or local folders only; do not download.",
    ),
) -> None:
    """Download semantic model definition(s) to local *.SemanticModel folders."""
    run_semantic_model_command(
        CommandMode.DOWNLOAD,
        target_values=target,
        file_values=file,
        silent=silent,
        dry_run=dry_run,
        manifest=manifest,
    )


@semantic_model_app.command("deploy")
def semantic_model_deploy(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace GUID (create) or "
        "workspace:artifact (overwrite). Repeatable or comma-separated.",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(required without -m/-o or -d) Local *.SemanticModel folder. "
        "Repeatable or comma-separated. One folder may broadcast to all targets.",
    ),
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(optional) Remote workspace:artifact source (mutually exclusive with --file).",
    ),
    name: list[str] | None = typer.Option(
        None,
        "--name",
        "-n",
        help="(optional) Display name for create. Defaults from folder stem. "
        "One name may broadcast.",
    ),
    manifest: str | None = typer.Option(
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
    independent: bool = typer.Option(
        False,
        "--independent",
        "-i",
        help="(optional) Model-only when the source also packages a report "
        "(e.g. thick .pbix → skipReport). No-op for *.SemanticModel folders. "
        "Not available on delete (service cascade cannot be opted out).",
    ),
) -> None:
    """Create or overwrite semantic model(s) from a local folder or Fabric origin."""
    run_semantic_model_command(
        CommandMode.DEPLOY,
        target_values=target,
        file_values=file,
        origin_values=origin,
        names=name,
        silent=silent,
        dry_run=dry_run,
        manifest=manifest,
        independent=independent,
    )


@semantic_model_app.command("compare")
def semantic_model_compare(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). One workspace only.",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(required without -m/-o or -d) Local *.SemanticModel folder. "
        "Repeatable or comma-separated (1:1 with targets).",
    ),
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(optional) Remote workspace:artifact source (mutually exclusive with --file).",
    ),
    manifest: str | None = typer.Option(
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
    """Compare target semantic model to a local folder or Fabric origin."""
    run_semantic_model_command(
        CommandMode.COMPARE,
        target_values=target,
        file_values=file,
        origin_values=origin,
        silent=True,
        dry_run=dry_run,
        manifest=manifest,
    )


@semantic_model_app.command("delete")
def semantic_model_delete(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). One workspace only.",
    ),
    manifest: str | None = typer.Option(
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
        help="(optional) Validate targets only; do not delete.",
    ),
) -> None:
    """Soft-delete semantic model(s); the service also removes dependent reports."""
    run_semantic_model_command(
        CommandMode.DELETE,
        target_values=target,
        file_values=None,
        silent=silent,
        dry_run=dry_run,
        manifest=manifest,
    )


@report_app.command("download")
def report_download(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). One workspace only.",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(optional) Local *.Report folder or .pbix path. "
        "Defaults to remote name with .Report in the current folder. "
        "Repeatable or comma-separated. One path may broadcast to all targets.",
    ),
    manifest: str | None = typer.Option(
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
        help="(optional) Validate targets and/or local paths only; do not download.",
    ),
    independent: bool = typer.Option(
        False,
        "--independent",
        "-i",
        help="(optional) Download the report only (no joined semantic model / "
        "LiveConnect for .pbix).",
    ),
) -> None:
    """Download report definition(s) to local *.Report folders or .pbix files."""
    run_report_command(
        CommandMode.DOWNLOAD,
        target_values=target,
        file_values=file,
        silent=silent,
        dry_run=dry_run,
        manifest=manifest,
        independent=independent,
    )


@report_app.command("deploy")
def report_deploy(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace GUID (create) or "
        "workspace:artifact (overwrite). Repeatable or comma-separated.",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(required without -m/-o or -d) Local *.Report folder or .pbix. "
        "Repeatable or comma-separated. One path may broadcast to all targets.",
    ),
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(optional) Remote workspace:artifact source (mutually exclusive with --file).",
    ),
    name: list[str] | None = typer.Option(
        None,
        "--name",
        "-n",
        help="(optional) Display name for create. Defaults from folder/.pbix stem. "
        "One name may broadcast.",
    ),
    manifest: str | None = typer.Option(
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
    independent: bool = typer.Option(
        False,
        "--independent",
        "-i",
        help="(optional) Deploy the report only (no joined model). "
        "Errors on thick .pbix or packable sibling *.SemanticModel.",
    ),
) -> None:
    """Create or overwrite report(s); joins a packable semantic model by default."""
    run_report_command(
        CommandMode.DEPLOY,
        target_values=target,
        file_values=file,
        origin_values=origin,
        names=name,
        silent=silent,
        dry_run=dry_run,
        manifest=manifest,
        independent=independent,
    )


@report_app.command("compare")
def report_compare(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). One workspace only.",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(required without -m/-o or -d) Local *.Report folder. "
        "Repeatable or comma-separated (1:1 with targets). .pbix is not supported.",
    ),
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(optional) Remote workspace:artifact source (mutually exclusive with --file).",
    ),
    manifest: str | None = typer.Option(
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
    independent: bool = typer.Option(
        False,
        "--independent",
        "-i",
        help="(optional) Compare the report definition only (skip joined-model notes).",
    ),
) -> None:
    """Compare target report to a local *.Report folder or Fabric origin."""
    run_report_command(
        CommandMode.COMPARE,
        target_values=target,
        file_values=file,
        origin_values=origin,
        silent=True,
        dry_run=dry_run,
        manifest=manifest,
        independent=independent,
    )


@report_app.command("delete")
def report_delete(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). One workspace only.",
    ),
    manifest: str | None = typer.Option(
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
        help="(optional) Validate targets only; do not delete.",
    ),
) -> None:
    """Soft-delete report(s); the bound semantic model is left intact."""
    run_report_command(
        CommandMode.DELETE,
        target_values=target,
        file_values=None,
        silent=silent,
        dry_run=dry_run,
        manifest=manifest,
    )


@dataflow_gen1_app.command("download")
def dataflow_gen1_download(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). One workspace only.",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(optional) Local model.json path. "
        "Defaults to remote name with .json in the current folder. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One file may broadcast to all targets.",
    ),
    manifest: str | None = typer.Option(
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
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace GUID (create only). "
        "Repeatable or comma-separated (spaces after commas OK). "
        "Overwrite (workspace:artifact) is not supported.",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(required without -m/-o or -d) Local model.json path. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One file may broadcast to all targets. Mutually exclusive with --origin.",
    ),
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(alternative to --file) Power BI workspace:artifact source. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One origin may broadcast to all targets. Mutually exclusive with --file.",
    ),
    name: list[str] | None = typer.Option(
        None,
        "--name",
        "-n",
        help="(optional) Display name written into model.json before import. "
        "Defaults to the model name (or origin name).",
    ),
    manifest: str | None = typer.Option(
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
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "With --file: one workspace only. Must 1:1 match --file or --origin.",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(required without -m/-o or -d) Local model.json path. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "Must 1:1 match --target (no broadcast). Mutually exclusive with --origin.",
    ),
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(alternative to --file) Power BI workspace:artifact to compare against "
        "--target. Must 1:1 match --target (no broadcast). "
        "Mutually exclusive with --file.",
    ),
    manifest: str | None = typer.Option(
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
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK).",
    ),
    manifest: str | None = typer.Option(
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


@paginated_report_app.command("download")
def paginated_report_download(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). One workspace only.",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(optional) Local .rdl path. "
        "Defaults to remote name with .rdl in the current folder. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One file may broadcast to all targets.",
    ),
    manifest: str | None = typer.Option(
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
    """Download paginated report RDL from Power BI to local files."""
    run_paginated_report_command(
        CommandMode.DOWNLOAD,
        target_values=target,
        file_values=file,
        silent=silent,
        dry_run=dry_run,
        manifest=manifest,
    )


@paginated_report_app.command("deploy")
def paginated_report_deploy(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace GUID (create) or "
        "workspace:artifact (overwrite). "
        "Repeatable or comma-separated (spaces after commas OK).",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(required without -m/-o or -d) Local .rdl path. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One file may broadcast to all targets. Mutually exclusive with --origin.",
    ),
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(alternative to --file) Power BI workspace:artifact source. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One origin may broadcast to all targets. Mutually exclusive with --file.",
    ),
    name: list[str] | None = typer.Option(
        None,
        "--name",
        "-n",
        help="(optional) Display name for create only. Defaults to .rdl stem "
        "(or origin name). Not used on overwrite.",
    ),
    manifest: str | None = typer.Option(
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
    """Create or overwrite paginated report(s) from local .rdl or a remote origin."""
    run_paginated_report_command(
        CommandMode.DEPLOY,
        target_values=target,
        file_values=file,
        origin_values=origin,
        silent=silent,
        dry_run=dry_run,
        names=name,
        manifest=manifest,
    )


@paginated_report_app.command("compare")
def paginated_report_compare(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "With --file: one workspace only. Must 1:1 match --file or --origin.",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(required without -m/-o or -d) Local .rdl path. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "Must 1:1 match --target (no broadcast). Mutually exclusive with --origin.",
    ),
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(alternative to --file) Power BI workspace:artifact to compare against "
        "--target. Must 1:1 match --target (no broadcast). "
        "Mutually exclusive with --file.",
    ),
    manifest: str | None = typer.Option(
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
    """Compare target paginated report to a local .rdl or remote origin."""
    run_paginated_report_command(
        CommandMode.COMPARE,
        target_values=target,
        file_values=file,
        origin_values=origin,
        silent=True,
        dry_run=dry_run,
        manifest=manifest,
    )


@paginated_report_app.command("delete")
def paginated_report_delete(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK).",
    ),
    manifest: str | None = typer.Option(
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
    """Delete paginated report(s) via the Power BI API."""
    run_paginated_report_command(
        CommandMode.DELETE,
        target_values=target,
        file_values=None,
        silent=silent,
        dry_run=dry_run,
        manifest=manifest,
    )


@pipeline_app.command("download")
def pipeline_download(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). One workspace only.",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(optional) Local *.DataPipeline folder. "
        "Defaults to remote display name with .DataPipeline in the current folder. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One folder may broadcast to all targets.",
    ),
    manifest: str | None = typer.Option(
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
    include_schedules: bool = typer.Option(
        False,
        "--include-schedules",
        "-i",
        help="(optional) Include .schedules in the downloaded folder. "
        "Default omits .schedules and removes a leftover local .schedules.",
    ),
) -> None:
    """Download DataPipeline definition(s) from Fabric to local folders."""
    run_pipeline_command(
        CommandMode.DOWNLOAD,
        target_values=target,
        file_values=file,
        silent=silent,
        dry_run=dry_run,
        manifest=manifest,
        include_schedules=include_schedules,
    )


@pipeline_app.command("deploy")
def pipeline_deploy(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace GUID (create) or "
        "workspace:artifact (overwrite). Repeatable or comma-separated "
        "(spaces after commas OK).",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(required without -m/-o or -d) Local *.DataPipeline folder. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One folder may broadcast to all targets. Mutually exclusive with --origin.",
    ),
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(alternative to --file) Fabric workspace:artifact source. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One origin may broadcast to all targets. Mutually exclusive with --file.",
    ),
    name: list[str] | None = typer.Option(
        None,
        "--name",
        "-n",
        help="(optional, create only) Display name. Defaults to folder stem "
        "or origin display name.",
    ),
    manifest: str | None = typer.Option(
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
    include_schedules: bool = typer.Option(
        False,
        "--include-schedules",
        "-i",
        help="(optional) Sync .schedules from the source. Default is pipeline-only: "
        "create omits .schedules; overwrite reattaches the target's existing "
        ".schedules so remote schedules stay untouched.",
    ),
    remap: list[str] | None = typer.Option(
        None,
        "--remap",
        "-r",
        help=_GUID_REMAP_HELP,
    ),
) -> None:
    """Deploy DataPipeline item(s) from local folders or a Fabric origin."""
    run_pipeline_command(
        CommandMode.DEPLOY,
        target_values=target,
        file_values=file,
        origin_values=origin,
        silent=silent,
        dry_run=dry_run,
        names=name,
        manifest=manifest,
        include_schedules=include_schedules,
        remap_values=remap,
    )


@pipeline_app.command("compare")
def pipeline_compare(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "With --file: one workspace only. Must 1:1 match --file or --origin.",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(required without -m/-o or -d) Local *.DataPipeline folder. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "Must 1:1 match --target (no broadcast). Mutually exclusive with --origin.",
    ),
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(alternative to --file) Fabric workspace:artifact to compare against "
        "--target. Must 1:1 match --target (no broadcast). "
        "Mutually exclusive with --file.",
    ),
    manifest: str | None = typer.Option(
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
    include_schedules: bool = typer.Option(
        False,
        "--include-schedules",
        "-i",
        help="(optional) Include .schedules in the unified diff. "
        "Default compares pipeline content only.",
    ),
) -> None:
    """Compare target DataPipeline to a local folder or Fabric origin."""
    run_pipeline_command(
        CommandMode.COMPARE,
        target_values=target,
        file_values=file,
        origin_values=origin,
        silent=True,
        dry_run=dry_run,
        manifest=manifest,
        include_schedules=include_schedules,
    )


@pipeline_app.command("delete")
def pipeline_delete(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK).",
    ),
    manifest: str | None = typer.Option(
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
    """Soft-delete DataPipeline item(s) in Fabric."""
    run_pipeline_command(
        CommandMode.DELETE,
        target_values=target,
        file_values=None,
        silent=silent,
        dry_run=dry_run,
        manifest=manifest,
    )


@udf_app.command("download")
def udf_download(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). One workspace only.",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(optional) Local *.UserDataFunction folder. "
        "Defaults to remote display name with .UserDataFunction in the current folder. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One folder may broadcast to all targets.",
    ),
    manifest: str | None = typer.Option(
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
    """Download User Data Function definition(s) from Fabric to local folders."""
    run_udf_command(
        CommandMode.DOWNLOAD,
        target_values=target,
        file_values=file,
        silent=silent,
        dry_run=dry_run,
        manifest=manifest,
    )


@udf_app.command("deploy")
def udf_deploy(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace GUID (create) or "
        "workspace:artifact (overwrite). Repeatable or comma-separated "
        "(spaces after commas OK).",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(required without -m/-o or -d) Local *.UserDataFunction folder. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One folder may broadcast to all targets. Mutually exclusive with --origin.",
    ),
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(alternative to --file) Fabric workspace:artifact source. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "One origin may broadcast to all targets. Mutually exclusive with --file.",
    ),
    name: list[str] | None = typer.Option(
        None,
        "--name",
        "-n",
        help="(optional, create only) Display name. Defaults to folder stem "
        "or origin display name.",
    ),
    manifest: str | None = typer.Option(
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
    remap: list[str] | None = typer.Option(
        None,
        "--remap",
        "-r",
        help=_GUID_REMAP_HELP,
    ),
) -> None:
    """Deploy User Data Function item(s) from local folders or a Fabric origin."""
    run_udf_command(
        CommandMode.DEPLOY,
        target_values=target,
        file_values=file,
        origin_values=origin,
        silent=silent,
        dry_run=dry_run,
        names=name,
        manifest=manifest,
        remap_values=remap,
    )


@udf_app.command("compare")
def udf_compare(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "With --file: one workspace only. Must 1:1 match --file or --origin.",
    ),
    file: list[str] | None = typer.Option(
        None,
        "--file",
        "-f",
        help="(required without -m/-o or -d) Local *.UserDataFunction folder. "
        "Repeatable or comma-separated (spaces after commas OK). "
        "Must 1:1 match --target (no broadcast). Mutually exclusive with --origin.",
    ),
    origin: list[str] | None = typer.Option(
        None,
        "--origin",
        "-o",
        help="(alternative to --file) Fabric workspace:artifact to compare against "
        "--target. Must 1:1 match --target (no broadcast). "
        "Mutually exclusive with --file.",
    ),
    manifest: str | None = typer.Option(
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
    """Compare target User Data Function to a local folder or Fabric origin."""
    run_udf_command(
        CommandMode.COMPARE,
        target_values=target,
        file_values=file,
        origin_values=origin,
        silent=True,
        dry_run=dry_run,
        manifest=manifest,
    )


@udf_app.command("delete")
def udf_delete(
    target: list[str] | None = typer.Option(
        None,
        "--target",
        "-t",
        help="(required without -m or -d) workspace:artifact GUID. "
        "Repeatable or comma-separated (spaces after commas OK).",
    ),
    manifest: str | None = typer.Option(
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
    """Soft-delete User Data Function item(s) in Fabric."""
    run_udf_command(
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
    remap_values: list[str] | None = None,
    on_success: Callable[..., None] | None = None,
) -> None:
    """Shared entry used by CLI commands and the interactive wizard.

    *on_success* is called after a completed successful operation or dry-run (all
    checks/ops/compare results ok), before the process exit code is raised — used
    by interactive mode to offer saving a deployment manifest.
    """
    _enforce_readonly_command(mode, dry_run=dry_run)
    from fabric_tools.client import FabricClient
    from fabric_tools.confirm import (
        ConfirmationAborted,
        confirm_delete_actions,
        confirm_deploy_actions,
        confirm_download_overwrites,
        resolve_notebook_download_files,
    )
    from fabric_tools.guid_map import guid_map_confirm_line
    from fabric_tools.notebook.cells import (
        CellSelectionError,
        parse_cell_indices,
        validate_cells_usage,
    )
    from fabric_tools.notebook.compare import run_compare_batch
    from fabric_tools.notebook.ops import (
        run_delete_batch,
        run_deploy_batch,
        run_download_batch,
    )
    from fabric_tools.status import busy
    from fabric_tools.validate import run_dry_run

    if remap_values and mode is not CommandMode.DEPLOY:
        _exit_error("--remap / -r is only valid with deploy")

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
        _exit_error(str(exc))

    guid_map_specs = (
        _resolve_deploy_guid_maps(
            remap_values,
            n_targets=len(items),
            has_targets=has_targets,
        )
        if mode is CommandMode.DEPLOY
        else []
    )
    guid_maps = [spec.mapping if spec is not None else None for spec in guid_map_specs]
    map_line = guid_map_confirm_line(guid_map_specs) if guid_map_specs else None

    if dry_run:
        client: FabricClient | None = None
        try:
            if has_targets or has_origins:
                with busy("Authenticating..."):
                    client = FabricClient()
                    _authenticate_client(client)
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
        except AuthError as exc:
            _fail_auth(exc)
        except Exception as exc:  # noqa: BLE001 - surface auth/client failures cleanly
            _exit_error(f"dry-run failed: {exc}", code=EXIT_API)
        finally:
            if client is not None:
                client.close()

        failed = False
        for result in results:
            color = FG_OK if result.ok else FG_ERROR
            typer.secho(result.message, fg=color)
            if not result.ok:
                failed = True
        if remap_values and not failed:
            if map_line:
                typer.secho(f"remap ok: {map_line}", fg=FG_OK)
            else:
                typer.secho("remap ok: GUID remap file(s) valid", fg=FG_OK)
        if not failed and has_targets and (has_files or has_origins):
            try:
                display_names = (
                    _resolve_deploy_names(items, resolved_names)
                    if mode is CommandMode.DEPLOY
                    else None
                )
            except ParseError as exc:
                _exit_error(str(exc))
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
        _exit_error(str(exc))

    with busy("Authenticating..."):
        client = FabricClient()
        _authenticate_client(client)
    try:
        if mode is CommandMode.DOWNLOAD:
            items = resolve_notebook_download_files(client, items)
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
                guid_map_line=map_line,
            )
            with busy("Deploying..."):
                op_results = run_deploy_batch(
                    client,
                    items,
                    display_names=display_names,
                    cell_indices=cell_indices,
                    guid_maps=guid_maps or None,
                )
            _print_op_results(op_results)
            for result in op_results:
                if (
                    result.ok
                    and result.workspace_id
                    and result.item_id
                    and "created" in result.message
                ):
                    typer.secho(
                        f"GUID: {result.workspace_id}:{result.item_id}",
                        fg=FG_ID,
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
            _exit_error(f"Unknown mode: {mode}")
    except ConfirmationAborted as exc:
        _exit_warn(str(exc))
    except typer.Exit:
        raise
    except AuthError as exc:
        _fail_auth(exc)
    except Exception as exc:  # noqa: BLE001
        _exit_error(str(exc), code=EXIT_API)
    finally:
        client.close()


def run_dataflow_command(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    file_values: list[str] | None,
    silent: bool,
    dry_run: bool,
    origin_values: list[str] | None = None,
    names: list[str | None] | list[str] | None = None,
    manifest: str | None = None,
    remap_values: list[str] | None = None,
    on_success: Callable[..., None] | None = None,
) -> None:
    """Shared entry for dataflow (Gen2) CLI commands and the interactive wizard."""
    _enforce_readonly_command(mode, dry_run=dry_run)
    from fabric_tools.client import FabricClient
    from fabric_tools.confirm import (
        ConfirmationAborted,
        confirm_delete_dataflow,
        confirm_deploy_actions_dataflow,
        confirm_download_overwrites_dataflow,
        resolve_dataflow_download_files,
    )
    from fabric_tools.dataflow.compare import run_compare_batch as run_df_compare
    from fabric_tools.dataflow.ops import (
        run_delete_batch as run_df_delete,
    )
    from fabric_tools.dataflow.ops import (
        run_deploy_batch as run_df_deploy,
    )
    from fabric_tools.dataflow.ops import (
        run_download_batch as run_df_download,
    )
    from fabric_tools.guid_map import guid_map_confirm_line
    from fabric_tools.status import busy
    from fabric_tools.validate import run_dry_run_dataflow

    if remap_values and mode is not CommandMode.DEPLOY:
        _exit_error("--remap / -r is only valid with deploy")

    try:
        items, resolved_names, has_targets, has_files, has_origins = (
            _resolve_dataflow_inputs(
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
        _exit_error(str(exc))

    guid_map_specs = (
        _resolve_deploy_guid_maps(
            remap_values,
            n_targets=len(items),
            has_targets=has_targets,
        )
        if mode is CommandMode.DEPLOY
        else []
    )
    guid_maps = [spec.mapping if spec is not None else None for spec in guid_map_specs]
    map_line = guid_map_confirm_line(guid_map_specs) if guid_map_specs else None

    if dry_run:
        client: FabricClient | None = None
        try:
            if has_targets or has_origins:
                with busy("Authenticating..."):
                    client = FabricClient()
                    _authenticate_client(client)
            with busy("Checking..."):
                results = run_dry_run_dataflow(
                    mode,
                    items,
                    client=client,
                    has_targets=has_targets,
                    has_files=has_files,
                    has_origins=has_origins,
                )
        except AuthError as exc:
            _fail_auth(exc)
        except Exception as exc:  # noqa: BLE001
            _exit_error(f"dry-run failed: {exc}", code=EXIT_API)
        finally:
            if client is not None:
                client.close()

        failed = False
        for result in results:
            color = FG_OK if result.ok else FG_ERROR
            typer.secho(result.message, fg=color)
            if not result.ok:
                failed = True
        if remap_values and not failed:
            if map_line:
                typer.secho(f"remap ok: {map_line}", fg=FG_OK)
            else:
                typer.secho("remap ok: GUID remap file(s) valid", fg=FG_OK)
        if not failed and has_targets and (has_files or has_origins):
            try:
                display_names = (
                    _resolve_dataflow_deploy_names(items, resolved_names)
                    if mode is CommandMode.DEPLOY
                    else None
                )
            except ParseError as exc:
                _exit_error(str(exc))
            _write_manifest_after_success(
                manifest,
                items,
                display_names=display_names,
                kind=KIND_DATAFLOW,
            )
            _notify_success(
                on_success,
                items,
                display_names=display_names,
            )
        raise typer.Exit(code=EXIT_USER if failed else EXIT_OK)

    try:
        display_names = (
            _resolve_dataflow_deploy_names(items, resolved_names)
            if mode is CommandMode.DEPLOY
            else None
        )
    except ParseError as exc:
        _exit_error(str(exc))

    with busy("Authenticating..."):
        client = FabricClient()
        _authenticate_client(client)
    try:
        if mode is CommandMode.DOWNLOAD:
            items = resolve_dataflow_download_files(client, items)
            confirm_download_overwrites_dataflow(client, items, silent=silent)
            with busy("Downloading..."):
                op_results = run_df_download(client, items)
            _print_op_results(op_results)  # type: ignore[arg-type]
            _write_manifest_after_success(
                manifest,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
                kind=KIND_DATAFLOW,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
            )
            _exit_from_op_results(op_results)  # type: ignore[arg-type]
        elif mode is CommandMode.DEPLOY:
            confirm_deploy_actions_dataflow(
                client,
                items,
                silent=silent,
                display_names=display_names,
                guid_map_line=map_line,
            )
            with busy("Deploying..."):
                op_results = run_df_deploy(
                    client,
                    items,
                    display_names=display_names,
                    guid_maps=guid_maps or None,
                )
            _print_op_results(op_results)  # type: ignore[arg-type]
            for result in op_results:
                if (
                    result.ok
                    and result.workspace_id
                    and result.item_id
                    and "created" in result.message
                ):
                    typer.secho(
                        f"GUID: {result.workspace_id}:{result.item_id}",
                        fg=FG_ID,
                    )
            _write_manifest_after_success(
                manifest,
                items,
                display_names=display_names,
                op_results=op_results,  # type: ignore[arg-type]
                kind=KIND_DATAFLOW,
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
                kind=KIND_DATAFLOW,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                compare_results=compare_results,  # type: ignore[arg-type]
            )
            _exit_from_compare_results(compare_results)  # type: ignore[arg-type]
        elif mode is CommandMode.DELETE:
            confirm_delete_dataflow(client, items, silent=silent)
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
            _exit_error(f"Unknown mode: {mode}")
    except ConfirmationAborted as exc:
        _exit_warn(str(exc))
    except typer.Exit:
        raise
    except AuthError as exc:
        _fail_auth(exc)
    except Exception as exc:  # noqa: BLE001
        _exit_error(str(exc), code=EXIT_API)
    finally:
        client.close()


def run_semantic_model_command(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    file_values: list[str] | None,
    silent: bool,
    dry_run: bool,
    origin_values: list[str] | None = None,
    names: list[str | None] | list[str] | None = None,
    manifest: str | None = None,
    independent: bool = False,
    on_success: Callable[..., None] | None = None,
) -> None:
    """Shared entry for semantic-model CLI commands and the interactive wizard."""
    _enforce_readonly_command(mode, dry_run=dry_run)
    from fabric_tools.client import FabricClient
    from fabric_tools.confirm import (
        ConfirmationAborted,
        confirm_delete_semantic_model,
        confirm_deploy_actions_semantic_model,
        confirm_download_overwrites_semantic_model,
        resolve_semantic_model_download_files,
    )
    from fabric_tools.semantic_model.compare import (
        run_compare_batch as run_sm_compare,
    )
    from fabric_tools.semantic_model.ops import (
        run_delete_batch as run_sm_delete,
    )
    from fabric_tools.semantic_model.ops import (
        run_deploy_batch as run_sm_deploy,
    )
    from fabric_tools.semantic_model.ops import (
        run_download_batch as run_sm_download,
    )
    from fabric_tools.status import busy
    from fabric_tools.validate import run_dry_run_semantic_model

    if independent and mode is not CommandMode.DEPLOY:
        _exit_error(
            "--independent / -i is only valid on semantic-model deploy "
            "(delete always follows service cascade)."
        )

    try:
        items, resolved_names, has_targets, has_files, has_origins = (
            _resolve_semantic_model_inputs(
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
        _exit_error(str(exc))

    if mode is CommandMode.DEPLOY and any(
        item.file is not None and item.file.suffix.lower() == ".pbix" for item in items
    ):
        _exit_error(
            "semantic-model deploy from .pbix is not supported yet "
            "(folder *.SemanticModel only; PBIX skipReport via --independent "
            "comes with report support)."
        )

    # Folder/origin deploy is already model-only; --independent is reserved for
    # thick .pbix (skipReport) once PBIX import is wired.
    _ = independent

    if dry_run:
        client: FabricClient | None = None
        try:
            if has_targets or has_origins:
                with busy("Authenticating..."):
                    client = FabricClient()
                    _authenticate_client(client)
            with busy("Checking..."):
                results = run_dry_run_semantic_model(
                    mode,
                    items,
                    client=client,
                    has_targets=has_targets,
                    has_files=has_files,
                    has_origins=has_origins,
                )
        except AuthError as exc:
            _fail_auth(exc)
        except Exception as exc:  # noqa: BLE001
            _exit_error(f"dry-run failed: {exc}", code=EXIT_API)
        finally:
            if client is not None:
                client.close()

        failed = False
        for result in results:
            color = FG_OK if result.ok else FG_ERROR
            typer.secho(result.message, fg=color)
            if not result.ok:
                failed = True
        if not failed and has_targets and (has_files or has_origins):
            try:
                display_names = (
                    _resolve_semantic_model_deploy_names(items, resolved_names)
                    if mode is CommandMode.DEPLOY
                    else None
                )
            except ParseError as exc:
                _exit_error(str(exc))
            _write_manifest_after_success(
                manifest,
                items,
                display_names=display_names,
                kind=KIND_SEMANTIC_MODEL,
            )
            _notify_success(
                on_success,
                items,
                display_names=display_names,
            )
        raise typer.Exit(code=EXIT_USER if failed else EXIT_OK)

    try:
        display_names = (
            _resolve_semantic_model_deploy_names(items, resolved_names)
            if mode is CommandMode.DEPLOY
            else None
        )
    except ParseError as exc:
        _exit_error(str(exc))

    with busy("Authenticating..."):
        client = FabricClient()
        _authenticate_client(client)
    try:
        if mode is CommandMode.DOWNLOAD:
            items = resolve_semantic_model_download_files(client, items)
            confirm_download_overwrites_semantic_model(client, items, silent=silent)
            with busy("Downloading..."):
                op_results = run_sm_download(client, items)
            _print_op_results(op_results)  # type: ignore[arg-type]
            _write_manifest_after_success(
                manifest,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
                kind=KIND_SEMANTIC_MODEL,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
            )
            _exit_from_op_results(op_results)  # type: ignore[arg-type]
        elif mode is CommandMode.DEPLOY:
            confirm_deploy_actions_semantic_model(
                client,
                items,
                silent=silent,
                display_names=display_names,
            )
            with busy("Deploying..."):
                op_results = run_sm_deploy(
                    client,
                    items,
                    display_names=display_names,
                )
            _print_op_results(op_results)  # type: ignore[arg-type]
            for result in op_results:
                if (
                    result.ok
                    and result.workspace_id
                    and result.item_id
                    and "created" in result.message
                ):
                    typer.secho(
                        f"GUID: {result.workspace_id}:{result.item_id}",
                        fg=FG_ID,
                    )
            _write_manifest_after_success(
                manifest,
                items,
                display_names=display_names,
                op_results=op_results,  # type: ignore[arg-type]
                kind=KIND_SEMANTIC_MODEL,
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
                compare_results = run_sm_compare(client, items)
            _print_compare_results(compare_results)  # type: ignore[arg-type]
            _write_manifest_after_success(
                manifest,
                items,
                display_names=None,
                compare_results=compare_results,  # type: ignore[arg-type]
                kind=KIND_SEMANTIC_MODEL,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                compare_results=compare_results,  # type: ignore[arg-type]
            )
            _exit_from_compare_results(compare_results)  # type: ignore[arg-type]
        elif mode is CommandMode.DELETE:
            confirm_delete_semantic_model(client, items, silent=silent)
            with busy("Deleting..."):
                op_results = run_sm_delete(client, items)
            _print_op_results(op_results)  # type: ignore[arg-type]
            _notify_success(
                on_success,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
            )
            _exit_from_op_results(op_results)  # type: ignore[arg-type]
        else:
            _exit_error(f"Unknown mode: {mode}")
    except ConfirmationAborted as exc:
        _exit_warn(str(exc))
    except typer.Exit:
        raise
    except AuthError as exc:
        _fail_auth(exc)
    except Exception as exc:  # noqa: BLE001
        _exit_error(str(exc), code=EXIT_API)
    finally:
        client.close()


def run_report_command(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    file_values: list[str] | None,
    silent: bool,
    dry_run: bool,
    origin_values: list[str] | None = None,
    names: list[str | None] | list[str] | None = None,
    manifest: str | None = None,
    independent: bool = False,
    on_success: Callable[..., None] | None = None,
) -> None:
    """Shared entry for report CLI commands and the interactive wizard."""
    _enforce_readonly_command(mode, dry_run=dry_run)
    from fabric_tools.client import FabricClient
    from fabric_tools.confirm import (
        ConfirmationAborted,
        confirm_delete_report,
        confirm_deploy_actions_report,
        confirm_download_overwrites_report,
        resolve_report_download_files,
    )
    from fabric_tools.report.compare import (
        run_compare_batch as run_report_compare,
    )
    from fabric_tools.report.definition import (
        DefinitionError as ReportDefinitionError,
    )
    from fabric_tools.report.definition import (
        is_pbix_path,
        packable_local_model,
    )
    from fabric_tools.report.ops import (
        run_delete_batch as run_report_delete,
    )
    from fabric_tools.report.ops import (
        run_deploy_batch as run_report_deploy,
    )
    from fabric_tools.report.ops import (
        run_download_batch as run_report_download,
    )
    from fabric_tools.status import busy
    from fabric_tools.validate import run_dry_run_report

    if independent and mode is CommandMode.DELETE:
        _exit_error(
            "--independent / -i is not used on report delete "
            "(delete always removes the report only)."
        )

    try:
        items, resolved_names, has_targets, has_files, has_origins, sm_ids = (
            _resolve_report_inputs(
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
        _exit_error(str(exc))

    if dry_run:
        client: FabricClient | None = None
        try:
            if has_targets or has_origins:
                with busy("Authenticating..."):
                    client = FabricClient()
                    _authenticate_client(client)
            with busy("Checking..."):
                results = run_dry_run_report(
                    mode,
                    items,
                    client=client,
                    has_targets=has_targets,
                    has_files=has_files,
                    has_origins=has_origins,
                )
        except AuthError as exc:
            _fail_auth(exc)
        except Exception as exc:  # noqa: BLE001
            _exit_error(f"dry-run failed: {exc}", code=EXIT_API)
        finally:
            if client is not None:
                client.close()

        failed = False
        for result in results:
            color = FG_OK if result.ok else FG_ERROR
            typer.secho(result.message, fg=color)
            if not result.ok:
                failed = True
        if not failed and has_targets and (has_files or has_origins):
            try:
                display_names = (
                    _resolve_report_deploy_names(items, resolved_names)
                    if mode is CommandMode.DEPLOY
                    else None
                )
            except ParseError as exc:
                _exit_error(str(exc))
            _write_manifest_after_success(
                manifest,
                items,
                display_names=display_names,
                kind=KIND_REPORT,
                semantic_model_ids=sm_ids,
            )
            _notify_success(
                on_success,
                items,
                display_names=display_names,
            )
        raise typer.Exit(code=EXIT_USER if failed else EXIT_OK)

    try:
        display_names = (
            _resolve_report_deploy_names(items, resolved_names)
            if mode is CommandMode.DEPLOY
            else None
        )
    except ParseError as exc:
        _exit_error(str(exc))

    with busy("Authenticating..."):
        client = FabricClient()
        _authenticate_client(client)
    try:
        if mode is CommandMode.DOWNLOAD:
            items = resolve_report_download_files(client, items)
            confirm_download_overwrites_report(client, items, silent=silent)
            with busy("Downloading..."):
                op_results = run_report_download(client, items, independent=independent)
            _print_op_results(op_results)  # type: ignore[arg-type]
            _write_manifest_after_success(
                manifest,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
                kind=KIND_REPORT,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
            )
            _exit_from_op_results(op_results)  # type: ignore[arg-type]
        elif mode is CommandMode.DEPLOY:
            join_model_paths: list[object | None] = []
            for item in items:
                if independent or item.file is None or is_pbix_path(item.file):
                    join_model_paths.append(None)
                    continue
                try:
                    join_model_paths.append(packable_local_model(item.file))
                except ReportDefinitionError:
                    join_model_paths.append(None)
            confirm_deploy_actions_report(
                client,
                items,
                silent=silent,
                display_names=display_names,
                independent=independent,
                join_model_paths=join_model_paths,  # type: ignore[arg-type]
            )
            with busy("Deploying..."):
                op_results = run_report_deploy(
                    client,
                    items,
                    display_names=display_names,
                    independent=independent,
                    semantic_model_ids=sm_ids,
                )
            _print_op_results(op_results)  # type: ignore[arg-type]
            for result in op_results:
                if (
                    result.ok
                    and result.workspace_id
                    and result.item_id
                    and "created" in result.message
                ):
                    typer.secho(
                        f"GUID: {result.workspace_id}:{result.item_id}",
                        fg=FG_ID,
                    )
                    sm = getattr(result, "semantic_model_id", None)
                    if sm:
                        typer.secho(
                            f"semanticModelId: {sm}",
                            fg=FG_ID,
                        )
            _write_manifest_after_success(
                manifest,
                items,
                display_names=display_names,
                op_results=op_results,  # type: ignore[arg-type]
                kind=KIND_REPORT,
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
                compare_results = run_report_compare(
                    client, items, independent=independent
                )
            _print_compare_results(compare_results)  # type: ignore[arg-type]
            _write_manifest_after_success(
                manifest,
                items,
                display_names=None,
                compare_results=compare_results,  # type: ignore[arg-type]
                kind=KIND_REPORT,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                compare_results=compare_results,  # type: ignore[arg-type]
            )
            _exit_from_compare_results(compare_results)  # type: ignore[arg-type]
        elif mode is CommandMode.DELETE:
            confirm_delete_report(client, items, silent=silent)
            with busy("Deleting..."):
                op_results = run_report_delete(client, items)
            _print_op_results(op_results)  # type: ignore[arg-type]
            _notify_success(
                on_success,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
            )
            _exit_from_op_results(op_results)  # type: ignore[arg-type]
        else:
            _exit_error(f"Unknown mode: {mode}")
    except ConfirmationAborted as exc:
        _exit_warn(str(exc))
    except typer.Exit:
        raise
    except AuthError as exc:
        _fail_auth(exc)
    except Exception as exc:  # noqa: BLE001
        _exit_error(str(exc), code=EXIT_API)
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
    _enforce_readonly_command(mode, dry_run=dry_run)
    from fabric_tools.confirm import (
        ConfirmationAborted,
        confirm_delete_dataflow_gen1,
        confirm_deploy_create_dataflow_gen1,
        confirm_download_overwrites_dataflow_gen1,
        resolve_dataflow_gen1_download_files,
    )
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
    from fabric_tools.powerbi_client import PowerBiClient
    from fabric_tools.status import busy
    from fabric_tools.validate import run_dry_run_dataflow_gen1

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
        _exit_error(str(exc))

    if dry_run:
        client: PowerBiClient | None = None
        try:
            if has_targets or has_origins:
                with busy("Authenticating..."):
                    client = PowerBiClient()
                    _authenticate_client(client)
            with busy("Checking..."):
                results = run_dry_run_dataflow_gen1(
                    mode,
                    items,
                    client=client,
                    has_targets=has_targets,
                    has_files=has_files,
                    has_origins=has_origins,
                )
        except AuthError as exc:
            _fail_auth(exc)
        except Exception as exc:  # noqa: BLE001
            _exit_error(f"dry-run failed: {exc}", code=EXIT_API)
        finally:
            if client is not None:
                client.close()

        failed = False
        for result in results:
            color = FG_OK if result.ok else FG_ERROR
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
                _exit_error(str(exc))
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
        _exit_error(str(exc))

    with busy("Authenticating..."):
        client = PowerBiClient()
        _authenticate_client(client)
    try:
        if mode is CommandMode.DOWNLOAD:
            items = resolve_dataflow_gen1_download_files(client, items)
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
                if (
                    result.ok
                    and result.workspace_id
                    and result.item_id
                    and "created" in result.message
                ):
                    typer.secho(
                        f"GUID: {result.workspace_id}:{result.item_id}",
                        fg=FG_ID,
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
            _exit_error(f"Unknown mode: {mode}")
    except ConfirmationAborted as exc:
        _exit_warn(str(exc))
    except typer.Exit:
        raise
    except AuthError as exc:
        _fail_auth(exc)
    except Exception as exc:  # noqa: BLE001
        _exit_error(str(exc), code=EXIT_API)
    finally:
        client.close()


def run_paginated_report_command(
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
    """Shared entry for paginated-report CLI commands and the interactive wizard."""
    _enforce_readonly_command(mode, dry_run=dry_run)
    from fabric_tools.confirm import (
        ConfirmationAborted,
        confirm_delete_paginated_report,
        confirm_deploy_actions_paginated_report,
        confirm_download_overwrites_paginated_report,
        resolve_paginated_report_download_files,
    )
    from fabric_tools.paginated_report.compare import (
        run_compare_batch as run_pr_compare,
    )
    from fabric_tools.paginated_report.definition import (
        DefinitionError as PaginatedReportDefinitionError,
    )
    from fabric_tools.paginated_report.ops import (
        run_delete_batch as run_pr_delete,
    )
    from fabric_tools.paginated_report.ops import (
        run_deploy_batch as run_pr_deploy,
    )
    from fabric_tools.paginated_report.ops import (
        run_download_batch as run_pr_download,
    )
    from fabric_tools.powerbi_client import PowerBiClient
    from fabric_tools.status import busy
    from fabric_tools.validate import run_dry_run_paginated_report

    try:
        items, resolved_names, has_targets, has_files, has_origins = (
            _resolve_paginated_report_inputs(
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
        _exit_error(str(exc))

    if dry_run:
        client: PowerBiClient | None = None
        try:
            if has_targets or has_origins:
                with busy("Authenticating..."):
                    client = PowerBiClient()
                    _authenticate_client(client)
            with busy("Checking..."):
                results = run_dry_run_paginated_report(
                    mode,
                    items,
                    client=client,
                    has_targets=has_targets,
                    has_files=has_files,
                    has_origins=has_origins,
                )
        except AuthError as exc:
            _fail_auth(exc)
        except Exception as exc:  # noqa: BLE001
            _exit_error(f"dry-run failed: {exc}", code=EXIT_API)
        finally:
            if client is not None:
                client.close()

        failed = False
        for result in results:
            color = FG_OK if result.ok else FG_ERROR
            typer.secho(result.message, fg=color)
            if not result.ok:
                failed = True
        if not failed and has_targets and (has_files or has_origins):
            try:
                display_names = (
                    _resolve_paginated_report_deploy_names(items, resolved_names)
                    if mode is CommandMode.DEPLOY
                    else None
                )
            except (ParseError, PaginatedReportDefinitionError) as exc:
                _exit_error(str(exc))
            _write_manifest_after_success(
                manifest,
                items,
                display_names=display_names,
                kind=KIND_PAGINATED_REPORT,
            )
            _notify_success(
                on_success,
                items,
                display_names=display_names,
            )
        raise typer.Exit(code=EXIT_USER if failed else EXIT_OK)

    try:
        display_names = (
            _resolve_paginated_report_deploy_names(items, resolved_names)
            if mode is CommandMode.DEPLOY
            else None
        )
    except (ParseError, PaginatedReportDefinitionError) as exc:
        _exit_error(str(exc))

    with busy("Authenticating..."):
        client = PowerBiClient()
        _authenticate_client(client)
    try:
        if mode is CommandMode.DOWNLOAD:
            items = resolve_paginated_report_download_files(client, items)
            confirm_download_overwrites_paginated_report(client, items, silent=silent)
            with busy("Downloading..."):
                op_results = run_pr_download(client, items)
            _print_op_results(op_results)  # type: ignore[arg-type]
            _write_manifest_after_success(
                manifest,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
                kind=KIND_PAGINATED_REPORT,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
            )
            _exit_from_op_results(op_results)  # type: ignore[arg-type]
        elif mode is CommandMode.DEPLOY:
            confirm_deploy_actions_paginated_report(
                client,
                items,
                silent=silent,
                display_names=display_names,
            )
            with busy("Deploying..."):
                op_results = run_pr_deploy(
                    client,
                    items,
                    display_names=display_names,
                )
            _print_op_results(op_results)  # type: ignore[arg-type]
            for result in op_results:
                if (
                    result.ok
                    and result.workspace_id
                    and result.item_id
                    and "created" in result.message
                ):
                    typer.secho(
                        f"GUID: {result.workspace_id}:{result.item_id}",
                        fg=FG_ID,
                    )
            _write_manifest_after_success(
                manifest,
                items,
                display_names=display_names,
                op_results=op_results,  # type: ignore[arg-type]
                kind=KIND_PAGINATED_REPORT,
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
                compare_results = run_pr_compare(client, items)
            _print_compare_results(compare_results)  # type: ignore[arg-type]
            _write_manifest_after_success(
                manifest,
                items,
                display_names=None,
                compare_results=compare_results,  # type: ignore[arg-type]
                kind=KIND_PAGINATED_REPORT,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                compare_results=compare_results,  # type: ignore[arg-type]
            )
            _exit_from_compare_results(compare_results)  # type: ignore[arg-type]
        elif mode is CommandMode.DELETE:
            confirm_delete_paginated_report(client, items, silent=silent)
            with busy("Deleting..."):
                op_results = run_pr_delete(client, items)
            _print_op_results(op_results)  # type: ignore[arg-type]
            _notify_success(
                on_success,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
            )
            _exit_from_op_results(op_results)  # type: ignore[arg-type]
        else:
            _exit_error(f"Unknown mode: {mode}")
    except ConfirmationAborted as exc:
        _exit_warn(str(exc))
    except typer.Exit:
        raise
    except AuthError as exc:
        _fail_auth(exc)
    except Exception as exc:  # noqa: BLE001
        _exit_error(str(exc), code=EXIT_API)
    finally:
        client.close()


def run_pipeline_command(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    file_values: list[str] | None,
    silent: bool,
    dry_run: bool,
    origin_values: list[str] | None = None,
    names: list[str | None] | list[str] | None = None,
    manifest: str | None = None,
    include_schedules: bool = False,
    remap_values: list[str] | None = None,
    on_success: Callable[..., None] | None = None,
) -> None:
    """Shared entry for pipeline CLI commands and the interactive wizard."""
    _enforce_readonly_command(mode, dry_run=dry_run)
    from fabric_tools.client import FabricClient
    from fabric_tools.confirm import (
        ConfirmationAborted,
        confirm_delete_pipeline,
        confirm_deploy_actions_pipeline,
        confirm_download_overwrites_pipeline,
        resolve_pipeline_download_files,
    )
    from fabric_tools.guid_map import guid_map_confirm_line
    from fabric_tools.pipeline.compare import run_compare_batch as run_pl_compare
    from fabric_tools.pipeline.ops import (
        run_delete_batch as run_pl_delete,
    )
    from fabric_tools.pipeline.ops import (
        run_deploy_batch as run_pl_deploy,
    )
    from fabric_tools.pipeline.ops import (
        run_download_batch as run_pl_download,
    )
    from fabric_tools.status import busy
    from fabric_tools.validate import run_dry_run_pipeline

    if remap_values and mode is not CommandMode.DEPLOY:
        _exit_error("--remap / -r is only valid with deploy")

    try:
        items, resolved_names, has_targets, has_files, has_origins = (
            _resolve_pipeline_inputs(
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
        _exit_error(str(exc))

    guid_map_specs = (
        _resolve_deploy_guid_maps(
            remap_values,
            n_targets=len(items),
            has_targets=has_targets,
        )
        if mode is CommandMode.DEPLOY
        else []
    )
    guid_maps = [spec.mapping if spec is not None else None for spec in guid_map_specs]
    map_line = guid_map_confirm_line(guid_map_specs) if guid_map_specs else None

    if dry_run:
        client: FabricClient | None = None
        try:
            if has_targets or has_origins:
                with busy("Authenticating..."):
                    client = FabricClient()
                    _authenticate_client(client)
            with busy("Checking..."):
                results = run_dry_run_pipeline(
                    mode,
                    items,
                    client=client,
                    has_targets=has_targets,
                    has_files=has_files,
                    has_origins=has_origins,
                )
        except AuthError as exc:
            _fail_auth(exc)
        except Exception as exc:  # noqa: BLE001
            _exit_error(f"dry-run failed: {exc}", code=EXIT_API)
        finally:
            if client is not None:
                client.close()

        failed = False
        for result in results:
            color = FG_OK if result.ok else FG_ERROR
            typer.secho(result.message, fg=color)
            if not result.ok:
                failed = True
        if remap_values and not failed:
            if map_line:
                typer.secho(f"remap ok: {map_line}", fg=FG_OK)
            else:
                typer.secho("remap ok: GUID remap file(s) valid", fg=FG_OK)
        if not failed and has_targets and (has_files or has_origins):
            try:
                display_names = (
                    _resolve_pipeline_deploy_names(items, resolved_names)
                    if mode is CommandMode.DEPLOY
                    else None
                )
            except ParseError as exc:
                _exit_error(str(exc))
            _write_manifest_after_success(
                manifest,
                items,
                display_names=display_names,
                kind=KIND_PIPELINE,
            )
            _notify_success(
                on_success,
                items,
                display_names=display_names,
            )
        raise typer.Exit(code=EXIT_USER if failed else EXIT_OK)

    try:
        display_names = (
            _resolve_pipeline_deploy_names(items, resolved_names)
            if mode is CommandMode.DEPLOY
            else None
        )
    except ParseError as exc:
        _exit_error(str(exc))

    with busy("Authenticating..."):
        client = FabricClient()
        _authenticate_client(client)
    try:
        if mode is CommandMode.DOWNLOAD:
            items = resolve_pipeline_download_files(client, items)
            confirm_download_overwrites_pipeline(client, items, silent=silent)
            with busy("Downloading..."):
                op_results = run_pl_download(
                    client, items, include_schedules=include_schedules
                )
            _print_op_results(op_results)  # type: ignore[arg-type]
            _write_manifest_after_success(
                manifest,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
                kind=KIND_PIPELINE,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
            )
            _exit_from_op_results(op_results)  # type: ignore[arg-type]
        elif mode is CommandMode.DEPLOY:
            confirm_deploy_actions_pipeline(
                client,
                items,
                silent=silent,
                display_names=display_names,
                include_schedules=include_schedules,
                guid_map_line=map_line,
            )
            with busy("Deploying..."):
                op_results = run_pl_deploy(
                    client,
                    items,
                    display_names=display_names,
                    include_schedules=include_schedules,
                    guid_maps=guid_maps or None,
                )
            _print_op_results(op_results)  # type: ignore[arg-type]
            for result in op_results:
                if (
                    result.ok
                    and result.workspace_id
                    and result.item_id
                    and "created" in result.message
                ):
                    typer.secho(
                        f"GUID: {result.workspace_id}:{result.item_id}",
                        fg=FG_ID,
                    )
            _write_manifest_after_success(
                manifest,
                items,
                display_names=display_names,
                op_results=op_results,  # type: ignore[arg-type]
                kind=KIND_PIPELINE,
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
                compare_results = run_pl_compare(
                    client, items, include_schedules=include_schedules
                )
            _print_compare_results(compare_results)  # type: ignore[arg-type]
            _write_manifest_after_success(
                manifest,
                items,
                display_names=None,
                compare_results=compare_results,  # type: ignore[arg-type]
                kind=KIND_PIPELINE,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                compare_results=compare_results,  # type: ignore[arg-type]
            )
            _exit_from_compare_results(compare_results)  # type: ignore[arg-type]
        elif mode is CommandMode.DELETE:
            confirm_delete_pipeline(client, items, silent=silent)
            with busy("Deleting..."):
                op_results = run_pl_delete(client, items)
            _print_op_results(op_results)  # type: ignore[arg-type]
            _notify_success(
                on_success,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
            )
            _exit_from_op_results(op_results)  # type: ignore[arg-type]
        else:
            _exit_error(f"Unknown mode: {mode}")
    except ConfirmationAborted as exc:
        _exit_warn(str(exc))
    except typer.Exit:
        raise
    except AuthError as exc:
        _fail_auth(exc)
    except Exception as exc:  # noqa: BLE001
        _exit_error(str(exc), code=EXIT_API)
    finally:
        client.close()


def run_udf_command(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    file_values: list[str] | None,
    silent: bool,
    dry_run: bool,
    origin_values: list[str] | None = None,
    names: list[str | None] | list[str] | None = None,
    manifest: str | None = None,
    remap_values: list[str] | None = None,
    on_success: Callable[..., None] | None = None,
) -> None:
    """Shared entry for User Data Function CLI commands and the interactive wizard."""
    _enforce_readonly_command(mode, dry_run=dry_run)
    from fabric_tools.client import FabricClient
    from fabric_tools.confirm import (
        ConfirmationAborted,
        confirm_delete_udf,
        confirm_deploy_actions_udf,
        confirm_download_overwrites_udf,
        resolve_udf_download_files,
    )
    from fabric_tools.guid_map import guid_map_confirm_line
    from fabric_tools.status import busy
    from fabric_tools.udf.compare import run_compare_batch as run_udf_compare
    from fabric_tools.udf.ops import (
        UdfAuthError,
        check_udf_user_auth,
    )
    from fabric_tools.udf.ops import (
        run_delete_batch as run_udf_delete,
    )
    from fabric_tools.udf.ops import (
        run_deploy_batch as run_udf_deploy,
    )
    from fabric_tools.udf.ops import (
        run_download_batch as run_udf_download,
    )
    from fabric_tools.validate import run_dry_run_udf

    try:
        check_udf_user_auth()
    except UdfAuthError as exc:
        _exit_error(str(exc))

    if remap_values and mode is not CommandMode.DEPLOY:
        _exit_error("--remap / -r is only valid with deploy")

    try:
        items, resolved_names, has_targets, has_files, has_origins = (
            _resolve_udf_inputs(
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
        _exit_error(str(exc))

    guid_map_specs = (
        _resolve_deploy_guid_maps(
            remap_values,
            n_targets=len(items),
            has_targets=has_targets,
        )
        if mode is CommandMode.DEPLOY
        else []
    )
    guid_maps = [spec.mapping if spec is not None else None for spec in guid_map_specs]
    map_line = guid_map_confirm_line(guid_map_specs) if guid_map_specs else None

    if dry_run:
        client: FabricClient | None = None
        try:
            if has_targets or has_origins:
                with busy("Authenticating..."):
                    client = FabricClient()
                    _authenticate_client(client)
            with busy("Checking..."):
                results = run_dry_run_udf(
                    mode,
                    items,
                    client=client,
                    has_targets=has_targets,
                    has_files=has_files,
                    has_origins=has_origins,
                )
        except AuthError as exc:
            _fail_auth(exc)
        except Exception as exc:  # noqa: BLE001
            _exit_error(f"dry-run failed: {exc}", code=EXIT_API)
        finally:
            if client is not None:
                client.close()

        failed = False
        for result in results:
            color = FG_OK if result.ok else FG_ERROR
            typer.secho(result.message, fg=color)
            if not result.ok:
                failed = True
        if remap_values and not failed:
            if map_line:
                typer.secho(f"remap ok: {map_line}", fg=FG_OK)
            else:
                typer.secho("remap ok: GUID remap file(s) valid", fg=FG_OK)
        if not failed and has_targets and (has_files or has_origins):
            try:
                display_names = (
                    _resolve_udf_deploy_names(items, resolved_names)
                    if mode is CommandMode.DEPLOY
                    else None
                )
            except ParseError as exc:
                _exit_error(str(exc))
            _write_manifest_after_success(
                manifest,
                items,
                display_names=display_names,
                kind=KIND_UDF,
            )
            _notify_success(
                on_success,
                items,
                display_names=display_names,
            )
        raise typer.Exit(code=EXIT_USER if failed else EXIT_OK)

    try:
        display_names = (
            _resolve_udf_deploy_names(items, resolved_names)
            if mode is CommandMode.DEPLOY
            else None
        )
    except ParseError as exc:
        _exit_error(str(exc))

    with busy("Authenticating..."):
        client = FabricClient()
        _authenticate_client(client)
    try:
        if mode is CommandMode.DOWNLOAD:
            items = resolve_udf_download_files(client, items)
            confirm_download_overwrites_udf(client, items, silent=silent)
            with busy("Downloading..."):
                op_results = run_udf_download(client, items)
            _print_op_results(op_results)  # type: ignore[arg-type]
            _write_manifest_after_success(
                manifest,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
                kind=KIND_UDF,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
            )
            _exit_from_op_results(op_results)  # type: ignore[arg-type]
        elif mode is CommandMode.DEPLOY:
            confirm_deploy_actions_udf(
                client,
                items,
                silent=silent,
                display_names=display_names,
                guid_map_line=map_line,
            )
            with busy("Deploying..."):
                op_results = run_udf_deploy(
                    client,
                    items,
                    display_names=display_names,
                    guid_maps=guid_maps or None,
                )
            _print_op_results(op_results)  # type: ignore[arg-type]
            for result in op_results:
                if (
                    result.ok
                    and result.workspace_id
                    and result.item_id
                    and "created" in result.message
                ):
                    typer.secho(
                        f"GUID: {result.workspace_id}:{result.item_id}",
                        fg=FG_ID,
                    )
            _write_manifest_after_success(
                manifest,
                items,
                display_names=display_names,
                op_results=op_results,  # type: ignore[arg-type]
                kind=KIND_UDF,
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
                compare_results = run_udf_compare(client, items)
            _print_compare_results(compare_results)  # type: ignore[arg-type]
            _write_manifest_after_success(
                manifest,
                items,
                display_names=None,
                compare_results=compare_results,  # type: ignore[arg-type]
                kind=KIND_UDF,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                compare_results=compare_results,  # type: ignore[arg-type]
            )
            _exit_from_compare_results(compare_results)  # type: ignore[arg-type]
        elif mode is CommandMode.DELETE:
            confirm_delete_udf(client, items, silent=silent)
            with busy("Deleting..."):
                op_results = run_udf_delete(client, items)
            _print_op_results(op_results)  # type: ignore[arg-type]
            _notify_success(
                on_success,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
            )
            _exit_from_op_results(op_results)  # type: ignore[arg-type]
        else:
            _exit_error(f"Unknown mode: {mode}")
    except ConfirmationAborted as exc:
        _exit_warn(str(exc))
    except typer.Exit:
        raise
    except AuthError as exc:
        _fail_auth(exc)
    except Exception as exc:  # noqa: BLE001
        _exit_error(str(exc), code=EXIT_API)
    finally:
        client.close()


def _resolve_dataflow_inputs(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    file_values: list[str] | None,
    origin_values: list[str] | None,
    dry_run: bool,
    names: list[str | None] | list[str] | None,
    manifest: str | None,
) -> tuple[list[WorkItem], list[str | None] | list[str] | None, bool, bool, bool]:
    """Resolve Gen2 targets/files/origins from CLI and/or a deployment manifest."""
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
            items = delete_targets_from_manifest(loaded, expected_kind=KIND_DATAFLOW)
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
            loaded, expected_kind=KIND_DATAFLOW
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

    items = build_work_items(mode, targets, files, origins=origins, dry_run=dry_run)
    effective_names: list[str | None] | list[str] | None = (
        names if names else manifest_names
    )
    return items, effective_names, bool(targets), bool(files), bool(origins)


def _resolve_dataflow_deploy_names(
    items: list[WorkItem],
    names: list[str | None] | list[str] | None,
) -> list[str]:
    from fabric_tools.dataflow.definition import display_name_from_path

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
            resolved.append(display_name_from_path(item.file))
        else:
            resolved.append("")
    return resolved


def _resolve_semantic_model_inputs(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    file_values: list[str] | None,
    origin_values: list[str] | None,
    dry_run: bool,
    names: list[str | None] | list[str] | None,
    manifest: str | None,
) -> tuple[list[WorkItem], list[str | None] | list[str] | None, bool, bool, bool]:
    """Resolve semantic-model targets/files/origins from CLI and/or a manifest."""
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
                loaded, expected_kind=KIND_SEMANTIC_MODEL
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
            loaded, expected_kind=KIND_SEMANTIC_MODEL
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

    items = build_work_items(mode, targets, files, origins=origins, dry_run=dry_run)
    effective_names: list[str | None] | list[str] | None = (
        names if names else manifest_names
    )
    return items, effective_names, bool(targets), bool(files), bool(origins)


def _resolve_semantic_model_deploy_names(
    items: list[WorkItem],
    names: list[str | None] | list[str] | None,
) -> list[str]:
    from fabric_tools.semantic_model.definition import display_name_from_path

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
            resolved.append(display_name_from_path(item.file))
        else:
            resolved.append("")
    return resolved


def _resolve_report_inputs(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    file_values: list[str] | None,
    origin_values: list[str] | None,
    dry_run: bool,
    names: list[str | None] | list[str] | None,
    manifest: str | None,
) -> tuple[
    list[WorkItem],
    list[str | None] | list[str] | None,
    bool,
    bool,
    bool,
    list[str | None] | None,
]:
    """Resolve report targets/files/origins from CLI and/or a manifest."""
    cli_targets = parse_target_values(target_values)
    cli_files = parse_file_values(file_values)
    cli_origins = parse_origin_values(origin_values)
    manifest_names: list[str | None] | None = None
    sm_ids: list[str | None] | None = None

    if mode is CommandMode.DELETE:
        if cli_files or cli_origins:
            raise ParseError("delete does not support --file or --origin")
        if cli_targets:
            targets = cli_targets
        elif manifest:
            path = resolve_manifest_path(manifest)
            loaded = load_manifest(path)
            items = delete_targets_from_manifest(loaded, expected_kind=KIND_REPORT)
            return items, None, True, False, False, None
        else:
            targets = []
        items = build_work_items(mode, targets, [], dry_run=dry_run)
        return items, None, bool(targets), False, False, None

    if cli_targets or cli_files or cli_origins:
        targets = cli_targets
        files = cli_files
        origins = cli_origins
    elif manifest:
        path = resolve_manifest_path(manifest)
        loaded = load_manifest(path)
        loaded_items, manifest_names = work_items_from_manifest(
            loaded, expected_kind=KIND_REPORT
        )
        sm_ids = semantic_model_ids_from_manifest(loaded)
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

    items = build_work_items(mode, targets, files, origins=origins, dry_run=dry_run)
    effective_names: list[str | None] | list[str] | None = (
        names if names else manifest_names
    )
    return items, effective_names, bool(targets), bool(files), bool(origins), sm_ids


def _resolve_report_deploy_names(
    items: list[WorkItem],
    names: list[str | None] | list[str] | None,
) -> list[str]:
    from fabric_tools.report.definition import display_name_from_path

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
            resolved.append(display_name_from_path(item.file))
        else:
            resolved.append("")
    return resolved


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


def _resolve_paginated_report_inputs(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    file_values: list[str] | None,
    origin_values: list[str] | None,
    dry_run: bool,
    names: list[str | None] | list[str] | None,
    manifest: str | None,
) -> tuple[list[WorkItem], list[str | None] | list[str] | None, bool, bool, bool]:
    """Resolve paginated-report targets/files/origins from CLI and/or a manifest."""
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
                loaded, expected_kind=KIND_PAGINATED_REPORT
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
            loaded, expected_kind=KIND_PAGINATED_REPORT
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
    )
    effective_names: list[str | None] | list[str] | None = (
        names if names else manifest_names
    )
    return items, effective_names, bool(targets), bool(files), bool(origins)


def _resolve_paginated_report_deploy_names(
    items: list[WorkItem],
    names: list[str | None] | list[str] | None,
) -> list[str]:
    from fabric_tools.paginated_report.definition import display_name_from_path

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
            resolved.append(display_name_from_path(item.file))
        else:
            resolved.append("")
    return resolved


def _resolve_pipeline_inputs(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    file_values: list[str] | None,
    origin_values: list[str] | None,
    dry_run: bool,
    names: list[str | None] | list[str] | None,
    manifest: str | None,
) -> tuple[list[WorkItem], list[str | None] | list[str] | None, bool, bool, bool]:
    """Resolve pipeline targets/files/origins from CLI and/or a deployment manifest."""
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
            items = delete_targets_from_manifest(loaded, expected_kind=KIND_PIPELINE)
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
            loaded, expected_kind=KIND_PIPELINE
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

    items = build_work_items(mode, targets, files, origins=origins, dry_run=dry_run)
    effective_names: list[str | None] | list[str] | None = (
        names if names else manifest_names
    )
    return items, effective_names, bool(targets), bool(files), bool(origins)


def _resolve_pipeline_deploy_names(
    items: list[WorkItem],
    names: list[str | None] | list[str] | None,
) -> list[str]:
    from fabric_tools.pipeline.definition import display_name_from_path

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
            resolved.append(display_name_from_path(item.file))
        else:
            resolved.append("")
    return resolved


def _resolve_udf_inputs(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    file_values: list[str] | None,
    origin_values: list[str] | None,
    dry_run: bool,
    names: list[str | None] | list[str] | None,
    manifest: str | None,
) -> tuple[list[WorkItem], list[str | None] | list[str] | None, bool, bool, bool]:
    """Resolve UDF targets/files/origins from CLI and/or a deployment manifest."""
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
            items = delete_targets_from_manifest(loaded, expected_kind=KIND_UDF)
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
            loaded, expected_kind=KIND_UDF
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

    items = build_work_items(mode, targets, files, origins=origins, dry_run=dry_run)
    effective_names: list[str | None] | list[str] | None = (
        names if names else manifest_names
    )
    return items, effective_names, bool(targets), bool(files), bool(origins)


def _resolve_udf_deploy_names(
    items: list[WorkItem],
    names: list[str | None] | list[str] | None,
) -> list[str]:
    from fabric_tools.udf.definition import display_name_from_path

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
            resolved.append(display_name_from_path(item.file))
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

    items = build_work_items(mode, targets, files, origins=origins, dry_run=dry_run)
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
    semantic_model_ids: list[str | None] | None = None,
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
    sm_overrides = semantic_model_ids
    if op_results is not None and kind == KIND_REPORT:
        from_results = semantic_model_id_overrides_from_results(op_results)
        if any(from_results):
            sm_overrides = from_results
    try:
        built = manifest_from_work_items(
            items,
            kind=kind,
            display_names=display_names,
            item_id_overrides=overrides,
            semantic_model_id_overrides=sm_overrides,
        )
        path = save_manifest(manifest, built)
    except ManifestError as exc:
        typer.secho(f"manifest not written: {exc}", fg=FG_WARN, err=True)
        return
    typer.secho(f"Wrote manifest: {path}", fg=FG_OK)


def _print_op_results(results: list[OpResult]) -> None:
    for result in results:
        color = FG_OK if result.ok else FG_ERROR
        typer.secho(result.message, fg=color, err=not result.ok)


def _exit_from_op_results(results: list[OpResult]) -> None:
    if all(result.ok for result in results):
        raise typer.Exit(code=EXIT_OK)
    raise typer.Exit(code=EXIT_API)


def _print_compare_results(results: list[CompareResult]) -> None:
    for result in results:
        typer.secho(result.header, fg=FG_ID, bold=True)
        if result.error:
            typer.secho(result.error, fg=FG_ERROR, err=True)
            continue
        if result.identical:
            typer.secho("identical", fg=FG_OK)
        else:
            typer.secho("differences found", fg=FG_WARN)
            if result.diff_text:
                typer.echo(result.diff_text.rstrip())
        messages = getattr(result, "messages", None) or []
        for message in messages:
            typer.secho(message, fg=FG_WARN)
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
    from fabric_tools.notebook.definition import display_name_from_path

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

    from fabric_tools.path_setup import format_nuitka_orphan_exe_error

    orphan = format_nuitka_orphan_exe_error()
    if orphan:
        _exit_error(orphan)

    app(prog_name="fabric-tools")

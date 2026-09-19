"""Root Typer application and entrypoint."""

from __future__ import annotations

import typer
from typer.core import TyperGroup

from fabric_tools import __version__
from fabric_tools.cli.commands.dataflow import dataflow_app
from fabric_tools.cli.commands.dataflow_gen1 import dataflow_gen1_app
from fabric_tools.cli.commands.debug import debug_app
from fabric_tools.cli.commands.env import env_app
from fabric_tools.cli.commands.environment import environment_app
from fabric_tools.cli.commands.inspect import inspect_app
from fabric_tools.cli.commands.manifest import manifest_app
from fabric_tools.cli.commands.notebook import notebook_app
from fabric_tools.cli.commands.org_app import org_app_app
from fabric_tools.cli.commands.pack import pack_app
from fabric_tools.cli.commands.paginated_report import paginated_report_app
from fabric_tools.cli.commands.pipeline import pipeline_app
from fabric_tools.cli.commands.report import report_app
from fabric_tools.cli.commands.semantic_model import semantic_model_app
from fabric_tools.cli.commands.setup import setup_app
from fabric_tools.cli.commands.udf import udf_app
from fabric_tools.cli.commands.variable_library import variable_library_app
from fabric_tools.cli.lifecycle import flush_update_notice, start_bg_update_check
from fabric_tools.cli.options import HELP_CONTEXT
from fabric_tools.colours import apply_help_theme, print_banner
from fabric_tools.parsing import rejoin_spaced_csv_argv
from fabric_tools.sync.common import _exit_error


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
        "environment",
        "notebook",
        "org-app",
        "paginated-report",
        "pipeline",
        "report",
        "semantic-model",
        "udf",
        "variable-library",
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


app = typer.Typer(
    name="fabric-tools",
    help="CLI for working with Microsoft Fabric artifacts.",
    no_args_is_help=False,
    invoke_without_command=True,
    add_completion=False,
    cls=_BannerGroup,
    context_settings=HELP_CONTEXT,
)

app.add_typer(notebook_app, name="notebook", rich_help_panel="Fabric")
app.add_typer(dataflow_app, name="dataflow", rich_help_panel="Fabric")
app.add_typer(environment_app, name="environment", rich_help_panel="Fabric")
app.add_typer(org_app_app, name="org-app", rich_help_panel="Fabric")
app.add_typer(variable_library_app, name="variable-library", rich_help_panel="Fabric")
app.add_typer(semantic_model_app, name="semantic-model", rich_help_panel="Fabric")
app.add_typer(report_app, name="report", rich_help_panel="Fabric")
app.add_typer(paginated_report_app, name="paginated-report", rich_help_panel="Fabric")
app.add_typer(dataflow_gen1_app, name="dataflow-gen1", rich_help_panel="Fabric")
app.add_typer(pipeline_app, name="pipeline", rich_help_panel="Fabric")
app.add_typer(udf_app, name="udf", rich_help_panel="Fabric")
app.add_typer(inspect_app, name="inspect", rich_help_panel="Fabric")
app.add_typer(setup_app, name="setup", rich_help_panel="Local")
app.add_typer(env_app, name="env", rich_help_panel="Local")
app.add_typer(manifest_app, name="manifest", rich_help_panel="Local")
app.add_typer(pack_app, name="pack", rich_help_panel="Local")
app.add_typer(debug_app, name="debug", hidden=True)


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
            flush_update_notice(ctx)
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
                flush_update_notice(ctx)
                pause_if_double_clicked()
        else:
            typer.echo(ctx.get_help())
        raise typer.Exit()

    # Nested setup commands decide whether to start the background check.
    if ctx.invoked_subcommand != "setup":
        start_bg_update_check(ctx)


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

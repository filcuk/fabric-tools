"""Typer commands: env."""

from __future__ import annotations

import typer

from fabric_tools.cli.options import (
    HELP_CONTEXT,
)
from fabric_tools.colours import (
    FG_OK,
)
from fabric_tools.exit_codes import EXIT_OK
from fabric_tools.sync.common import (
    _exit_error,
)

env_app = typer.Typer(
    name="env",
    help="Manage environment variables.",
    no_args_is_help=True,
    context_settings=HELP_CONTEXT,
)


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

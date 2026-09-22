"""Typer commands: setup."""

from __future__ import annotations

import typer

from fabric_tools.cli.lifecycle import flush_update_notice, start_bg_update_check
from fabric_tools.cli.options import (
    HELP_CONTEXT,
    option_help,
)
from fabric_tools.colours import (
    FG_OK,
)
from fabric_tools.exit_codes import EXIT_API, EXIT_OK, EXIT_USER
from fabric_tools.sync.common import (
    _enforce_readonly_setup,
    _exit_error,
    _exit_user_abort,
)

setup_app = typer.Typer(
    name="setup",
    help="Manage fabric-tools installation and updates.",
    no_args_is_help=True,
    context_settings=HELP_CONTEXT,
)


@setup_app.callback()
def setup_main(ctx: typer.Context) -> None:
    """Manage the fabric-tools install (install / update / status / clean / uninstall)."""
    root = ctx.find_root()
    if ctx.invoked_subcommand == "update":
        root.meta["skip_bg_update"] = True
        # Still register close flush so skip is honored consistently.
        root.call_on_close(lambda: flush_update_notice(root))
        return
    start_bg_update_check(root)


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
        help=option_help(
            "Leave installed files in place; only remove PATH registration."
        ),
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
    from fabric_tools.setup_status import print_setup_status

    print_setup_status(exit_error=_exit_error)


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
        help=option_help("Skip confirmation prompts when downloading/installing."),
    ),
) -> None:
    """Check for a newer release, or download and install it."""
    from fabric_tools.status import busy, status_detail
    from fabric_tools.update_check import UpdateCheckError, check_for_update

    if check:
        try:
            with busy(status_detail("setup", "checking for updates")):
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
        _exit_user_abort(exc)
    except typer.Abort as exc:
        _exit_user_abort(exc)
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

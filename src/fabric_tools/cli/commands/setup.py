"""Typer commands: setup."""

from __future__ import annotations

import typer

from fabric_tools.cli.lifecycle import flush_update_notice, start_bg_update_check
from fabric_tools.cli.options import (
    HELP_CONTEXT,
)
from fabric_tools.colours import (
    FG_ID,
    FG_OK,
    STYLE_DIM,
    STYLE_ERROR,
    STYLE_OK,
    STYLE_WARN,
)
from fabric_tools.exit_codes import EXIT_API, EXIT_OK, EXIT_USER
from fabric_tools.sync.common import _enforce_readonly_setup, _exit_error, _exit_warn

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

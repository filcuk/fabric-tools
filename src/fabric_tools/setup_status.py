"""Presentation for ``fabric-tools setup status``."""

from __future__ import annotations

from typing import Any


def print_setup_status(*, exit_error: Any) -> None:
    """Print install status (inspect-get key/value layout) and exit successfully.

    *exit_error* is the shared CLI ``_exit_error`` callable (avoids importing
    sync helpers at module load).

    On a TTY, the full status block is drawn immediately while the GitHub
    update check runs; only the Version row is refreshed when it finishes.
    """
    import threading

    import httpx
    import typer
    from rich.console import Console, Group, RenderableType
    from rich.live import Live
    from rich.spinner import Spinner
    from rich.table import Table
    from rich.text import Text

    from fabric_tools.colours import (
        FG_ID,
        STYLE_DIM,
        STYLE_ERROR,
        STYLE_ID,
        STYLE_OK,
        STYLE_WARN,
    )
    from fabric_tools.exit_codes import EXIT_OK
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
        exit_error(str(exc))

    # Same key/value layout as inspect get: dim right-aligned keys, no colon,
    # two-space gap, left-aligned values.
    gap = "  "
    keys = ("Status", "Version", "Install", "PATH", "Cache")
    key_w = max(len(k) for k in keys)
    console = Console()

    state = str(status["install_state"])
    if state == "installed":
        state_style = STYLE_OK
    elif state == "incomplete":
        state_style = STYLE_WARN
    else:
        state_style = STYLE_ERROR

    cache_present = bool(status["cache_present"])
    version = str(status.get("version") or "").strip()

    def kv_line(key: str, value: str, *, value_style: str | None = None) -> Text:
        line = Text()
        line.append(f"{key:>{key_w}}", style=STYLE_DIM)
        line.append(gap)
        line.append(value, style=value_style)
        return line

    def version_renderable(
        version: str,
        *,
        latest: str | None = None,
        up_to_date: bool = False,
        note: str | None = None,
        checking: bool = False,
    ) -> RenderableType:
        if latest:
            return kv_line("Version", f"{version} < {latest}", value_style=STYLE_WARN)
        if up_to_date:
            return kv_line("Version", f"{version} (up to date)", value_style=STYLE_OK)
        if note:
            return kv_line("Version", f"{version} ({note})", value_style=STYLE_WARN)
        left = kv_line("Version", version, value_style=STYLE_OK)
        if not checking:
            return left
        grid = Table.grid(padding=(0, 1))
        grid.add_column()
        grid.add_column()
        grid.add_row(left, Spinner("dots", text="checking…", style=STYLE_DIM))
        return grid

    def path_renderable() -> Text:
        line = Text()
        line.append(f"{'PATH':>{key_w}}", style=STYLE_DIM)
        line.append(gap)
        if status["bin_dir_on_user_path"]:
            line.append("registered", style=STYLE_OK)
            which = str(status["which_fabric_tools"] or "")
            if which:
                line.append(f" → {which}")
            else:
                line.append(" (open a new terminal if ")
                line.append("fabric-tools", style=STYLE_ID)
                line.append(" is not found)")
        else:
            line.append("not registered", style=STYLE_ERROR)
        return line

    def status_block(version_part: RenderableType | None) -> RenderableType:
        parts: list[RenderableType] = [
            kv_line("Status", state, value_style=state_style),
        ]
        if version_part is not None:
            parts.append(version_part)
        parts.append(kv_line("Install", str(status["install_dir"])))
        parts.append(path_renderable())
        parts.append(
            kv_line(
                "Cache",
                "yes" if cache_present else "no",
                value_style=STYLE_WARN if cache_present else STYLE_OK,
            )
        )
        return Group(*parts)

    def print_cache_footer() -> None:
        if state != "installed" or not cache_present:
            return
        typer.echo()
        typer.secho(
            "Cache is only used for portable one-file runs. Clear with: ",
            dim=True,
            nl=False,
        )
        typer.secho("fabric-tools setup clean", fg=FG_ID)

    def version_from_result(
        result: UpdateCheckResult | None,
        *,
        note: str | None = None,
    ) -> RenderableType:
        if result is not None and result.update_available:
            return version_renderable(version, latest=result.latest)
        if result is not None:
            return version_renderable(version, up_to_date=True)
        if note:
            return version_renderable(version, note=note)
        return version_renderable(version)

    def check_failure_note(exc: BaseException) -> str:
        cause = exc.__cause__
        if isinstance(cause, httpx.TimeoutException) or "timeout" in str(exc).lower():
            return "update check timeout"
        return "update check failed"

    def run_version_check() -> tuple[UpdateCheckResult | None, str | None]:
        try:
            result = check_for_update(current=version)
        except UpdateCheckError as exc:
            return None, check_failure_note(exc)
        save_update_cache(result)
        return result, None

    if not version:
        console.print(status_block(None))
        print_cache_footer()
        raise typer.Exit(code=EXIT_OK)

    if is_update_check_disabled():
        console.print(status_block(version_from_result(None)))
        print_cache_footer()
        raise typer.Exit(code=EXIT_OK)

    if not console.is_terminal:
        result, note = run_version_check()
        console.print(status_block(version_from_result(result, note=note)))
        print_cache_footer()
        raise typer.Exit(code=EXIT_OK)

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
        status_block(version_renderable(version, checking=True)),
        console=console,
        refresh_per_second=12,
        transient=False,
    ) as live:
        while thread.is_alive():
            live.update(status_block(version_renderable(version, checking=True)))
            thread.join(timeout=0.05)
        result = holder["result"]
        note = str(holder["note"] or "") or None
        if isinstance(result, UpdateCheckResult):
            save_update_cache(result)
            live.update(status_block(version_from_result(result)))
        else:
            live.update(status_block(version_from_result(None, note=note)))

    print_cache_footer()
    raise typer.Exit(code=EXIT_OK)

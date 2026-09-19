"""Presentation for ``fabric-tools setup status``."""

from __future__ import annotations

from typing import Any


def print_setup_status(*, exit_error: Any) -> None:
    """Print install status (inspect-get key/value layout) and exit successfully.

    *exit_error* is the shared CLI ``_exit_error`` callable (avoids importing
    sync helpers at module load).
    """
    import threading

    import httpx
    import typer
    from rich.console import Console, RenderableType
    from rich.live import Live
    from rich.spinner import Spinner
    from rich.table import Table
    from rich.text import Text

    from fabric_tools.colours import FG_ID, STYLE_DIM, STYLE_ERROR, STYLE_OK, STYLE_WARN
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

    def print_row(key: str, value: str, *, value_style: str | None = None) -> None:
        line = Text()
        line.append(f"{key:>{key_w}}", style=STYLE_DIM)
        line.append(gap)
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
            line.append(gap)
            line.append(f"{version} < {latest}", style=STYLE_WARN)
            return line
        left = Text()
        left.append(f"{'Version':>{key_w}}", style=STYLE_DIM)
        left.append(gap)
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
    path_line.append(gap)
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

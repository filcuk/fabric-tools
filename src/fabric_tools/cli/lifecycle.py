"""CLI lifecycle helpers (update notice flush / background check)."""

from __future__ import annotations

import typer

from fabric_tools.colours import print_warn_panel


def flush_update_notice(ctx: typer.Context) -> None:
    """Print a background update notice on stderr, if one is ready."""
    if ctx.meta.get("skip_bg_update"):
        return
    from fabric_tools.update_check import consume_update_notice

    notice = consume_update_notice()
    if notice:
        print_warn_panel(notice)


def start_bg_update_check(ctx: typer.Context) -> None:
    """Register notice flush and start a once-per-day background check."""
    ctx.call_on_close(lambda: flush_update_notice(ctx))
    if ctx.meta.get("skip_bg_update"):
        return
    from fabric_tools.update_check import start_background_update_check

    start_background_update_check()

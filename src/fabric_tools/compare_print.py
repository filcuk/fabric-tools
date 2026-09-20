"""Aligned compare result summary printing."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fabric_tools.colours import (
    STYLE_DIM,
    STYLE_ERROR,
    STYLE_HEADER,
    STYLE_OK,
    STYLE_WARN,
    print_error_panel,
)

_COL_GAP = "  "
_HEADERS = ("REMOTE", "LOCAL", "STATUS", "TARGET")


def compare_status(result: Any) -> str:
    """Map a compare result to a STATUS column token."""
    if getattr(result, "error", None) or not getattr(result, "ok", False):
        return "error"
    if getattr(result, "identical", False):
        return "identical"
    return "differences"


def compare_status_style(status: str) -> str | None:
    """Rich style for a compare STATUS token."""
    if status == "identical":
        return STYLE_OK
    if status == "differences":
        return STYLE_WARN
    if status == "error":
        return STYLE_ERROR
    return None


def compare_row_cells(result: Any) -> tuple[str, str, str, str]:
    """Return ``(REMOTE, LOCAL, STATUS, TARGET)`` cells for one result."""
    return (
        getattr(result, "remote_name", None) or "-",
        getattr(result, "local_name", None) or "-",
        compare_status(result),
        getattr(result, "target_ref", None) or "-",
    )


def format_compare_table(results: Sequence[Any]) -> str:
    """Plain aligned compare table (header + rows) for tests."""
    if not results:
        return ""
    rows = [compare_row_cells(result) for result in results]
    widths = _column_widths(_HEADERS, rows)
    lines = [_COL_GAP.join(_pad_row(_HEADERS, widths))]
    for row in rows:
        lines.append(_COL_GAP.join(_pad_row(row, widths)))
    return "\n".join(lines)


def print_compare_results(results: Sequence[Any]) -> None:
    """Print compare summary table, then errors / notes / diffs."""
    import typer
    from rich.console import Console
    from rich.text import Text

    if not results:
        return

    rows = [compare_row_cells(result) for result in results]
    widths = _column_widths(_HEADERS, rows)
    console = Console()

    header_line = Text()
    for i, cell in enumerate(_pad_row(_HEADERS, widths)):
        if i:
            header_line.append(_COL_GAP)
        header_line.append(cell, style=STYLE_HEADER)
    console.print(header_line, soft_wrap=True)

    for row in rows:
        line = Text()
        padded = _pad_row(row, widths)
        for i, cell in enumerate(padded):
            if i:
                line.append(_COL_GAP)
            if i == 2:
                line.append(cell, style=compare_status_style(row[2]))
            elif i == 3:
                line.append(cell, style=STYLE_DIM)
            else:
                line.append(cell)
        console.print(line, soft_wrap=True)

    for result in results:
        error = getattr(result, "error", None)
        if error:
            print_error_panel(error)
        for message in getattr(result, "messages", None) or []:
            console.print(message, style=STYLE_DIM)
        if error:
            continue
        diff_text = getattr(result, "diff_text", None) or ""
        if not getattr(result, "identical", False) and diff_text:
            typer.echo(diff_text.rstrip())


def _column_widths(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
) -> list[int]:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    return widths


def _pad_row(cells: Sequence[str], widths: Sequence[int]) -> list[str]:
    return [f"{cell:<{widths[i]}}" for i, cell in enumerate(cells)]

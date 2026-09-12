"""CLI colour roles shared by Typer and Rich output.

See DESIGN.md for the role → colour contract. Prefer these constants over
ad-hoc ``typer.colors`` / Rich style strings.
"""

from __future__ import annotations

from dataclasses import dataclass

import typer

# Typer / Click foreground names (``typer.secho(..., fg=...)``).
FG_ERROR = typer.colors.RED
FG_WARN = typer.colors.YELLOW
FG_OK = typer.colors.GREEN
FG_ID = typer.colors.CYAN
FG_OPTION = typer.colors.MAGENTA

# Rich style strings (``Text.append(..., style=...)``).
STYLE_ERROR = "red"
STYLE_WARN = "yellow"
STYLE_OK = "green"
STYLE_ID = "cyan"
STYLE_OPTION = "magenta"
STYLE_DIM = "dim"
STYLE_HEADER = "bold blue"

# Typer Rich ``--help`` theme (long options + short aliases).
HELP_STYLE_OPTION = "magenta"
HELP_STYLE_SWITCH = "magenta"


@dataclass(frozen=True)
class PaletteRow:
    """One swatch row for ``debug color`` (and docs alignment)."""

    name: str
    """Colour label shown in column 1 (styled with ``style``)."""

    style: str | None
    """Rich style for the name, or ``None`` for primary/default text."""

    usage: str
    """Primary-text description of the role."""


PALETTE_ROWS: tuple[PaletteRow, ...] = (
    PaletteRow("red", STYLE_ERROR, "Error / failure"),
    PaletteRow("yellow", STYLE_WARN, "Warning / cancel / soft fail"),
    PaletteRow("green", STYLE_OK, "Success / affirmative"),
    PaletteRow("cyan", STYLE_ID, "Identifier / command hint"),
    PaletteRow("magenta", STYLE_OPTION, "Command option (help)"),
    PaletteRow("dim", STYLE_DIM, "Muted hint"),
    PaletteRow("dim", STYLE_DIM, "Secondary columns / keys"),
    PaletteRow("bold blue", STYLE_HEADER, "Table header"),
    PaletteRow("default", None, "Primary text"),
)


def env_status_style(status: str) -> str:
    """Rich style for an ``env list`` status token."""
    if status in {"enabled", "set"}:
        return STYLE_OK
    if status == "set (not enabled)":
        return STYLE_WARN
    return STYLE_DIM


def apply_help_theme() -> None:
    """Set Typer Rich help colours so long options and aliases are magenta."""
    from typer import rich_utils

    rich_utils.STYLE_OPTION = HELP_STYLE_OPTION
    rich_utils.STYLE_SWITCH = HELP_STYLE_SWITCH


def print_color_swatch() -> None:
    """Print a two-column palette demo (``fabric-tools debug color``)."""
    from rich.console import Console
    from rich.text import Text

    gap = "  "
    name_w = max(len(row.name) for row in PALETTE_ROWS)
    console = Console()
    for row in PALETTE_ROWS:
        line = Text()
        line.append(f"{row.name:<{name_w}}", style=row.style)
        line.append(gap)
        line.append(row.usage)
        console.print(line)

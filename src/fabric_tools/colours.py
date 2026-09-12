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
FG_OPTION_ALIAS = typer.colors.BRIGHT_MAGENTA

# Rich style strings (``Text.append(..., style=...)``).
STYLE_ERROR = "red"
STYLE_WARN = "yellow"
STYLE_METAVAR = "bright_yellow"
STYLE_OK = "green"
STYLE_ID = "cyan"
STYLE_OPTION = "magenta"
# Truecolor so aliases stay distinct from magenta on terminals where
# ANSI ``bright_magenta`` renders the same as ``magenta``.
STYLE_OPTION_ALIAS = "#ff9cf5"
STYLE_DIM = "dim"
STYLE_HEADER = "blue"
# Rich has no named ``teal``; truecolor keeps the Fabric panel distinct from cyan.
STYLE_PANEL_FABRIC = "#8acfb3"
# Root help ASCII banner: ``FABRIC`` / ``-`` / ``TOOLS``.
STYLE_BANNER_FABRIC = STYLE_PANEL_FABRIC
STYLE_BANNER_SEP = "#1d8e7a"
STYLE_BANNER_TOOLS = "#1d8e7a"

# Column splits for the figlet banner (``FABRIC`` | ``-`` gap | ``TOOLS``).
_BANNER_FABRIC_END = 25
_BANNER_TOOLS_START = 30
_BANNER_LINES = (
    " _____     _       _         _____         _     ",
    "|   __|___| |_ ___|_|___ ___|_   _|___ ___| |___ ",
    "|   __| .'| . |  _| |  _|___| | | | . | . | |_ -|",
    "|__|  |__,|___|_| |_|___|     |_| |___|___|_|___|",
)

# Typer Rich ``--help`` theme (long options vs short aliases).
HELP_STYLE_OPTION = STYLE_OPTION
HELP_STYLE_SWITCH = STYLE_OPTION_ALIAS
HELP_STYLE_METAVAR = STYLE_METAVAR
HELP_STYLE_USAGE = STYLE_DIM
HELP_STYLE_USAGE_COMMAND = ""
HELP_STYLE_COMMAND = STYLE_ID
HELP_STYLE_FABRIC = STYLE_PANEL_FABRIC
HELP_STYLE_POWERBI = STYLE_WARN
HELP_PANEL_FABRIC = "Fabric"

# Highlighter patterns: long options before short, and short must not match
# inside ``--dry-run`` / ``--target`` (Typer's defaults style both as switch).
# Usage-line tokens: command path cyan, [OPTIONS] magenta, placeholders yellow.
# Product names in help prose: Fabric teal, Power BI yellow.
_HELP_OPTION_HIGHLIGHTS = [
    r"(?P<option>\-\-[\w\-]+)",
    r"(?P<switch>(?<![\w\-])\-[a-zA-Z0-9]+)(?![\w\-])",
    r"(?P<metavar>\<[^\>]+\>)",
    r"(?P<usage>Usage: )(?P<command>[\w-]+(?:\s+[\w-]+)*)",
    r"(?P<option>\[OPTIONS\])",
    r"(?P<metavar>\[ARGS\]\.\.\.)",
    r"(?P<command>\bCOMMAND\b)",
    r"(?P<metavar>\b(?!OPTIONS\b|ARGS\b|COMMAND\b|BI\b)[A-Z][A-Z0-9_]+\b)",
    r"(?P<metavar>\[(?!OPTIONS\b|ARGS\b)[A-Z][^\]]*\])",
    r"(?P<powerbi>Power BI)",
    r"(?P<fabric>\bFabric\b)",
]
_HELP_NEGATIVE_HIGHLIGHTS = [
    r"(?P<negative_option>\-\-[\w\-]+)",
    r"(?P<negative_switch>(?<![\w\-])\-[a-zA-Z0-9]+)(?![\w\-])",
]


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
    PaletteRow("yellow", STYLE_WARN, "Warning / cancel / soft fail; Power BI in help"),
    PaletteRow(
        "bright yellow",
        STYLE_METAVAR,
        "Help metavar (e.g. <PATH>, [ARGS]...)",
    ),
    PaletteRow("green", STYLE_OK, "Success / affirmative"),
    PaletteRow(
        "cyan",
        STYLE_ID,
        "Identifier / command hint; Usage command path / COMMAND",
    ),
    PaletteRow("magenta", STYLE_OPTION, "Command option — long (help); [OPTIONS]"),
    PaletteRow(
        "bright magenta",
        STYLE_OPTION_ALIAS,
        "Command option — alias (help)",
    ),
    PaletteRow(
        "dim",
        STYLE_DIM,
        "Muted hint; secondary columns / keys; root help subtitle; Usage: label",
    ),
    PaletteRow("blue", STYLE_HEADER, "Table header"),
    PaletteRow(
        "teal",
        STYLE_PANEL_FABRIC,
        "Root help — Fabric panel; banner FABRIC; Fabric in help",
    ),
    PaletteRow("#1d8e7a", STYLE_BANNER_TOOLS, "Root help — banner - / TOOLS"),
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
    """Set Typer Rich help colours and fix option/alias highlighting."""
    from rich.console import Console
    from rich.theme import Theme
    from typer import rich_utils

    rich_utils.STYLE_OPTION = HELP_STYLE_OPTION
    rich_utils.STYLE_SWITCH = HELP_STYLE_SWITCH
    rich_utils.STYLE_METAVAR = HELP_STYLE_METAVAR
    rich_utils.STYLE_USAGE = HELP_STYLE_USAGE
    rich_utils.STYLE_USAGE_COMMAND = HELP_STYLE_USAGE_COMMAND
    rich_utils.OptionHighlighter.highlights = list(_HELP_OPTION_HIGHLIGHTS)
    rich_utils.NegativeOptionHighlighter.highlights = list(
        _HELP_NEGATIVE_HIGHLIGHTS
    )
    # Module-level instances are built at import with the old patterns.
    rich_utils.highlighter = rich_utils.OptionHighlighter()
    rich_utils.negative_highlighter = rich_utils.NegativeOptionHighlighter()

    if getattr(rich_utils, "_fabric_tools_help_theme_patched", False):
        return

    def _get_rich_console(stderr: bool = False) -> Console:
        return Console(
            theme=Theme(
                {
                    "option": rich_utils.STYLE_OPTION,
                    "switch": rich_utils.STYLE_SWITCH,
                    "negative_option": rich_utils.STYLE_NEGATIVE_OPTION,
                    "negative_switch": rich_utils.STYLE_NEGATIVE_SWITCH,
                    "metavar": rich_utils.STYLE_METAVAR,
                    "metavar_sep": rich_utils.STYLE_METAVAR_SEPARATOR,
                    "usage": rich_utils.STYLE_USAGE,
                    "command": HELP_STYLE_COMMAND,
                    "fabric": HELP_STYLE_FABRIC,
                    "powerbi": HELP_STYLE_POWERBI,
                },
            ),
            highlighter=rich_utils.highlighter,
            color_system=rich_utils.COLOR_SYSTEM,
            force_terminal=rich_utils.FORCE_TERMINAL,
            width=rich_utils.MAX_WIDTH,
            stderr=stderr,
        )

    rich_utils._get_rich_console = _get_rich_console  # type: ignore[assignment]

    # Teal border + title for the root ``Fabric`` commands panel only.
    # Rich Panel uses ``border_style`` for both frame and title.
    original = rich_utils._print_commands_panel

    def _print_commands_panel(*, name: str, **kwargs) -> None:
        previous = rich_utils.STYLE_COMMANDS_PANEL_BORDER
        if name == HELP_PANEL_FABRIC:
            rich_utils.STYLE_COMMANDS_PANEL_BORDER = STYLE_PANEL_FABRIC
        try:
            original(name=name, **kwargs)
        finally:
            rich_utils.STYLE_COMMANDS_PANEL_BORDER = previous

    rich_utils._print_commands_panel = _print_commands_panel  # type: ignore[assignment]
    rich_utils._fabric_tools_help_theme_patched = True


def print_banner(*, subtitle: str | None = None) -> None:
    """Print the root-help ASCII banner with FABRIC / - / TOOLS colours."""
    from rich.console import Console
    from rich.text import Text

    console = Console()
    for raw in _BANNER_LINES:
        line = Text()
        line.append(raw[:_BANNER_FABRIC_END], style=STYLE_BANNER_FABRIC)
        line.append(
            raw[_BANNER_FABRIC_END:_BANNER_TOOLS_START],
            style=STYLE_BANNER_SEP,
        )
        line.append(raw[_BANNER_TOOLS_START:], style=STYLE_BANNER_TOOLS)
        console.print(line)
    if subtitle:
        console.print(subtitle, style=STYLE_DIM)


def print_color_swatch() -> None:
    """Print a two-column palette demo (``fabric-tools debug color``)."""
    from rich.console import Console
    from rich.text import Text

    gap = "  "
    name_w = max(len(row.name) for row in PALETTE_ROWS)
    console = Console()
    for row in PALETTE_ROWS:
        line = Text()
        line.append(f"{row.name:>{name_w}}", style=row.style)
        line.append(gap)
        line.append(row.usage)
        console.print(line)

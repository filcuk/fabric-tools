"""CLI colour roles shared by Typer and Rich output.

See DESIGN.md for the role → colour contract. Prefer these constants over
ad-hoc ``typer.colors`` / Rich style strings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from rich.text import Text

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
    " _____     _       _      _____         _     ",
    "|   __|___| |_ ___|_|___ |_   _|___ ___| |___ ",
    "|   __| .'| . |  _| |  _|  | | | . | . | |_ -|",
    "|__|  |__,|___|_| |_|___|  |_| |___|___|_|___|",
)

# Typer Rich ``--help`` theme (long options vs short aliases).
HELP_STYLE_OPTION = STYLE_OPTION
HELP_STYLE_SWITCH = STYLE_OPTION_ALIAS
HELP_STYLE_METAVAR = STYLE_METAVAR
HELP_STYLE_REQUIRED_SHORT = STYLE_ERROR
HELP_STYLE_REQUIRED_LONG = "dim red"
HELP_STYLE_USAGE = STYLE_DIM
HELP_STYLE_USAGE_COMMAND = ""
HELP_STYLE_COMMAND = STYLE_ID
HELP_STYLE_FABRIC = STYLE_PANEL_FABRIC
HELP_STYLE_POWERBI = STYLE_METAVAR
HELP_PANEL_FABRIC = "Fabric"

# Highlighter patterns: long options before short, and short must not match
# inside ``--dry-run`` / ``--target`` (Typer's defaults style both as switch).
# Usage-line tokens: command path cyan, [OPTIONS] magenta, placeholders yellow.
# Do not match bare ALL-CAPS prose (GUID, OK, XMLA, …) — the Options metavar
# column is styled by Typer directly; prose yellow only via Rich markup tags.
# Product names in help prose: Fabric teal, Power BI bright yellow.
_HELP_OPTION_HIGHLIGHTS = [
    r"(?P<option>\-\-[\w\-]+)",
    r"(?P<switch>(?<![\w\-])\-[a-zA-Z0-9]+)(?![\w\-])",
    r"(?P<metavar>\<[^\>]+\>)",
    r"(?P<usage>Usage: )(?P<command>[\w-]+(?:\s+[\w-]+)*)",
    r"(?P<option>\[OPTIONS\])",
    r"(?P<metavar>\[ARGS\]\.\.\.)",
    r"(?P<command>\bCOMMAND\b)",
    r"(?P<powerbi>Power BI)",
    r"(?P<fabric>\bFabric\b)",
]
_HELP_NEGATIVE_HIGHLIGHTS = [
    r"(?P<negative_option>\-\-[\w\-]+)",
    r"(?P<negative_switch>(?<![\w\-])\-[a-zA-Z0-9]+)(?![\w\-])",
]

# Command / subcommand words that may follow ``fabric-tools`` in a suggested
# invocation. Kept explicit so prose like "fabric-tools is not found" does not
# turn cyan past the program name; tests assert it covers every registered name.
CLI_COMMAND_WORDS: frozenset[str] = frozenset(
    {
        "add",
        "clean",
        "color",
        "compare",
        "dataflow",
        "dataflow-gen1",
        "debug",
        "delete",
        "deploy",
        "download",
        "env",
        "environment",
        "get",
        "inspect",
        "install",
        "item",
        "list",
        "manifest",
        "member",
        "member-add",
        "member-remove",
        "move",
        "notebook",
        "org-app",
        "pack",
        "paginated-report",
        "pipeline",
        "remove",
        "report",
        "role",
        "semantic-model",
        "set",
        "setup",
        "status",
        "udf",
        "uninstall",
        "unset",
        "update",
        "variable-library",
        "workspace",
        "xmla-roles",
    }
)
_CLI_WORD_ALT = "|".join(
    re.escape(word) for word in sorted(CLI_COMMAND_WORDS, key=len, reverse=True)
)

# Error / Warning / aside prose: whole-match regex → concrete style, so panels
# render correctly on a plain Console (no help theme needed).
_PROSE_HIGHLIGHTS: tuple[tuple[str, str], ...] = (
    (
        rf"(?<![\w\-])fabric-tools(?:\s+(?:{_CLI_WORD_ALT}))*(?![\w\-])",
        STYLE_ID,
    ),
    (r"(?<![\w\-])\-\-[a-zA-Z0-9][\w\-]*", STYLE_OPTION),
    (r"(?<![\w\-])\-[a-zA-Z][a-zA-Z0-9]*(?![\w\-])", STYLE_OPTION_ALIAS),
    (r"<[^<>\s][^<>]*>", STYLE_METAVAR),
)

# Click / Typer quote names with ``{name!r}``: ``No such command 'x'.``,
# ``Did you mean 'a', 'b'?``, ``Missing option '--role' / '-r'.``
_USAGE_COMMAND_CLAUSE_RE = re.compile(
    r"(No such command |Did you mean )((?:'[\w\-]+'(?:, )?)+)"
)
_QUOTED_WORD_RE = re.compile(r"'([\w\-]+)'")
_QUOTED_OPTION_RE = re.compile(r"'(\-{1,2}[a-zA-Z0-9][\w\-]*)'")


def highlight_cli_prose(message: str | Text) -> Text:
    """Style options, aliases, ``fabric-tools …`` invocations, and ``<metavars>``.

    Plain strings are highlighted. A Rich ``Text`` is returned unchanged so
    callers that already styled their tokens keep their spans.
    """
    from rich.text import Text

    if isinstance(message, Text):
        return message
    text = Text(message)
    for pattern, style in _PROSE_HIGHLIGHTS:
        text.highlight_regex(pattern, style)
    return text


def echo_cli_hint(message: str) -> None:
    """Print a primary-text stdout line with ``highlight_cli_prose`` styling."""
    from rich.console import Console

    Console(soft_wrap=True).print(highlight_cli_prose(message))


def render_cli_prose(message: str, *, stderr: bool = False) -> str:
    """Return *message* with ``highlight_cli_prose`` styling as an ANSI string.

    For APIs that print raw text (``typer.confirm``). Colour follows the target
    stream: plain text when it is not a terminal or ``NO_COLOR`` is set.
    """
    from rich.console import Console

    console = Console(stderr=stderr, soft_wrap=True)
    with console.capture() as capture:
        console.print(highlight_cli_prose(message), end="")
    return capture.get()


def format_usage_error_message(message: str) -> Text:
    """Unquote Click command/option names and highlight them for the Error panel."""
    commands: list[str] = []

    def _unquote_clause(match: re.Match[str]) -> str:
        names = _QUOTED_WORD_RE.findall(match.group(2))
        commands.extend(name for name in names if not name.startswith("-"))
        return match.group(1) + _QUOTED_WORD_RE.sub(r"\1", match.group(2))

    plain = _USAGE_COMMAND_CLAUSE_RE.sub(_unquote_clause, message)
    plain = _QUOTED_OPTION_RE.sub(r"\1", plain)
    text = highlight_cli_prose(plain)
    for name in dict.fromkeys(commands):
        text.highlight_regex(rf"(?<![\w\-]){re.escape(name)}(?![\w\-])", STYLE_ID)
    return text


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
    PaletteRow("red", STYLE_ERROR, "Error / failure; help required marker *"),
    PaletteRow(
        "dim red",
        HELP_STYLE_REQUIRED_LONG,
        "Help required marker [required]",
    ),
    PaletteRow("yellow", STYLE_WARN, "Warning / cancel / soft fail"),
    PaletteRow(
        "bright yellow",
        STYLE_METAVAR,
        "Help metavar column / <placeholders>; Power BI; optional [metavar] prose",
    ),
    PaletteRow("green", STYLE_OK, "Success / affirmative"),
    PaletteRow(
        "cyan",
        STYLE_ID,
        "Identifier / command hint; Usage command path / COMMAND; created GUIDs; "
        "usage-error command names",
    ),
    PaletteRow(
        "magenta",
        STYLE_OPTION,
        "Command option — long (help, errors, warnings); [OPTIONS]",
    ),
    PaletteRow(
        "bright magenta",
        STYLE_OPTION_ALIAS,
        "Command option — alias (help, errors, warnings)",
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
    rich_utils.STYLE_REQUIRED_SHORT = HELP_STYLE_REQUIRED_SHORT
    rich_utils.STYLE_REQUIRED_LONG = HELP_STYLE_REQUIRED_LONG
    rich_utils.STYLE_USAGE = HELP_STYLE_USAGE
    rich_utils.STYLE_USAGE_COMMAND = HELP_STYLE_USAGE_COMMAND
    rich_utils.OptionHighlighter.highlights = list(_HELP_OPTION_HIGHLIGHTS)
    rich_utils.NegativeOptionHighlighter.highlights = list(_HELP_NEGATIVE_HIGHLIGHTS)
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

    # Drop Typer's ``Try '… --help' for help.`` line on usage errors. Usage +
    # the Error panel (which already carries Did-you-mean / option hints) are
    # enough; the Try line is redundant and mismatched our colour contract.
    def _rich_format_error(self) -> None:
        from rich.panel import Panel

        if self.__class__.__name__ == "NoArgsIsHelpError":
            return

        console = rich_utils._get_rich_console(stderr=True)
        ctx = getattr(self, "ctx", None)
        if ctx is not None:
            console.print(ctx.get_usage())
        console.print(
            Panel(
                format_usage_error_message(self.format_message()),
                border_style=rich_utils.STYLE_ERRORS_PANEL_BORDER,
                title=rich_utils.ERRORS_PANEL_TITLE,
                title_align=rich_utils.ALIGN_ERRORS_PANEL,
            )
        )

    rich_utils.rich_format_error = _rich_format_error  # type: ignore[assignment]
    rich_utils._fabric_tools_help_theme_patched = True


def _panel_body(message: str | Text, default: str) -> Text:
    from rich.text import Text

    if isinstance(message, Text):
        return message if message.plain.strip() else Text(default)
    return highlight_cli_prose((message or "").strip() or default)


def print_error_panel(message: str | Text) -> None:
    """Print a Typer-style Error panel on stderr (red border, title Error)."""
    from rich.console import Console
    from rich.panel import Panel

    from fabric_tools.status import clear

    clear()
    Console(stderr=True).print(
        Panel(
            _panel_body(message, "Operation failed."),
            border_style=STYLE_ERROR,
            title="Error",
            title_align="left",
        )
    )


def print_warn_panel(message: str | Text) -> None:
    """Print a Warning panel on stderr (yellow border, title Warning)."""
    from rich.console import Console
    from rich.panel import Panel

    from fabric_tools.confirm import CONFIRM_ABORT_MESSAGE
    from fabric_tools.status import clear

    clear()
    Console(stderr=True).print(
        Panel(
            _panel_body(message, CONFIRM_ABORT_MESSAGE),
            border_style=STYLE_WARN,
            title="Warning",
            title_align="left",
        )
    )


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

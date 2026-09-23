"""Tests for CLI colour roles, help theme, and debug color swatch."""

from __future__ import annotations

from typer.testing import CliRunner

from fabric_tools import colours
from fabric_tools.cli import app
from fabric_tools.exit_codes import EXIT_OK


def test_style_header_is_blue() -> None:
    assert colours.STYLE_HEADER == "blue"


def test_env_status_style_mapping() -> None:
    assert colours.env_status_style("enabled") == colours.STYLE_OK
    assert colours.env_status_style("set") == colours.STYLE_OK
    assert colours.env_status_style("set (not enabled)") == colours.STYLE_WARN
    assert colours.env_status_style("unset") == colours.STYLE_DIM
    assert colours.env_status_style("off") == colours.STYLE_DIM
    assert colours.env_status_style("not configured") == colours.STYLE_DIM


def test_apply_help_theme_sets_option_and_switch_styles() -> None:
    from typer import rich_utils

    colours.apply_help_theme()
    assert rich_utils.STYLE_OPTION == colours.HELP_STYLE_OPTION
    assert rich_utils.STYLE_SWITCH == colours.HELP_STYLE_SWITCH
    assert rich_utils.STYLE_METAVAR == colours.HELP_STYLE_METAVAR
    assert rich_utils.STYLE_REQUIRED_SHORT == colours.HELP_STYLE_REQUIRED_SHORT
    assert rich_utils.STYLE_REQUIRED_LONG == colours.HELP_STYLE_REQUIRED_LONG
    assert rich_utils.STYLE_USAGE == colours.HELP_STYLE_USAGE
    assert colours.HELP_STYLE_OPTION == "magenta"
    assert colours.HELP_STYLE_SWITCH == colours.STYLE_OPTION_ALIAS
    assert colours.HELP_STYLE_METAVAR == "bright_yellow"
    assert colours.HELP_STYLE_REQUIRED_SHORT == colours.STYLE_ERROR
    assert colours.HELP_STYLE_REQUIRED_LONG == "dim red"


def test_usage_error_omits_try_help_hint() -> None:
    """Unknown-command errors keep Usage + Error panel; no Try … --help line."""
    result = CliRunner().invoke(app, ["report", "dowload"])
    assert result.exit_code != EXIT_OK
    combined = (result.stdout or "") + (result.stderr or "")
    assert "Usage:" in combined
    assert "No such command" in combined
    assert "Did you mean" in combined
    assert "Try " not in combined
    assert "for help." not in combined

    root = CliRunner().invoke(app, ["not-a-command"])
    assert root.exit_code != EXIT_OK
    root_text = (root.stdout or "") + (root.stderr or "")
    assert "Usage:" in root_text
    assert "No such command" in root_text
    assert "Try " not in root_text
    assert "for help." not in root_text

    option = CliRunner().invoke(app, ["notebook", "deploy", "--bogus"])
    assert option.exit_code != EXIT_OK
    option_text = (option.stdout or "") + (option.stderr or "")
    assert "Usage:" in option_text
    assert "No such option" in option_text
    assert "Try " not in option_text
    assert "for help." not in option_text


def _styled_tokens(text) -> dict[str, str]:
    return {text.plain[s.start : s.end]: str(s.style) for s in text.spans}


def test_usage_error_unquotes_and_colours_command_suggestion() -> None:
    text = colours.format_usage_error_message(
        "No such command 'dowload'. Did you mean 'download'?"
    )
    assert text.plain == "No such command dowload. Did you mean download?"
    tokens = _styled_tokens(text)
    assert tokens["dowload"] == colours.STYLE_ID
    assert tokens["download"] == colours.STYLE_ID


def test_usage_error_unquotes_multiple_suggestions_and_options() -> None:
    text = colours.format_usage_error_message(
        "No such command 'depoly'. Did you mean 'deploy', 'delete'?"
    )
    assert "'" not in text.plain
    tokens = _styled_tokens(text)
    assert tokens["deploy"] == colours.STYLE_ID
    assert tokens["delete"] == colours.STYLE_ID

    missing = colours.format_usage_error_message("Missing option '--role' / '-r'.")
    assert missing.plain == "Missing option --role / -r."
    tokens = _styled_tokens(missing)
    assert tokens["--role"] == colours.STYLE_OPTION
    assert tokens["-r"] == colours.STYLE_OPTION_ALIAS


def test_usage_error_keeps_quoted_values() -> None:
    text = colours.format_usage_error_message(
        "Invalid value for '--target' / '-t': 'abc' is not valid."
    )
    assert text.plain == "Invalid value for --target / -t: 'abc' is not valid."


def test_cli_usage_error_panel_has_no_quoted_names() -> None:
    result = CliRunner().invoke(app, ["report", "dowload"])
    combined = (result.stdout or "") + (result.stderr or "")
    assert "No such command dowload" in combined
    assert "Did you mean download?" in combined
    assert "'download'" not in combined


def test_highlight_cli_prose_styles_options_aliases_and_invocations() -> None:
    text = colours.highlight_cli_prose(
        "download requires a local --target path (-t). "
        "Run: fabric-tools setup update. See <workspaceId>."
    )
    tokens = _styled_tokens(text)
    assert tokens["--target"] == colours.STYLE_OPTION
    assert tokens["-t"] == colours.STYLE_OPTION_ALIAS
    assert tokens["fabric-tools setup update"] == colours.STYLE_ID
    assert tokens["<workspaceId>"] == colours.STYLE_METAVAR
    assert "download" not in tokens


def test_highlight_cli_prose_skips_guids_paths_and_prose() -> None:
    text = colours.highlight_cli_prose(
        "fabric-tools is not found; item 1b396529-da9c-453a-bb58-7b2ab95117e2 "
        r"in temp\my-report -> done; non-TTY"
    )
    tokens = _styled_tokens(text)
    assert tokens == {"fabric-tools": colours.STYLE_ID}


def test_highlight_cli_prose_leaves_rich_text_unchanged() -> None:
    from rich.text import Text

    body = Text("Use ")
    body.append("--independent", style="bold")
    assert colours.highlight_cli_prose(body) is body


def test_cli_command_words_cover_registered_commands() -> None:
    import typer.main

    def walk(group) -> set[str]:
        names: set[str] = set()
        for name, cmd in getattr(group, "commands", {}).items():
            names.add(name)
            names |= walk(cmd)
        return names

    registered = walk(typer.main.get_command(app))
    assert registered <= colours.CLI_COMMAND_WORDS


def test_joined_model_aside_uses_option_and_alias_colours() -> None:
    from fabric_tools.report.ops import joined_model_aside_text

    tokens = _styled_tokens(joined_model_aside_text(provisional="Joined model."))
    assert tokens["--independent"] == colours.STYLE_OPTION
    assert tokens["-i"] == colours.STYLE_OPTION_ALIAS


def test_echo_cli_hint_prints_plain_text(capsys) -> None:
    colours.echo_cli_hint("Open a new terminal, then run: fabric-tools --help")
    assert capsys.readouterr().out == (
        "Open a new terminal, then run: fabric-tools --help\n"
    )


def test_render_cli_prose_plain_when_not_a_terminal() -> None:
    message = "Pipeline-only (use --include-schedules / -i to sync schedules)."
    assert colours.render_cli_prose(message) == message


def test_render_cli_prose_emits_ansi_on_colour_terminal(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("TERM", "xterm-256color")
    out = colours.render_cli_prose("use --include-schedules / -i")
    assert "\x1b[35m--include-schedules\x1b[0m" in out
    # Alias colour depth depends on detected colour system; only require styling.
    assert "m-i\x1b[0m" in out
    assert "\x1b[35m-i" not in out


def test_print_error_panel_highlights_options(capsys, monkeypatch) -> None:
    from rich.console import Console

    captured: list[object] = []

    class _Recorder(Console):
        def print(self, *objects, **kwargs) -> None:  # type: ignore[override]
            captured.extend(objects)

    monkeypatch.setattr("rich.console.Console", _Recorder)
    colours.print_error_panel("download requires a local --target path")
    panel = captured[0]
    tokens = _styled_tokens(panel.renderable)
    assert tokens["--target"] == colours.STYLE_OPTION


def _span_styles_covering(text, start: int, end: int) -> set[str]:
    """Return Rich style names covering ``text.plain[start:end]``."""
    styles: set[str] = set()
    for span_start, span_end, style in text.spans:
        if span_end <= start or span_start >= end:
            continue
        styles.add(str(style))
    return styles


def test_help_highlighter_skips_all_caps_prose_but_styles_placeholders() -> None:
    from rich.text import Text
    from typer import rich_utils

    colours.apply_help_theme()
    prose = "workspace:artifact GUID. spaces after commas OK. XMLA RLS UPN"
    highlighted = rich_utils.highlighter(Text(prose))
    for token in ("GUID", "OK", "XMLA", "RLS", "UPN"):
        idx = prose.index(token)
        styles = _span_styles_covering(highlighted, idx, idx + len(token))
        assert "metavar" not in styles, f"{token} should not be metavar-styled"

    placeholder = rich_utils.highlighter(Text("get -t <workspaceId>"))
    start = placeholder.plain.index("<workspaceId>")
    styles = _span_styles_covering(placeholder, start, start + len("<workspaceId>"))
    assert "metavar" in styles

    branded = rich_utils.highlighter(Text("Fabric and Power BI items"))
    fabric_i = branded.plain.index("Fabric")
    assert "fabric" in _span_styles_covering(
        branded, fabric_i, fabric_i + len("Fabric")
    )
    pbi_i = branded.plain.index("Power BI")
    assert "powerbi" in _span_styles_covering(branded, pbi_i, pbi_i + len("Power BI"))


def test_palette_rows_cover_core_roles() -> None:
    by_name = {row.name: row for row in colours.PALETTE_ROWS}
    assert by_name["red"].usage.startswith("Error / failure")
    assert by_name["dim red"].style == colours.HELP_STYLE_REQUIRED_LONG
    assert by_name["yellow"].usage.startswith("Warning")
    assert by_name["green"].usage.startswith("Success")
    assert by_name["cyan"].style == colours.STYLE_ID
    assert by_name["magenta"].style == colours.STYLE_OPTION
    assert by_name["bright magenta"].style == colours.STYLE_OPTION_ALIAS
    assert by_name["dim"].style == colours.STYLE_DIM
    assert by_name["blue"].style == colours.STYLE_HEADER
    assert by_name["bright blue"].style == colours.STYLE_INFO
    assert by_name["bright blue"].usage.startswith("Info")
    assert by_name["default"].style is None


def test_debug_color_emits_palette_labels() -> None:
    result = CliRunner().invoke(app, ["debug", "color"])
    assert result.exit_code == EXIT_OK
    for row in colours.PALETTE_ROWS:
        assert row.name in result.stdout
        # Rich may wrap long usage cells; match a stable leading phrase.
        assert row.usage.split(";")[0] in result.stdout


def test_debug_banner_emits_all_panel_titles() -> None:
    result = CliRunner().invoke(app, ["debug", "banner"])
    assert result.exit_code == EXIT_OK
    err = result.stderr or ""
    for title, body in (
        ("Error", "Example error."),
        ("Warning", "Example warning."),
        ("Info", "Example info."),
        ("Success", "Example success."),
    ):
        assert title in err
        assert body in err


def test_debug_hidden_from_root_help() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == EXIT_OK
    # Hidden group: not listed among root commands (avoid matching incidental text).
    assert "\ndebug " not in result.stdout
    assert " debug " not in result.stdout


def test_print_error_panel_uses_error_title(capsys) -> None:
    colours.print_error_panel("Refusing setup update: FABRIC_TOOLS_READONLY is set.")
    err = capsys.readouterr().err
    assert "Error" in err
    assert "FABRIC_TOOLS_READONLY" in err


def test_print_warn_panel_uses_warning_title(capsys) -> None:
    colours.print_warn_panel("Aborted by user.")
    err = capsys.readouterr().err
    assert "Warning" in err
    assert "Aborted by user." in err


def test_print_warn_panel_empty_defaults_to_aborted(capsys) -> None:
    colours.print_warn_panel("  ")
    err = capsys.readouterr().err
    assert "Warning" in err
    assert "Aborted by user." in err


def test_print_info_panel_uses_info_title(capsys) -> None:
    colours.print_info_panel("After deploy, configure credentials in the service.")
    err = capsys.readouterr().err
    assert "Info" in err
    assert "configure credentials" in err


def test_print_info_panel_empty_defaults_to_info(capsys) -> None:
    colours.print_info_panel("  ")
    err = capsys.readouterr().err
    assert "Info" in err
    assert "Info." in err


def test_print_success_panel_uses_success_title(capsys) -> None:
    colours.print_success_panel("Installed fabric-tools to the user PATH.")
    err = capsys.readouterr().err
    assert "Success" in err
    assert "Installed fabric-tools" in err


def test_print_success_panel_empty_defaults_to_success(capsys) -> None:
    colours.print_success_panel("")
    err = capsys.readouterr().err
    assert "Success" in err
    assert "Success." in err


def test_print_info_panel_highlights_options(capsys, monkeypatch) -> None:
    from rich.console import Console

    captured: list[object] = []

    class _Recorder(Console):
        def print(self, *objects, **kwargs) -> None:  # type: ignore[override]
            captured.extend(objects)

    monkeypatch.setattr("rich.console.Console", _Recorder)
    colours.print_info_panel("Tip: pass --filter / -f with workspace:*")
    panel = captured[0]
    tokens = _styled_tokens(panel.renderable)
    assert tokens["--filter"] == colours.STYLE_OPTION
    assert tokens["-f"] == colours.STYLE_OPTION_ALIAS


def test_print_panel_swatch_prints_all_titles(capsys) -> None:
    colours.print_panel_swatch()
    err = capsys.readouterr().err
    assert "Error" in err
    assert "Example error." in err
    assert "Warning" in err
    assert "Example warning." in err
    assert "Info" in err
    assert "Example info." in err
    assert "Success" in err
    assert "Example success." in err


def test_print_compare_results_prints_note_messages(capsys) -> None:
    from types import SimpleNamespace

    from fabric_tools.sync.common import _print_compare_results

    _print_compare_results(
        [
            SimpleNamespace(
                header="remote vs local",
                error=None,
                identical=True,
                ok=True,
                diff_text=None,
                messages=[
                    "local packable model present; joined model compare requires a bound id"
                ],
            )
        ]
    )
    out = capsys.readouterr().out
    assert "joined model compare" in out


def test_cli_exit_error_renders_error_panel(monkeypatch) -> None:
    from fabric_tools.exit_codes import EXIT_USER

    monkeypatch.setenv("FABRIC_TOOLS_READONLY", "1")
    result = CliRunner().invoke(app, ["setup", "update"])
    assert result.exit_code == EXIT_USER
    combined = (result.stdout or "") + (result.stderr or "")
    assert "Error" in combined
    assert "read-only" in combined.lower() or "readonly" in combined.lower()

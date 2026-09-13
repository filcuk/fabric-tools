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
    assert rich_utils.STYLE_USAGE == colours.HELP_STYLE_USAGE
    assert colours.HELP_STYLE_OPTION == "magenta"
    assert colours.HELP_STYLE_SWITCH == colours.STYLE_OPTION_ALIAS
    assert colours.HELP_STYLE_METAVAR == "bright_yellow"


def test_palette_rows_cover_core_roles() -> None:
    by_name = {row.name: row for row in colours.PALETTE_ROWS}
    assert by_name["red"].usage == "Error / failure"
    assert by_name["yellow"].usage.startswith("Warning")
    assert by_name["green"].usage.startswith("Success")
    assert by_name["cyan"].style == colours.STYLE_ID
    assert by_name["magenta"].style == colours.STYLE_OPTION
    assert by_name["bright magenta"].style == colours.STYLE_OPTION_ALIAS
    assert by_name["dim"].style == colours.STYLE_DIM
    assert by_name["blue"].style == colours.STYLE_HEADER
    assert by_name["default"].style is None


def test_debug_color_emits_palette_labels() -> None:
    result = CliRunner().invoke(app, ["debug", "color"])
    assert result.exit_code == EXIT_OK
    for row in colours.PALETTE_ROWS:
        assert row.name in result.stdout
        # Rich may wrap long usage cells; match a stable leading phrase.
        assert row.usage.split(";")[0] in result.stdout


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
    colours.print_warn_panel("Cancelled.")
    err = capsys.readouterr().err
    assert "Warning" in err
    assert "Cancelled." in err


def test_print_compare_results_uses_warning_panel(capsys) -> None:
    from types import SimpleNamespace

    from fabric_tools.cli import _print_compare_results

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
    err = capsys.readouterr().err
    assert "Warning" in err
    assert "joined model compare" in err


def test_cli_exit_error_renders_error_panel(monkeypatch) -> None:
    from fabric_tools.exit_codes import EXIT_USER

    monkeypatch.setenv("FABRIC_TOOLS_READONLY", "1")
    result = CliRunner().invoke(app, ["setup", "update"])
    assert result.exit_code == EXIT_USER
    combined = (result.stdout or "") + (result.stderr or "")
    assert "Error" in combined
    assert "read-only" in combined.lower() or "readonly" in combined.lower()

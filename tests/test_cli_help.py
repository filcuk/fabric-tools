"""Smoke tests for CLI help surfaces added for Gen1 / delete."""

from __future__ import annotations

from typer.testing import CliRunner

from fabric_tools.cli import app


def test_root_help_lists_dataflow_gen1() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "dataflow" in result.stdout
    assert "dataflow-gen1" in result.stdout
    assert "notebook" in result.stdout
    assert "setup" in result.stdout
    assert "Commands" in result.stdout


def test_root_help_orders_help_and_setup_first() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    help_idx = result.stdout.index("--help")
    version_idx = result.stdout.index("--version")
    interactive_idx = result.stdout.index("--interactive")
    assert help_idx < version_idx < interactive_idx

    setup_idx = result.stdout.index("setup")
    inspect_idx = result.stdout.index("inspect")
    notebook_idx = result.stdout.index("notebook")
    assert setup_idx < inspect_idx < notebook_idx


def test_setup_help_lists_update() -> None:
    result = CliRunner().invoke(app, ["setup", "--help"])
    assert result.exit_code == 0
    assert "update" in result.stdout
    assert "install" in result.stdout


def test_help_puts_description_before_usage() -> None:
    result = CliRunner().invoke(app, ["setup", "update", "--help"])
    assert result.exit_code == 0
    description = "Check for a newer release"
    usage = "Usage:"
    assert description in result.stdout
    assert usage in result.stdout
    assert result.stdout.index(description) < result.stdout.index(usage)


def test_setup_update_help_lists_check() -> None:
    result = CliRunner().invoke(app, ["setup", "update", "--help"])
    assert result.exit_code == 0
    assert "--check" in result.stdout
    assert "-c" in result.stdout


def test_dataflow_help_lists_commands() -> None:
    result = CliRunner().invoke(app, ["dataflow", "--help"])
    assert result.exit_code == 0
    for name in ("download", "deploy", "compare", "delete"):
        assert name in result.stdout
    assert "Gen2" in result.stdout or "Dataflow" in result.stdout


def test_dataflow_gen1_help_lists_commands() -> None:
    result = CliRunner().invoke(app, ["dataflow-gen1", "--help"])
    assert result.exit_code == 0
    for name in ("download", "deploy", "compare", "delete"):
        assert name in result.stdout


def test_notebook_delete_help() -> None:
    result = CliRunner().invoke(app, ["notebook", "delete", "--help"])
    assert result.exit_code == 0
    assert "Soft-delete" in result.stdout or "delete" in result.stdout.lower()

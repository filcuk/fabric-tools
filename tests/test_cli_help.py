"""Smoke tests for CLI help surfaces added for Gen1 / delete."""

from __future__ import annotations

from typer.testing import CliRunner

from fabric_tools.cli import app


def test_root_help_lists_dataflow_gen1() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "dataflow-gen1" in result.stdout
    assert "notebook" in result.stdout
    assert "update" in result.stdout


def test_update_help_lists_check() -> None:
    result = CliRunner().invoke(app, ["update", "--help"])
    assert result.exit_code == 0
    assert "--check" in result.stdout
    assert "-c" in result.stdout


def test_dataflow_gen1_help_lists_commands() -> None:
    result = CliRunner().invoke(app, ["dataflow-gen1", "--help"])
    assert result.exit_code == 0
    for name in ("download", "deploy", "compare", "delete"):
        assert name in result.stdout


def test_notebook_delete_help() -> None:
    result = CliRunner().invoke(app, ["notebook", "delete", "--help"])
    assert result.exit_code == 0
    assert "Soft-delete" in result.stdout or "delete" in result.stdout.lower()

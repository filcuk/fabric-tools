"""Tests for fabric-tools env reporting."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from fabric_tools.cli import app
from fabric_tools.env_info import ENV_VAR_SPECS, collect_env_statuses
from fabric_tools.exit_codes import EXIT_OK
from fabric_tools.readonly import READONLY_ENV
from fabric_tools.update_check import DISABLE_UPDATE_CHECK_ENV


def test_env_var_specs_cover_known_names() -> None:
    names = {spec.name for spec in ENV_VAR_SPECS}
    assert READONLY_ENV in names
    assert DISABLE_UPDATE_CHECK_ENV in names
    assert "AZURE_TENANT_ID" in names
    assert "AZURE_CLIENT_ID" in names
    assert "AZURE_CLIENT_SECRET" in names


def test_collect_env_statuses_redacts_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(READONLY_ENV, "1")
    monkeypatch.setenv(DISABLE_UPDATE_CHECK_ENV, "0")
    monkeypatch.setenv("AZURE_TENANT_ID", "tenant-guid")
    monkeypatch.setenv("AZURE_CLIENT_ID", "client-guid")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "super-secret-value")

    by_name = {row.name: row for row in collect_env_statuses()}
    assert by_name[READONLY_ENV].value == "1"
    assert by_name[READONLY_ENV].status == "enabled"
    assert by_name[DISABLE_UPDATE_CHECK_ENV].status == "set (not enabled)"
    assert by_name["AZURE_TENANT_ID"].value == "tenant-guid"
    assert by_name["AZURE_CLIENT_SECRET"].value == "***"
    assert by_name["AZURE_CLIENT_SECRET"].status == "set"
    assert "super-secret-value" not in by_name["AZURE_CLIENT_SECRET"].value


def test_collect_env_statuses_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        READONLY_ENV,
        DISABLE_UPDATE_CHECK_ENV,
        "AZURE_TENANT_ID",
        "AZURE_CLIENT_ID",
        "AZURE_CLIENT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)

    by_name = {row.name: row for row in collect_env_statuses()}
    assert by_name[READONLY_ENV].value == "(unset)"
    assert by_name[READONLY_ENV].status == "unset"
    assert by_name["AZURE_CLIENT_SECRET"].value == "(unset)"


def test_cli_env_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(READONLY_ENV, "true")
    monkeypatch.delenv("AZURE_CLIENT_SECRET", raising=False)
    result = CliRunner().invoke(app, ["env"])
    assert result.exit_code == EXIT_OK
    assert READONLY_ENV in result.stdout
    assert "enabled" in result.stdout
    assert "Effective:" in result.stdout
    assert "read-only=" in result.stdout


def test_root_help_lists_env() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "env" in result.stdout

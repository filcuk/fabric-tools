"""Tests for fabric-tools env reporting."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from fabric_tools.cli import app
from fabric_tools.env_info import ENV_VAR_SPECS, format_env_report
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


def test_format_env_report_redacts_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(READONLY_ENV, "1")
    monkeypatch.setenv(DISABLE_UPDATE_CHECK_ENV, "0")
    monkeypatch.setenv("AZURE_TENANT_ID", "tenant-guid")
    monkeypatch.setenv("AZURE_CLIENT_ID", "client-guid")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "super-secret-value")

    report = format_env_report()
    assert f"{READONLY_ENV}=1" in report
    assert "[enabled]" in report
    assert "set (not enabled)" in report
    assert "AZURE_TENANT_ID=tenant-guid" in report
    assert "AZURE_CLIENT_SECRET=***" in report
    assert "super-secret-value" not in report
    assert "read-only=on" in report
    assert "service principal=configured" in report


def test_format_env_report_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        READONLY_ENV,
        DISABLE_UPDATE_CHECK_ENV,
        "AZURE_TENANT_ID",
        "AZURE_CLIENT_ID",
        "AZURE_CLIENT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)

    report = format_env_report()
    assert f"{READONLY_ENV}=(unset)" in report
    assert "AZURE_CLIENT_SECRET=(unset)" in report
    assert "read-only=off" in report
    assert "service principal=not configured" in report


def test_cli_env_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(READONLY_ENV, "true")
    monkeypatch.delenv("AZURE_CLIENT_SECRET", raising=False)
    result = CliRunner().invoke(app, ["env"])
    assert result.exit_code == EXIT_OK
    assert READONLY_ENV in result.stdout
    assert "Effective:" in result.stdout


def test_root_help_lists_env() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "env" in result.stdout

"""Tests for fabric-tools env reporting and user-env set/unset."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from fabric_tools.cli import app
from fabric_tools.env_info import (
    ENV_VAR_SPECS,
    EnvError,
    collect_env_statuses,
    format_set_confirmation,
    get_spec,
    set_user_env,
    unset_user_env,
)
from fabric_tools.exit_codes import EXIT_OK, EXIT_USER
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


def test_get_spec_rejects_unknown() -> None:
    with pytest.raises(EnvError, match="Unknown"):
        get_spec("NOT_A_REAL_VAR")


def test_set_user_env_updates_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written: list[tuple[str, str]] = []

    def fake_write(name: str, value: str) -> None:
        written.append((name, value))

    monkeypatch.setattr("fabric_tools.env_info._write_user_env", fake_write)
    monkeypatch.delenv(READONLY_ENV, raising=False)

    spec = set_user_env(READONLY_ENV, "1")
    assert spec.name == READONLY_ENV
    assert written == [(READONLY_ENV, "1")]
    assert __import__("os").environ.get(READONLY_ENV) == "1"


def test_unset_user_env_updates_process(monkeypatch: pytest.MonkeyPatch) -> None:
    deleted: list[str] = []

    def fake_delete(name: str) -> None:
        deleted.append(name)

    monkeypatch.setattr("fabric_tools.env_info._delete_user_env", fake_delete)
    monkeypatch.setenv(READONLY_ENV, "1")

    spec = unset_user_env(READONLY_ENV)
    assert spec.name == READONLY_ENV
    assert deleted == [READONLY_ENV]
    assert READONLY_ENV not in __import__("os").environ


def test_set_user_env_rejects_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fabric_tools.env_info._write_user_env", lambda *_a, **_k: None)
    with pytest.raises(EnvError, match="Empty value"):
        set_user_env(READONLY_ENV, "")


def test_set_user_env_non_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fabric_tools.env_info.os.name", "posix")
    with pytest.raises(EnvError, match="Windows"):
        set_user_env(READONLY_ENV, "1")


def test_format_set_confirmation_hides_secret() -> None:
    spec = get_spec("AZURE_CLIENT_SECRET")
    text = format_set_confirmation(spec, "super-secret-value")
    assert "AZURE_CLIENT_SECRET" in text
    assert "super-secret-value" not in text
    assert "value hidden" in text


def test_cli_env_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(READONLY_ENV, "true")
    monkeypatch.delenv("AZURE_CLIENT_SECRET", raising=False)
    result = CliRunner().invoke(app, ["env", "list"])
    assert result.exit_code == EXIT_OK
    assert READONLY_ENV in result.stdout
    assert "enabled" in result.stdout
    assert "Effective:" in result.stdout
    assert "read-only=" in result.stdout


def test_cli_env_bare_shows_help() -> None:
    result = CliRunner().invoke(app, ["env"])
    assert result.exit_code != 0
    output = result.stdout + (result.stderr or "")
    assert "list" in output
    assert "set" in output
    assert "unset" in output


def test_cli_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    written: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "fabric_tools.env_info._write_user_env",
        lambda name, value: written.append((name, value)),
    )
    result = CliRunner().invoke(app, ["env", "set", READONLY_ENV, "1"])
    assert result.exit_code == EXIT_OK
    assert written == [(READONLY_ENV, "1")]
    assert READONLY_ENV in result.stdout
    assert "Open a new terminal" in result.stdout


def test_cli_env_set_secret_not_echoed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fabric_tools.env_info._write_user_env", lambda *_a, **_k: None)
    secret = "super-secret-value"
    result = CliRunner().invoke(app, ["env", "set", "AZURE_CLIENT_SECRET", secret])
    assert result.exit_code == EXIT_OK
    assert secret not in result.stdout
    assert "value hidden" in result.stdout


def test_cli_env_set_unknown() -> None:
    result = CliRunner().invoke(app, ["env", "set", "NOPE", "1"])
    assert result.exit_code == EXIT_USER
    assert "Unknown" in (result.stderr or result.output)


def test_cli_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    deleted: list[str] = []
    monkeypatch.setattr(
        "fabric_tools.env_info._delete_user_env",
        lambda name: deleted.append(name),
    )
    result = CliRunner().invoke(app, ["env", "unset", READONLY_ENV])
    assert result.exit_code == EXIT_OK
    assert deleted == [READONLY_ENV]
    assert "Unset" in result.stdout


def test_cli_env_set_allowed_when_readonly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(READONLY_ENV, "1")
    monkeypatch.setattr("fabric_tools.env_info._write_user_env", lambda *_a, **_k: None)
    result = CliRunner().invoke(app, ["env", "set", "AZURE_TENANT_ID", "tenant"])
    assert result.exit_code == EXIT_OK


def test_root_help_lists_env() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "env" in result.stdout


def test_env_help_lists_list_set_unset() -> None:
    result = CliRunner().invoke(app, ["env", "--help"])
    assert result.exit_code == 0
    assert "list" in result.stdout
    assert "set" in result.stdout
    assert "unset" in result.stdout

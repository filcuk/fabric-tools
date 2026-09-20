"""Tests for FABRIC_TOOLS_READONLY guard."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from fabric_tools.cli import app
from fabric_tools.exit_codes import EXIT_USER
from fabric_tools.parsing import CommandMode
from fabric_tools.readonly import (
    READONLY_ENV,
    ReadOnlyError,
    ensure_command_allowed,
    ensure_setup_mutation_allowed,
    is_readonly_enabled,
)

WS = "11111111-1111-1111-1111-111111111111"
ITEM = "22222222-2222-2222-2222-222222222222"
TARGET = f"{WS}:{ITEM}"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", True),
        ("true", True),
        ("YES", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("", False),
    ],
)
def test_is_readonly_enabled(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
) -> None:
    if value == "":
        monkeypatch.delenv(READONLY_ENV, raising=False)
    else:
        monkeypatch.setenv(READONLY_ENV, value)
    assert is_readonly_enabled() is expected


def test_ensure_command_allows_download_and_compare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(READONLY_ENV, "1")
    ensure_command_allowed(CommandMode.DOWNLOAD, dry_run=False)
    ensure_command_allowed(CommandMode.COMPARE, dry_run=False)


def test_ensure_command_allows_mutating_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(READONLY_ENV, "1")
    ensure_command_allowed(CommandMode.DEPLOY, dry_run=True)
    ensure_command_allowed(CommandMode.DELETE, dry_run=True)


def test_ensure_command_blocks_deploy_and_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(READONLY_ENV, "1")
    with pytest.raises(ReadOnlyError, match=READONLY_ENV):
        ensure_command_allowed(CommandMode.DEPLOY, dry_run=False)
    with pytest.raises(ReadOnlyError, match="delete"):
        ensure_command_allowed(CommandMode.DELETE, dry_run=False)


def test_ensure_setup_blocks_mutations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(READONLY_ENV, "1")
    with pytest.raises(ReadOnlyError, match="install"):
        ensure_setup_mutation_allowed("install")


def test_cli_readonly_blocks_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(READONLY_ENV, "1")
    result = CliRunner().invoke(
        app,
        ["notebook", "delete", "-s", "-t", TARGET],
    )
    assert result.exit_code == EXIT_USER
    assert READONLY_ENV in (result.stderr or result.output)


def test_cli_readonly_blocks_deploy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(READONLY_ENV, "1")
    result = CliRunner().invoke(
        app,
        ["notebook", "deploy", "-s", "-t", TARGET, "-f", "missing.ipynb"],
    )
    assert result.exit_code == EXIT_USER
    assert READONLY_ENV in (result.stderr or result.output)


def test_cli_readonly_allows_deploy_dry_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv(READONLY_ENV, "1")
    nb = tmp_path / "n.ipynb"
    nb.write_text(
        '{"nbformat":4,"nbformat_minor":5,"metadata":{},"cells":[]}',
        encoding="utf-8",
    )
    # File-only dry-run skips auth; must not hit the readonly refusal.
    result = CliRunner().invoke(
        app,
        ["notebook", "deploy", "-d", "-f", str(nb)],
    )
    assert READONLY_ENV not in (result.stderr or result.output)
    assert result.exit_code == 0


def test_cli_readonly_blocks_setup_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(READONLY_ENV, "1")
    result = CliRunner().invoke(app, ["setup", "install"])
    assert result.exit_code == EXIT_USER
    assert READONLY_ENV in (result.stderr or result.output)


def test_cli_readonly_allows_setup_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(READONLY_ENV, "1")
    result = CliRunner().invoke(app, ["setup", "status"])
    assert READONLY_ENV not in (result.stderr or result.output)


def test_cli_readonly_blocks_setup_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(READONLY_ENV, "1")
    result = CliRunner().invoke(app, ["setup", "clean"])
    assert result.exit_code == EXIT_USER
    assert READONLY_ENV in (result.stderr or result.output)


def test_cli_readonly_allows_manifest_delete(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from fabric_tools.manifest import manifest_from_work_items, save_manifest
    from fabric_tools.parsing import Target, WorkItem

    monkeypatch.setenv(READONLY_ENV, "1")
    monkeypatch.chdir(tmp_path)
    nb = tmp_path / "etl.ipynb"
    nb.write_text("{}", encoding="utf-8")
    save_manifest(
        tmp_path / "demo",
        manifest_from_work_items([WorkItem(Target(WS, ITEM), nb)]),
    )
    result = CliRunner().invoke(app, ["manifest", "delete", "-s", "-m", "demo"])
    assert result.exit_code == 0
    assert READONLY_ENV not in (result.stderr or result.output)
    assert not (tmp_path / "demo.ftdep").exists()

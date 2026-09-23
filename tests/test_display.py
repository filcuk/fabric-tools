"""Tests for informational GUID / path display helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from fabric_tools import display

GUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


@pytest.fixture(autouse=True)
def _clear_guid_length(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(display.GUID_LENGTH_ENV, raising=False)


def test_format_guid_default_length() -> None:
    assert display.format_guid(GUID) == "a1b2c3d"


def test_format_guid_passes_through_non_guid() -> None:
    assert display.format_guid("Sales") == "Sales"
    assert display.format_guid("abcdefghij") == "abcdefghij"


def test_format_guid_explicit_length() -> None:
    assert display.format_guid(GUID, length=4) == "a1b2"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", 7),
        ("12", 12),
        ("full", None),
        ("FULL", None),
        ("0", None),
        ("36", None),
        ("abc", 7),
        ("-3", 7),
        ("99", 7),
    ],
)
def test_resolve_guid_length(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: int | None
) -> None:
    monkeypatch.setenv(display.GUID_LENGTH_ENV, raw)
    assert display.resolve_guid_length() == expected


def test_format_guid_full_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(display.GUID_LENGTH_ENV, "full")
    assert display.format_guid(GUID) == GUID


def test_format_item_ref() -> None:
    assert display.format_item_ref("Sales", GUID) == "Sales (a1b2c3d)"
    assert display.format_item_ref(GUID, GUID) == "a1b2c3d"
    assert display.format_item_ref(None, GUID) == "a1b2c3d"
    assert display.format_item_ref("Sales", None) == "Sales"
    assert display.format_item_ref(None, None) == "-"


def test_format_local_path_relative_under_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "out" / "Sales.ipynb"
    assert display.format_local_path(target) == str(Path("out") / "Sales.ipynb")
    assert display.format_local_path(Path("out") / "Sales.ipynb") == str(
        Path("out") / "Sales.ipynb"
    )


def test_format_local_path_outside_cwd_stays_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    outside = tmp_path / "x.ipynb"
    assert display.format_local_path(outside) == str(outside.resolve())

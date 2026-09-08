"""Tests for target/file parsing and pairing rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from fabric_tools.parsing import (
    CommandMode,
    ParseError,
    build_work_items,
    parse_file_values,
    parse_target_values,
)

WS = "11111111-1111-1111-1111-111111111111"
A = "22222222-2222-2222-2222-222222222222"
B = "33333333-3333-3333-3333-333333333333"
WS2 = "44444444-4444-4444-4444-444444444444"


def test_parse_targets_comma_and_create() -> None:
    targets = parse_target_values([f"{WS}:{A},{WS}:{B}", WS2])
    assert len(targets) == 3
    assert targets[0].item_id == A
    assert targets[2].is_create


def test_download_broadcast_one_file() -> None:
    targets = parse_target_values([f"{WS}:{A},{WS}:{B}"])
    files = parse_file_values(["one.ipynb"])
    items = build_work_items(CommandMode.DOWNLOAD, targets, files, dry_run=False)
    assert len(items) == 2
    assert items[0].file == items[1].file == Path("one.ipynb")


def test_compare_rejects_broadcast() -> None:
    targets = parse_target_values([f"{WS}:{A},{WS}:{B}"])
    files = parse_file_values(["one.ipynb"])
    with pytest.raises(ParseError, match="1:1"):
        build_work_items(CommandMode.COMPARE, targets, files, dry_run=False)


def test_download_rejects_multiple_workspaces() -> None:
    targets = parse_target_values([f"{WS}:{A},{WS2}:{B}"])
    files = parse_file_values(["a.ipynb", "b.ipynb"])
    with pytest.raises(ParseError, match="one workspace"):
        build_work_items(CommandMode.DOWNLOAD, targets, files, dry_run=False)


def test_upload_rejects_mixed_create_and_overwrite() -> None:
    targets = parse_target_values([WS, f"{WS}:{A}"])
    files = parse_file_values(["a.ipynb", "b.ipynb"])
    with pytest.raises(ParseError, match="cannot mix"):
        build_work_items(CommandMode.UPLOAD, targets, files, dry_run=False)


def test_dry_run_files_only() -> None:
    items = build_work_items(
        CommandMode.UPLOAD,
        [],
        parse_file_values(["a.ipynb"]),
        dry_run=True,
    )
    assert len(items) == 1
    assert items[0].target is None
    assert items[0].file == Path("a.ipynb")


def test_dry_run_requires_something() -> None:
    with pytest.raises(ParseError, match="at least one"):
        build_work_items(CommandMode.UPLOAD, [], [], dry_run=True)


def test_invalid_guid() -> None:
    with pytest.raises(ParseError, match="invalid workspace"):
        parse_target_values(["not-a-guid"])

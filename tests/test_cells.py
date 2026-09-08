"""Tests for selective cell replacement helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from fabric_tools.notebook.cells import (
    CellSelectionError,
    merge_notebook_cells,
    parse_cell_indices,
    validate_cells_usage,
)
from fabric_tools.parsing import CommandMode, ParseError, Target, WorkItem

WS = "11111111-1111-1111-1111-111111111111"
A = "22222222-2222-2222-2222-222222222222"


def _nb(*sources: str) -> dict:
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": [
            {"cell_type": "code", "metadata": {}, "source": [src], "outputs": []}
            for src in sources
        ],
    }


def test_parse_cell_indices_comma_and_repeatable() -> None:
    assert parse_cell_indices(["1,3", "5", "3"]) == [1, 3, 5]


def test_parse_cell_indices_rejects_zero() -> None:
    with pytest.raises(CellSelectionError, match="1-based"):
        parse_cell_indices(["0,1"])


def test_parse_cell_indices_rejects_non_int() -> None:
    with pytest.raises(CellSelectionError, match="positive integer"):
        parse_cell_indices(["1,a"])


def test_merge_replaces_whole_cells() -> None:
    remote = _nb("r1", "r2", "r3")
    local = _nb("l1", "l2", "l3")
    local["cells"][0]["outputs"] = [{"output_type": "stream", "text": ["out\n"]}]
    merged = merge_notebook_cells(remote, local, [1, 3])
    assert merged["cells"][0]["source"] == ["l1"]
    assert merged["cells"][0]["outputs"] == [{"output_type": "stream", "text": ["out\n"]}]
    assert merged["cells"][1]["source"] == ["r2"]
    assert merged["cells"][2]["source"] == ["l3"]


def test_merge_fails_when_index_missing() -> None:
    with pytest.raises(CellSelectionError, match="remote"):
        merge_notebook_cells(_nb("r1"), _nb("l1", "l2"), [1, 2])


def test_validate_cells_usage_rejects_multi(tmp_path: Path) -> None:
    nb = tmp_path / "a.ipynb"
    nb.write_text('{"nbformat":4,"nbformat_minor":5,"cells":[],"metadata":{}}', encoding="utf-8")
    items = [
        WorkItem(Target(WS, A), nb),
        WorkItem(Target(WS, A), nb),
    ]
    with pytest.raises(ParseError, match="exactly one"):
        validate_cells_usage(CommandMode.UPLOAD, items, [1], dry_run=False)


def test_validate_cells_usage_rejects_create(tmp_path: Path) -> None:
    nb = tmp_path / "a.ipynb"
    nb.write_text('{"nbformat":4,"nbformat_minor":5,"cells":[],"metadata":{}}', encoding="utf-8")
    items = [WorkItem(Target(WS), nb)]
    with pytest.raises(ParseError, match="overwrite"):
        validate_cells_usage(CommandMode.UPLOAD, items, [1], dry_run=False)

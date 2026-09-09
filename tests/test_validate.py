"""Tests for dry-run validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fabric_tools.client import FabricApiError
from fabric_tools.parsing import CommandMode, Target, WorkItem
from fabric_tools.validate import run_dry_run


class FakeClient:
    def __init__(self, *, item_type: str = "Notebook") -> None:
        self.item_type = item_type

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        return {"id": workspace_id, "displayName": "Dev"}

    def get_item(self, workspace_id: str, item_id: str) -> dict[str, Any]:
        return {
            "id": item_id,
            "workspaceId": workspace_id,
            "displayName": "NB",
            "type": self.item_type,
        }


def test_dry_run_local_ok(tmp_path: Path) -> None:
    nb = tmp_path / "demo.ipynb"
    nb.write_text(
        json.dumps(
            {"nbformat": 4, "nbformat_minor": 5, "cells": [], "metadata": {}}
        ),
        encoding="utf-8",
    )
    results = run_dry_run(
        CommandMode.UPLOAD,
        [WorkItem(None, nb)],
        client=None,
        has_targets=False,
        has_files=True,
    )
    assert len(results) == 1 and results[0].ok


def test_dry_run_broadcast_file_validated_once(tmp_path: Path) -> None:
    nb = tmp_path / "demo.ipynb"
    nb.write_text(
        json.dumps(
            {"nbformat": 4, "nbformat_minor": 5, "cells": [], "metadata": {}}
        ),
        encoding="utf-8",
    )
    ws1 = "11111111-1111-1111-1111-111111111111"
    ws2 = "22222222-2222-2222-2222-222222222222"
    item1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    item2 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    items = [
        WorkItem(Target(ws1, item1), nb),
        WorkItem(Target(ws2, item2), nb),
    ]
    results = run_dry_run(
        CommandMode.UPLOAD,
        items,
        client=FakeClient(),  # type: ignore[arg-type]
        has_targets=True,
        has_files=True,
    )
    local = [r for r in results if r.message.startswith("local ok:")]
    assert len(local) == 1 and local[0].ok
    remote = [r for r in results if r.message.startswith("remote ok:")]
    assert len(remote) == 4  # 2 workspaces + 2 notebooks


def test_dry_run_remote_wrong_type() -> None:
    client = FakeClient(item_type="Lakehouse")
    item = WorkItem(
        Target("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"),
        None,
    )
    results = run_dry_run(
        CommandMode.DOWNLOAD,
        [item],
        client=client,  # type: ignore[arg-type]
        has_targets=True,
        has_files=False,
    )
    assert any(not r.ok and "Lakehouse" in r.message for r in results)


def test_dry_run_remote_missing_item() -> None:
    class MissingClient(FakeClient):
        def get_item(self, workspace_id: str, item_id: str) -> dict[str, Any]:
            raise FabricApiError("missing", status_code=404, error_code="ItemNotFound")

    item = WorkItem(
        Target("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"),
        None,
    )
    results = run_dry_run(
        CommandMode.COMPARE,
        [item],
        client=MissingClient(),  # type: ignore[arg-type]
        has_targets=True,
        has_files=False,
    )
    assert any(not r.ok and "ItemNotFound" in r.message for r in results)

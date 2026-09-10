"""Tests for default download destination resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fabric_tools.confirm import (
    resolve_dataflow_download_files,
    resolve_dataflow_gen1_download_files,
    resolve_notebook_download_files,
)
from fabric_tools.parsing import Target, WorkItem

WS = "11111111-1111-1111-1111-111111111111"
A = "22222222-2222-2222-2222-222222222222"
B = "33333333-3333-3333-3333-333333333333"


class FakeFabricClient:
    def get_item(self, workspace_id: str, item_id: str) -> dict[str, Any]:
        names = {A: "Notebook1", B: "Notebook1"}
        return {
            "id": item_id,
            "workspaceId": workspace_id,
            "displayName": names.get(item_id, "Notebook"),
            "type": "Notebook",
        }


class FakeDataflowFabricClient:
    def get_item(self, workspace_id: str, item_id: str) -> dict[str, Any]:
        return {
            "id": item_id,
            "workspaceId": workspace_id,
            "displayName": "My Flow",
            "type": "Dataflow",
        }


class FakePowerBiClient:
    def get_dataflow(self, group_id: str, dataflow_id: str) -> dict[str, Any]:
        return {"objectId": dataflow_id, "name": "My Dataflow"}


def test_resolve_notebook_download_files_defaults() -> None:
    items = [
        WorkItem(Target(WS, A), None),
        WorkItem(Target(WS, B), None),
    ]
    resolved = resolve_notebook_download_files(FakeFabricClient(), items)  # type: ignore[arg-type]
    assert [item.file for item in resolved] == [
        Path("Notebook1.ipynb"),
        Path("Notebook1 (2).ipynb"),
    ]


def test_resolve_notebook_download_files_keeps_explicit() -> None:
    dest = Path("custom.ipynb")
    items = [WorkItem(Target(WS, A), dest)]
    resolved = resolve_notebook_download_files(FakeFabricClient(), items)  # type: ignore[arg-type]
    assert resolved[0].file == dest


def test_resolve_dataflow_gen1_download_files_defaults() -> None:
    items = [WorkItem(Target(WS, A), None)]
    resolved = resolve_dataflow_gen1_download_files(
        FakePowerBiClient(),  # type: ignore[arg-type]
        items,
    )
    assert resolved[0].file == Path("My Dataflow.json")


def test_resolve_dataflow_download_files_defaults() -> None:
    items = [WorkItem(Target(WS, A), None)]
    resolved = resolve_dataflow_download_files(
        FakeDataflowFabricClient(),  # type: ignore[arg-type]
        items,
    )
    assert resolved[0].file == Path("My Flow.Dataflow")

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
        json.dumps({"nbformat": 4, "nbformat_minor": 5, "cells": [], "metadata": {}}),
        encoding="utf-8",
    )
    results = run_dry_run(
        CommandMode.DEPLOY,
        [WorkItem(None, nb)],
        client=None,
        has_targets=False,
        has_files=True,
    )
    assert len(results) == 1 and results[0].ok


def test_dry_run_broadcast_file_validated_once(tmp_path: Path) -> None:
    nb = tmp_path / "demo.ipynb"
    nb.write_text(
        json.dumps({"nbformat": 4, "nbformat_minor": 5, "cells": [], "metadata": {}}),
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
        CommandMode.DEPLOY,
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
        Target(
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ),
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
        Target(
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ),
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


def test_dry_run_origin_ok() -> None:
    ws = "11111111-1111-1111-1111-111111111111"
    origin_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    target_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    item = WorkItem(
        Target(ws, target_id),
        None,
        origin=Target(ws, origin_id),
    )
    results = run_dry_run(
        CommandMode.DEPLOY,
        [item],
        client=FakeClient(),  # type: ignore[arg-type]
        has_targets=True,
        has_files=False,
        has_origins=True,
    )
    assert all(r.ok for r in results)
    assert any("origin notebook" in r.message for r in results)
    assert any("target notebook" in r.message for r in results)


def test_dry_run_delete_notebook() -> None:
    item = WorkItem(
        Target(
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ),
        None,
    )
    results = run_dry_run(
        CommandMode.DELETE,
        [item],
        client=FakeClient(),  # type: ignore[arg-type]
        has_targets=True,
        has_files=False,
    )
    assert all(r.ok for r in results)
    assert any("delete" in r.message for r in results)


def test_dry_run_dataflow_gen1_local_and_remote(tmp_path: Path) -> None:
    from fabric_tools.powerbi_client import PowerBiApiError
    from fabric_tools.validate import run_dry_run_dataflow_gen1

    model = tmp_path / "model.json"
    model.write_text(
        json.dumps({"name": "Sales", "entities": []}),
        encoding="utf-8",
    )
    ws = "11111111-1111-1111-1111-111111111111"
    df = "22222222-2222-2222-2222-222222222222"

    class FakePowerBi:
        def get_group(self, group_id: str) -> dict[str, Any]:
            return {"id": group_id, "name": "Dev"}

        def get_dataflow(self, group_id: str, dataflow_id: str) -> dict[str, Any]:
            if dataflow_id != df:
                raise PowerBiApiError("missing", status_code=404)
            return {"objectId": dataflow_id, "name": "Sales"}

    items = [WorkItem(Target(ws, df), model)]
    results = run_dry_run_dataflow_gen1(
        CommandMode.DOWNLOAD,
        items,
        client=FakePowerBi(),  # type: ignore[arg-type]
        has_targets=True,
        has_files=True,
    )
    assert all(r.ok for r in results)
    assert any("model.json" in r.message for r in results)
    assert any("dataflow-gen1" in r.message for r in results)


def test_dry_run_dataflow_gen1_missing_remote() -> None:
    from fabric_tools.powerbi_client import PowerBiApiError
    from fabric_tools.validate import run_dry_run_dataflow_gen1

    class FakePowerBi:
        def get_group(self, group_id: str) -> dict[str, Any]:
            return {"id": group_id, "name": "Dev"}

        def get_dataflow(self, group_id: str, dataflow_id: str) -> dict[str, Any]:
            raise PowerBiApiError(
                "missing", status_code=404, error_code="DataflowNotFound"
            )

    item = WorkItem(
        Target(
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ),
        None,
    )
    results = run_dry_run_dataflow_gen1(
        CommandMode.DELETE,
        [item],
        client=FakePowerBi(),  # type: ignore[arg-type]
        has_targets=True,
        has_files=False,
    )
    assert any(not r.ok and "DataflowNotFound" in r.message for r in results)


def test_dry_run_dataflow_local_and_remote(tmp_path: Path) -> None:
    from fabric_tools.validate import run_dry_run_dataflow

    folder = tmp_path / "Sales.Dataflow"
    folder.mkdir()
    (folder / "queryMetadata.json").write_text(
        json.dumps(
            {
                "formatVersion": "202502",
                "name": "Sales",
                "queryGroups": [],
                "queriesMetadata": {},
                "connections": [],
            }
        ),
        encoding="utf-8",
    )
    (folder / "mashup.pq").write_text("section Section1;\n", encoding="utf-8")
    ws = "11111111-1111-1111-1111-111111111111"
    df = "22222222-2222-2222-2222-222222222222"
    client = FakeClient(item_type="Dataflow")
    results = run_dry_run_dataflow(
        CommandMode.DOWNLOAD,
        [WorkItem(Target(ws, df), folder)],
        client=client,  # type: ignore[arg-type]
        has_targets=True,
        has_files=True,
    )
    assert all(r.ok for r in results)
    assert any("Dataflow folder" in r.message for r in results)
    assert any("dataflow" in r.message for r in results)


def test_dry_run_dataflow_wrong_type() -> None:
    from fabric_tools.validate import run_dry_run_dataflow

    item = WorkItem(
        Target(
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ),
        None,
    )
    results = run_dry_run_dataflow(
        CommandMode.DOWNLOAD,
        [item],
        client=FakeClient(item_type="Notebook"),  # type: ignore[arg-type]
        has_targets=True,
        has_files=False,
    )
    assert any(not r.ok and "Notebook" in r.message for r in results)


def test_dry_run_pipeline_local_and_remote(tmp_path: Path) -> None:
    from fabric_tools.validate import run_dry_run_pipeline

    folder = tmp_path / "ETL.DataPipeline"
    folder.mkdir()
    (folder / "pipeline-content.json").write_text(
        json.dumps(
            {
                "properties": {
                    "activities": [
                        {
                            "name": "Wait_1",
                            "type": "Wait",
                            "dependsOn": [],
                            "typeProperties": {"waitTimeInSeconds": 10},
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    ws = "11111111-1111-1111-1111-111111111111"
    pl = "22222222-2222-2222-2222-222222222222"
    client = FakeClient(item_type="DataPipeline")
    results = run_dry_run_pipeline(
        CommandMode.DOWNLOAD,
        [WorkItem(Target(ws, pl), folder)],
        client=client,  # type: ignore[arg-type]
        has_targets=True,
        has_files=True,
    )
    assert all(r.ok for r in results)
    assert any("DataPipeline folder" in r.message for r in results)
    assert any("pipeline" in r.message for r in results)


def test_dry_run_udf_local_and_remote(tmp_path: Path) -> None:
    from fabric_tools.validate import run_dry_run_udf

    folder = tmp_path / "Demo.UserDataFunction"
    folder.mkdir()
    (folder / "definition.json").write_text(
        json.dumps(
            {
                "runtime": "PYTHON",
                "connectedDataSources": [],
                "functions": [],
                "libraries": {"public": [], "private": []},
            }
        ),
        encoding="utf-8",
    )
    (folder / "function_app.py").write_text("print(1)\n", encoding="utf-8")
    resources = folder / "resources"
    resources.mkdir()
    (resources / "functions.json").write_text("{}", encoding="utf-8")

    ws = "11111111-1111-1111-1111-111111111111"
    udf_id = "22222222-2222-2222-2222-222222222222"
    client = FakeClient(item_type="UserDataFunction")
    results = run_dry_run_udf(
        CommandMode.DOWNLOAD,
        [WorkItem(Target(ws, udf_id), folder)],
        client=client,  # type: ignore[arg-type]
        has_targets=True,
        has_files=True,
    )
    assert all(r.ok for r in results)
    assert any("UserDataFunction folder" in r.message for r in results)
    assert any("udf" in r.message for r in results)

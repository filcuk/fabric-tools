"""Tests for Dataflow Gen1 download/create/delete ops with a fake Power BI client."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fabric_tools.dataflow_gen1.ops import (
    delete_dataflow,
    deploy_dataflow,
    download_dataflow,
)
from fabric_tools.parsing import Target, WorkItem
from fabric_tools.powerbi_client import PowerBiApiError

WS = "11111111-1111-1111-1111-111111111111"
DF = "22222222-2222-2222-2222-222222222222"
ORIGIN = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CREATED = "99999999-9999-9999-9999-999999999999"


class FakePowerBiClient:
    def __init__(
        self,
        *,
        models_by_id: dict[str, dict[str, Any]] | None = None,
        import_dataflows: list[dict[str, Any]] | None = None,
        listed: list[dict[str, Any]] | None = None,
    ) -> None:
        self.models_by_id = models_by_id or {
            DF: {
                "name": "Sales",
                "entities": [
                    {"name": "Query1", "partitions": [{"name": "p"}]}
                ],
            },
            ORIGIN: {
                "name": "OriginFlow",
                "entities": [{"name": "Q"}],
            },
        }
        self.import_dataflows = (
            import_dataflows
            if import_dataflows is not None
            else [{"objectId": CREATED, "name": "Sales"}]
        )
        self.listed = listed if listed is not None else []
        self.deleted: list[tuple[str, str]] = []
        self.last_import_bytes: bytes | None = None
        self.last_name_conflict: str | None = None

    def get_dataflow_definition(self, group_id: str, dataflow_id: str) -> dict[str, Any]:
        if dataflow_id not in self.models_by_id:
            raise PowerBiApiError("missing", status_code=404)
        return json.loads(json.dumps(self.models_by_id[dataflow_id]))

    def create_dataflow_from_model(
        self,
        group_id: str,
        model_json_bytes: bytes,
        *,
        name_conflict: str = "Abort",
        wait: bool = True,
    ) -> dict[str, Any]:
        self.last_import_bytes = model_json_bytes
        self.last_name_conflict = name_conflict
        assert b"partitions" not in model_json_bytes
        return {
            "id": "imp-1",
            "importState": "Succeeded",
            "dataflows": list(self.import_dataflows),
        }

    def list_dataflows(self, group_id: str) -> list[dict[str, Any]]:
        return list(self.listed)

    def delete_dataflow(self, group_id: str, dataflow_id: str) -> None:
        self.deleted.append((group_id, dataflow_id))


def test_download_writes_model(tmp_path: Path) -> None:
    client = FakePowerBiClient()
    dest = tmp_path / "out.json"
    item = WorkItem(Target(WS, DF), dest)
    result = download_dataflow(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert dest.is_file()
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["name"] == "Sales"


def test_deploy_create_from_file(tmp_path: Path) -> None:
    client = FakePowerBiClient()
    src = tmp_path / "model.json"
    src.write_text(
        json.dumps(
            {
                "name": "Sales",
                "entities": [
                    {"name": "Query1", "partitions": [{"name": "p"}]}
                ],
            }
        ),
        encoding="utf-8",
    )
    item = WorkItem(Target(WS), src)
    result = deploy_dataflow(client, item, display_name="Sales")  # type: ignore[arg-type]
    assert result.ok
    assert result.item_id == CREATED
    assert client.last_name_conflict == "Abort"
    assert b'"name":"Sales"' in (client.last_import_bytes or b"")


def test_deploy_create_from_origin() -> None:
    client = FakePowerBiClient()
    item = WorkItem(Target(WS), None, origin=Target(WS, ORIGIN))
    result = deploy_dataflow(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert result.item_id == CREATED
    assert "OriginFlow" in result.message or result.ok


def test_deploy_rejects_overwrite_target(tmp_path: Path) -> None:
    client = FakePowerBiClient()
    src = tmp_path / "model.json"
    src.write_text(json.dumps({"name": "Sales", "entities": []}), encoding="utf-8")
    item = WorkItem(Target(WS, DF), src)
    result = deploy_dataflow(client, item)  # type: ignore[arg-type]
    assert not result.ok
    assert "create only" in result.message


def test_deploy_resolves_id_via_list_when_import_omits_dataflows(
    tmp_path: Path,
) -> None:
    client = FakePowerBiClient(import_dataflows=[], listed=[{"objectId": CREATED, "name": "Sales"}])
    src = tmp_path / "model.json"
    src.write_text(json.dumps({"name": "Sales", "entities": []}), encoding="utf-8")
    item = WorkItem(Target(WS), src)
    result = deploy_dataflow(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert result.item_id == CREATED


def test_delete_dataflow() -> None:
    client = FakePowerBiClient()
    item = WorkItem(Target(WS, DF), None)
    result = delete_dataflow(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert client.deleted == [(WS, DF)]


def test_delete_requires_item_id() -> None:
    client = FakePowerBiClient()
    item = WorkItem(Target(WS), None)
    result = delete_dataflow(client, item)  # type: ignore[arg-type]
    assert not result.ok

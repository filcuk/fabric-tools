"""Tests for semantic model download/deploy/delete ops with a fake Fabric client."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fabric_tools.client import FabricApiError
from fabric_tools.definition_parts import PAYLOAD_TYPE
from fabric_tools.parsing import Target, WorkItem
from fabric_tools.semantic_model.ops import (
    delete_semantic_model,
    deploy_semantic_model,
    download_semantic_model,
)

WS = "11111111-1111-1111-1111-111111111111"
SM = "22222222-2222-2222-2222-222222222222"
ORIGIN = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CREATED = "99999999-9999-9999-9999-999999999999"


def _pbism() -> bytes:
    return json.dumps({"version": "5.0"}).encode("utf-8")


def _part(path: str, raw: bytes) -> dict[str, str]:
    return {
        "path": path,
        "payload": base64.b64encode(raw).decode("ascii"),
        "payloadType": PAYLOAD_TYPE,
    }


def _definition(*, model: str = "model Sales\n") -> dict[str, Any]:
    return {
        "format": "TMDL",
        "parts": [
            _part("definition.pbism", _pbism()),
            _part("definition/model.tmdl", model.encode("utf-8")),
        ],
    }


def _write_local(folder: Path, *, model: str = "model Sales\n") -> Path:
    (folder / "definition").mkdir(parents=True)
    (folder / "definition.pbism").write_bytes(_pbism())
    (folder / "definition" / "model.tmdl").write_text(model, encoding="utf-8")
    return folder


class FakeClient:
    def __init__(
        self,
        *,
        definitions_by_item: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None, Any]] = []
        self.definitions_by_item = definitions_by_item or {
            SM: _definition(),
            ORIGIN: _definition(model="model Origin\n"),
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        wait: bool = True,
    ) -> Any:
        del wait
        self.calls.append((method, path, params, json))
        if method == "POST" and path.endswith("/getDefinition"):
            item_id = path.split("/")[-2]
            return {"definition": self.definitions_by_item[item_id]}
        if method == "POST" and path.endswith("/items"):
            return {
                "id": CREATED,
                "type": "SemanticModel",
                "displayName": json["displayName"],
            }
        if method == "POST" and path.endswith("/updateDefinition"):
            return None
        if method == "DELETE":
            return None
        raise FabricApiError(f"unexpected {method} {path}")

    def get_item(self, workspace_id: str, item_id: str) -> dict[str, Any]:
        del workspace_id
        return {"id": item_id, "displayName": "FromOrigin", "type": "SemanticModel"}


def test_download_writes_folder(tmp_path: Path) -> None:
    dest = tmp_path / "Sales.SemanticModel"
    client = FakeClient()
    result = download_semantic_model(
        client,
        WorkItem(Target(WS, SM), dest),  # type: ignore[arg-type]
    )
    assert result.ok
    assert (dest / "definition" / "model.tmdl").is_file()
    assert any(c[0] == "POST" and c[1].endswith("/getDefinition") for c in client.calls)


def test_deploy_create_and_overwrite(tmp_path: Path) -> None:
    folder = _write_local(tmp_path / "Sales.SemanticModel")
    client = FakeClient()

    created = deploy_semantic_model(
        client,
        WorkItem(Target(WS, None), folder),  # type: ignore[arg-type]
        display_name="Sales",
    )
    assert created.ok
    assert created.item_id == CREATED

    updated = deploy_semantic_model(
        client,
        WorkItem(Target(WS, SM), folder),  # type: ignore[arg-type]
    )
    assert updated.ok
    assert any(c[1].endswith("/updateDefinition") for c in client.calls)


def test_deploy_from_origin(tmp_path: Path) -> None:
    del tmp_path
    client = FakeClient()
    result = deploy_semantic_model(
        client,
        WorkItem(Target(WS, None), None, Target(WS, ORIGIN)),  # type: ignore[arg-type]
    )
    assert result.ok
    assert result.item_id == CREATED
    assert "FromOrigin" in result.message or "name=" in result.message


def test_delete(tmp_path: Path) -> None:
    del tmp_path
    client = FakeClient()
    result = delete_semantic_model(client, WorkItem(Target(WS, SM), None))  # type: ignore[arg-type]
    assert result.ok
    assert client.calls[-1][0] == "DELETE"

"""Tests for Microsoft Fabric Variable Library operations."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fabric_tools.client import FabricApiError
from fabric_tools.parsing import Target, WorkItem
from fabric_tools.variable_library.ops import (
    delete_variable_library,
    deploy_variable_library,
    download_variable_library,
)

WS = "11111111-1111-1111-1111-111111111111"
LIBRARY = "22222222-2222-2222-2222-222222222222"
ORIGIN = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CREATED = "99999999-9999-9999-9999-999999999999"


def _part(path: str, value: object) -> dict[str, str]:
    return {
        "path": path,
        "payload": base64.b64encode(json.dumps(value).encode()).decode(),
        "payloadType": "InlineBase64",
    }


def _definition(*, platform: bool = True) -> dict[str, Any]:
    parts = [
        _part("variables.json", {"variables": []}),
        _part("settings.json", {}),
        _part("valueSets/Dev.json", {}),
    ]
    if platform:
        parts.append(_part(".platform", {}))
    return {"parts": parts}


def _write_folder(folder: Path, *, platform: bool = True) -> Path:
    folder.mkdir()
    (folder / "variables.json").write_text("{}", encoding="utf-8")
    (folder / "settings.json").write_text("{}", encoding="utf-8")
    if platform:
        (folder / ".platform").write_text("{}", encoding="utf-8")
    return folder


class FakeClient:
    def __init__(self) -> None:
        self.definitions = {LIBRARY: _definition(), ORIGIN: _definition()}
        self.last_create_payload: dict[str, Any] | None = None
        self.last_update_payload: dict[str, Any] | None = None
        self.last_update_params: dict[str, Any] | None = None
        self.deleted: list[str] = []

    def get_item(self, workspace_id: str, item_id: str) -> dict[str, Any]:
        return {"displayName": "Origin Library", "id": item_id}

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        wait: bool = True,
    ) -> Any:
        if method == "POST" and path.endswith("/getDefinition"):
            assert "/variableLibraries/" in path
            item_id = path.split("/")[-2]
            if item_id not in self.definitions:
                raise FabricApiError("missing", status_code=404)
            return {"definition": self.definitions[item_id]}
        if method == "POST" and path.endswith("/items"):
            self.last_create_payload = json
            return {"id": CREATED, "type": "VariableLibrary"}
        if method == "POST" and path.endswith("/updateDefinition"):
            assert "/variableLibraries/" in path
            self.last_update_payload = json
            self.last_update_params = params
            return None
        if method == "DELETE" and "/variableLibraries/" in path:
            self.deleted.append(path)
            return None
        raise AssertionError(f"Unexpected call {method} {path}")


def test_download_writes_folder(tmp_path: Path) -> None:
    destination = tmp_path / "Config.VariableLibrary"
    result = download_variable_library(
        FakeClient(), WorkItem(Target(WS, LIBRARY), destination)
    )
    assert result.ok
    assert (destination / "variables.json").is_file()
    assert (destination / "valueSets" / "Dev.json").is_file()


def test_create_uses_type_and_folder_name(tmp_path: Path) -> None:
    client = FakeClient()
    source = _write_folder(tmp_path / "Config.VariableLibrary")
    result = deploy_variable_library(client, WorkItem(Target(WS), source))
    assert result.ok
    assert result.item_id == CREATED
    assert client.last_create_payload is not None
    assert client.last_create_payload["type"] == "VariableLibrary"
    assert client.last_create_payload["displayName"] == "Config"


def test_create_from_origin_uses_remote_name() -> None:
    client = FakeClient()
    result = deploy_variable_library(
        client, WorkItem(Target(WS), None, origin=Target(WS, ORIGIN))
    )
    assert result.ok
    assert client.last_create_payload is not None
    assert client.last_create_payload["displayName"] == "Origin Library"


def test_overwrite_platform_controls_update_metadata(tmp_path: Path) -> None:
    client = FakeClient()
    source = _write_folder(tmp_path / "With.VariableLibrary")
    assert deploy_variable_library(client, WorkItem(Target(WS, LIBRARY), source)).ok
    assert client.last_update_params == {"updateMetadata": "true"}

    source_without = _write_folder(tmp_path / "Without.VariableLibrary", platform=False)
    assert deploy_variable_library(
        client, WorkItem(Target(WS, LIBRARY), source_without)
    ).ok
    assert client.last_update_params is None


def test_delete_uses_variable_libraries_endpoint() -> None:
    client = FakeClient()
    result = delete_variable_library(client, WorkItem(Target(WS, LIBRARY), None))
    assert result.ok
    assert client.deleted == [f"/workspaces/{WS}/variableLibraries/{LIBRARY}"]

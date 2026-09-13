"""Tests for Microsoft Fabric Org App operations."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fabric_tools.client import FabricApiError
from fabric_tools.org_app.definition import PAYLOAD_TYPE
from fabric_tools.org_app.ops import (
    delete_org_app,
    deploy_org_app,
    download_org_app,
)
from fabric_tools.parsing import Target, WorkItem

WS = "11111111-1111-1111-1111-111111111111"
APP = "22222222-2222-2222-2222-222222222222"
ORIGIN = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CREATED = "99999999-9999-9999-9999-999999999999"


def _part(path: str, value: object) -> dict[str, str]:
    payload = json.dumps(value).encode()
    return {
        "path": path,
        "payload": base64.b64encode(payload).decode(),
        "payloadType": PAYLOAD_TYPE,
    }


def _definition(*, platform: bool = True) -> dict[str, Any]:
    parts = [_part("definition.json", {"elements": [{"id": "one"}]})]
    if platform:
        parts.append(_part(".platform", {"metadata": {"type": "OrgApp"}}))
    return {"parts": parts}


def _write_folder(folder: Path, *, platform: bool = True) -> Path:
    folder.mkdir()
    (folder / "definition.json").write_text(
        json.dumps({"elements": [{"id": "one"}]}),
        encoding="utf-8",
    )
    if platform:
        (folder / ".platform").write_text("{}", encoding="utf-8")
    return folder


class FakeClient:
    def __init__(self) -> None:
        self.definitions = {APP: _definition(), ORIGIN: _definition()}
        self.calls: list[tuple[str, str, dict[str, Any] | None, Any]] = []
        self.last_create_payload: dict[str, Any] | None = None
        self.last_update_payload: dict[str, Any] | None = None
        self.last_update_params: dict[str, Any] | None = None
        self.deleted: list[str] = []

    def get_item(self, workspace_id: str, item_id: str) -> dict[str, Any]:
        return {"displayName": "Origin App", "id": item_id, "workspaceId": workspace_id}

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        wait: bool = True,
    ) -> Any:
        self.calls.append((method, path, params, json))
        if method == "POST" and path.endswith("/getDefinition"):
            item_id = path.split("/")[-2]
            if item_id not in self.definitions:
                raise FabricApiError("missing", status_code=404)
            assert "/orgApps/" in path
            return {"definition": self.definitions[item_id]}
        if method == "POST" and path.endswith("/items"):
            self.last_create_payload = json
            return {"id": CREATED, "type": "OrgApp"}
        if method == "POST" and path.endswith("/updateDefinition"):
            assert "/orgApps/" in path
            self.last_update_payload = json
            self.last_update_params = params
            return None
        if method == "DELETE" and "/orgApps/" in path:
            self.deleted.append(path)
            return None
        raise AssertionError(f"Unexpected call {method} {path}")


def test_download_writes_folder(tmp_path: Path) -> None:
    client = FakeClient()
    destination = tmp_path / "Sales.OrgApp"
    result = download_org_app(
        client,
        WorkItem(Target(WS, APP), destination),  # type: ignore[arg-type]
    )
    assert result.ok
    assert (destination / "definition.json").is_file()
    assert (destination / ".platform").is_file()


def test_create_uses_org_app_type_and_folder_name(tmp_path: Path) -> None:
    client = FakeClient()
    source = _write_folder(tmp_path / "Sales.OrgApp")
    result = deploy_org_app(
        client,
        WorkItem(Target(WS), source),  # type: ignore[arg-type]
    )
    assert result.ok
    assert result.item_id == CREATED
    assert client.last_create_payload is not None
    assert client.last_create_payload["type"] == "OrgApp"
    assert client.last_create_payload["displayName"] == "Sales"


def test_create_from_origin_uses_remote_name() -> None:
    client = FakeClient()
    result = deploy_org_app(
        client,
        WorkItem(Target(WS), None, origin=Target(WS, ORIGIN)),  # type: ignore[arg-type]
    )
    assert result.ok
    assert client.last_create_payload is not None
    assert client.last_create_payload["displayName"] == "Origin App"


def test_overwrite_sets_update_metadata_for_platform(tmp_path: Path) -> None:
    client = FakeClient()
    source = _write_folder(tmp_path / "Sales.OrgApp")
    result = deploy_org_app(
        client,
        WorkItem(Target(WS, APP), source),  # type: ignore[arg-type]
    )
    assert result.ok
    assert client.last_update_payload is not None
    assert client.last_update_params == {"updateMetadata": "true"}


def test_overwrite_without_platform_skips_metadata(tmp_path: Path) -> None:
    client = FakeClient()
    source = _write_folder(tmp_path / "Sales.OrgApp", platform=False)
    result = deploy_org_app(
        client,
        WorkItem(Target(WS, APP), source),  # type: ignore[arg-type]
    )
    assert result.ok
    assert client.last_update_params is None


def test_delete_uses_org_apps_endpoint() -> None:
    client = FakeClient()
    result = delete_org_app(
        client,
        WorkItem(Target(WS, APP), None),  # type: ignore[arg-type]
    )
    assert result.ok
    assert client.deleted == [f"/workspaces/{WS}/orgApps/{APP}"]


def test_delete_requires_item_id() -> None:
    result = delete_org_app(
        FakeClient(),
        WorkItem(Target(WS), None),  # type: ignore[arg-type]
    )
    assert not result.ok

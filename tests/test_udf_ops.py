"""Tests for User Data Function download/deploy/delete ops with a fake client."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

from fabric_tools.parsing import Target, WorkItem
from fabric_tools.udf.definition import (
    DEFINITION_JSON_PATH,
    FUNCTION_APP_PATH,
    FUNCTIONS_JSON_PATH,
    PAYLOAD_TYPE,
    definition_json_from_definition,
)
from fabric_tools.udf.ops import (
    UdfAuthError,
    check_udf_user_auth,
    delete_udf,
    deploy_udf,
    download_udf,
)

WS = "11111111-1111-1111-1111-111111111111"
ORIGIN_ITEM = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TARGET_ITEM = "22222222-2222-2222-2222-222222222222"


def _definition_json(
    *,
    connected: list[dict[str, object]] | None = None,
) -> dict[str, Any]:
    return {
        "runtime": "PYTHON",
        "connectedDataSources": connected if connected is not None else [],
        "functions": [
            {"name": "hello", "description": "", "isPublicEndpointEnabled": True}
        ],
        "libraries": {"public": [], "private": []},
    }


def _part(path: str, payload: bytes) -> dict[str, str]:
    return {
        "path": path,
        "payload": base64.b64encode(payload).decode("ascii"),
        "payloadType": PAYLOAD_TYPE,
    }


def _udf_definition(
    *,
    connected: list[dict[str, object]] | None = None,
    app_source: str = "print('hello')\n",
) -> dict[str, Any]:
    return {
        "parts": [
            _part(
                DEFINITION_JSON_PATH,
                json.dumps(_definition_json(connected=connected)).encode("utf-8"),
            ),
            _part(FUNCTION_APP_PATH, app_source.encode("utf-8")),
            _part(FUNCTIONS_JSON_PATH, b"{}"),
        ]
    }


def _write_local_udf(
    folder: Path,
    *,
    connected: list[dict[str, object]] | None = None,
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "definition.json").write_text(
        json.dumps(_definition_json(connected=connected)),
        encoding="utf-8",
    )
    (folder / "function_app.py").write_text("print('local')\n", encoding="utf-8")
    resources = folder / "resources"
    resources.mkdir(exist_ok=True)
    (resources / "functions.json").write_text("{}", encoding="utf-8")
    return folder


class FakeClient:
    def __init__(
        self,
        *,
        definitions_by_item: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None, Any]] = []
        self.definitions_by_item = definitions_by_item or {}
        self.create_response = {
            "id": "99999999-9999-9999-9999-999999999999",
            "type": "UserDataFunction",
            "displayName": "Demo",
            "workspaceId": WS,
        }
        self.last_update_definition: dict[str, Any] | None = None

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
        if method == "GET" and "/userDataFunctions/" in path:
            item_id = path.rstrip("/").split("/")[-1]
            return {
                "id": item_id,
                "workspaceId": WS,
                "displayName": "Origin UDF",
                "type": "UserDataFunction",
            }
        if method == "POST" and path.endswith("/getDefinition"):
            item_id = path.split("/")[-2]
            definition = self.definitions_by_item.get(item_id) or _udf_definition()
            return {"definition": definition}
        if method == "POST" and path.endswith("/userDataFunctions"):
            return self.create_response
        if method == "POST" and path.endswith("/updateDefinition"):
            self.last_update_definition = json
            return None
        if method == "DELETE" and "/userDataFunctions/" in path:
            return None
        raise AssertionError(f"Unexpected call {method} {path}")


def test_download_writes_folder(tmp_path: Path) -> None:
    client = FakeClient(
        definitions_by_item={TARGET_ITEM: _udf_definition(app_source="print(1)\n")}
    )
    dest = tmp_path / "Out.UserDataFunction"
    item = WorkItem(Target(WS, TARGET_ITEM), dest)
    result = download_udf(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert (dest / "function_app.py").read_text(encoding="utf-8") == "print(1)\n"
    assert any(call[1].endswith("/getDefinition") for call in client.calls)


def test_deploy_create(tmp_path: Path) -> None:
    client = FakeClient()
    src = _write_local_udf(tmp_path / "Demo.UserDataFunction")
    item = WorkItem(Target(WS), src)
    result = deploy_udf(client, item, display_name="Demo")  # type: ignore[arg-type]
    assert result.ok
    assert result.item_id == "99999999-9999-9999-9999-999999999999"
    assert any(call[1].endswith("/userDataFunctions") for call in client.calls)


def test_deploy_overwrite_preserves_remote_connections(tmp_path: Path) -> None:
    remote_connected = [
        {
            "alias": "lh_target",
            "artifactId": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "artifactType": "Lakehouse",
            "workspaceId": WS,
        }
    ]
    client = FakeClient(
        definitions_by_item={
            TARGET_ITEM: _udf_definition(connected=remote_connected),
        }
    )
    src = _write_local_udf(
        tmp_path / "Demo.UserDataFunction",
        connected=[
            {
                "alias": "lh_local",
                "artifactId": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "artifactType": "Lakehouse",
                "workspaceId": WS,
            }
        ],
    )
    item = WorkItem(Target(WS, TARGET_ITEM), src)
    result = deploy_udf(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert "preserved remote connectedDataSources" in result.message
    assert client.last_update_definition is not None
    updated = definition_json_from_definition(
        client.last_update_definition["definition"]
    )
    assert updated["connectedDataSources"] == remote_connected


def test_deploy_origin_overwrite_strips_then_preserves() -> None:
    origin_connected = [
        {
            "alias": "lh_origin",
            "artifactId": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "artifactType": "Lakehouse",
            "workspaceId": WS,
        }
    ]
    target_connected = [
        {
            "alias": "lh_target",
            "artifactId": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "artifactType": "Lakehouse",
            "workspaceId": WS,
        }
    ]
    client = FakeClient(
        definitions_by_item={
            ORIGIN_ITEM: _udf_definition(connected=origin_connected),
            TARGET_ITEM: _udf_definition(connected=target_connected),
        }
    )
    item = WorkItem(
        Target(WS, TARGET_ITEM),
        None,
        origin=Target(WS, ORIGIN_ITEM),
    )
    result = deploy_udf(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert client.last_update_definition is not None
    updated = definition_json_from_definition(
        client.last_update_definition["definition"]
    )
    assert updated["connectedDataSources"] == target_connected


def test_delete_udf() -> None:
    client = FakeClient()
    item = WorkItem(Target(WS, TARGET_ITEM), None)
    result = delete_udf(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert client.calls[0][0] == "DELETE"
    assert "/userDataFunctions/" in client.calls[0][1]


def test_check_udf_user_auth_rejects_service_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AZURE_TENANT_ID", "t")
    monkeypatch.setenv("AZURE_CLIENT_ID", "c")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "s")
    with pytest.raises(UdfAuthError, match="service principal"):
        check_udf_user_auth()


def test_check_udf_user_auth_ok_without_sp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_TENANT_ID", raising=False)
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
    monkeypatch.delenv("AZURE_CLIENT_SECRET", raising=False)
    check_udf_user_auth()

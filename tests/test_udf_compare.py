"""Tests for User Data Function compare."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fabric_tools.parsing import Target, WorkItem
from fabric_tools.udf.compare import compare_udf
from fabric_tools.udf.definition import (
    DEFINITION_JSON_PATH,
    FUNCTION_APP_PATH,
    FUNCTIONS_JSON_PATH,
    PAYLOAD_TYPE,
)

WS = "11111111-1111-1111-1111-111111111111"
TARGET_ITEM = "22222222-2222-2222-2222-222222222222"


def _part(path: str, payload: bytes) -> dict[str, str]:
    return {
        "path": path,
        "payload": base64.b64encode(payload).decode("ascii"),
        "payloadType": PAYLOAD_TYPE,
    }


def _definition(app_source: str = "print('remote')\n") -> dict[str, Any]:
    definition_json = {
        "runtime": "PYTHON",
        "connectedDataSources": [],
        "functions": [],
        "libraries": {"public": [], "private": []},
    }
    return {
        "parts": [
            _part(DEFINITION_JSON_PATH, json.dumps(definition_json).encode("utf-8")),
            _part(FUNCTION_APP_PATH, app_source.encode("utf-8")),
            _part(FUNCTIONS_JSON_PATH, b"{}"),
        ]
    }


class FakeClient:
    def __init__(self, *, remote_app: str = "print('remote')\n") -> None:
        self.remote_app = remote_app

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        return {"id": workspace_id, "displayName": "WS"}

    def get_item(self, workspace_id: str, item_id: str) -> dict[str, Any]:
        return {
            "id": item_id,
            "workspaceId": workspace_id,
            "displayName": "Demo",
            "type": "UserDataFunction",
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
        if method == "POST" and path.endswith("/getDefinition"):
            return {"definition": _definition(self.remote_app)}
        raise AssertionError(f"Unexpected call {method} {path}")


def _write_local(folder: Path, app_source: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
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
    (folder / "function_app.py").write_text(app_source, encoding="utf-8")
    resources = folder / "resources"
    resources.mkdir()
    (resources / "functions.json").write_text("{}", encoding="utf-8")
    return folder


def test_compare_identical(tmp_path: Path) -> None:
    src = _write_local(tmp_path / "Demo.UserDataFunction", "print('remote')\n")
    client = FakeClient(remote_app="print('remote')\n")
    item = WorkItem(Target(WS, TARGET_ITEM), src)
    result = compare_udf(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert result.identical


def test_compare_differs(tmp_path: Path) -> None:
    src = _write_local(tmp_path / "Demo.UserDataFunction", "print('local')\n")
    client = FakeClient(remote_app="print('remote')\n")
    item = WorkItem(Target(WS, TARGET_ITEM), src)
    result = compare_udf(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert not result.identical
    assert "function_app.py" in result.diff_text

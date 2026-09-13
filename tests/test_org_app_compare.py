"""Tests for Microsoft Fabric Org App comparisons."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fabric_tools.org_app.compare import compare_org_app
from fabric_tools.org_app.definition import PAYLOAD_TYPE
from fabric_tools.parsing import Target, WorkItem

WS = "11111111-1111-1111-1111-111111111111"
APP = "22222222-2222-2222-2222-222222222222"
ORIGIN = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _definition(element_id: str, *, logical_id: str = "remote") -> dict[str, Any]:
    def part(path: str, value: object) -> dict[str, str]:
        return {
            "path": path,
            "payload": base64.b64encode(json.dumps(value).encode()).decode(),
            "payloadType": PAYLOAD_TYPE,
        }

    return {
        "parts": [
            part("definition.json", {"elements": [{"id": element_id}]}),
            part(".platform", {"logicalId": logical_id}),
        ]
    }


def _write_folder(folder: Path, element_id: str) -> Path:
    folder.mkdir()
    (folder / "definition.json").write_text(
        json.dumps({"elements": [{"id": element_id}]}),
        encoding="utf-8",
    )
    (folder / ".platform").write_text(
        json.dumps({"logicalId": "local"}),
        encoding="utf-8",
    )
    return folder


class FakeClient:
    def __init__(self, definitions: dict[str, dict[str, Any]]) -> None:
        self.definitions = definitions

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        return {"id": workspace_id, "displayName": "Dev"}

    def get_item(self, workspace_id: str, item_id: str) -> dict[str, Any]:
        return {
            "id": item_id,
            "workspaceId": workspace_id,
            "displayName": f"App {item_id[-4:]}",
            "type": "OrgApp",
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
            item_id = path.split("/")[-2]
            return {"definition": self.definitions[item_id]}
        raise AssertionError(f"Unexpected call {method} {path}")


def test_compare_identical_ignores_platform(tmp_path: Path) -> None:
    folder = _write_folder(tmp_path / "Sales.OrgApp", "one")
    client = FakeClient({APP: _definition("one", logical_id="different")})
    result = compare_org_app(
        client,
        WorkItem(Target(WS, APP), folder),  # type: ignore[arg-type]
    )
    assert result.ok
    assert result.identical
    assert result.diff_text == ""


def test_compare_reports_definition_diff(tmp_path: Path) -> None:
    folder = _write_folder(tmp_path / "Sales.OrgApp", "local")
    client = FakeClient({APP: _definition("remote")})
    result = compare_org_app(
        client,
        WorkItem(Target(WS, APP), folder),  # type: ignore[arg-type]
    )
    assert result.ok
    assert not result.identical
    assert "local" in result.diff_text
    assert "remote" in result.diff_text
    assert "logicalId" not in result.diff_text


def test_compare_origin_to_target() -> None:
    client = FakeClient(
        {
            ORIGIN: _definition("origin"),
            APP: _definition("target"),
        }
    )
    result = compare_org_app(
        client,
        WorkItem(
            Target(WS, APP),
            None,
            origin=Target(WS, ORIGIN),
        ),  # type: ignore[arg-type]
    )
    assert result.ok
    assert not result.identical
    assert "origin" in result.diff_text
    assert "target" in result.diff_text

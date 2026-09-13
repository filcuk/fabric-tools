"""Tests for Microsoft Fabric Variable Library comparisons."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fabric_tools.parsing import Target, WorkItem
from fabric_tools.variable_library.compare import compare_variable_library

WS = "11111111-1111-1111-1111-111111111111"
LIBRARY = "22222222-2222-2222-2222-222222222222"
ORIGIN = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _definition(value: str, *, platform: str = "remote") -> dict[str, Any]:
    def part(path: str, body: object) -> dict[str, str]:
        return {
            "path": path,
            "payload": base64.b64encode(json.dumps(body).encode()).decode(),
            "payloadType": "InlineBase64",
        }

    return {
        "parts": [
            part("variables.json", {"Region": value}),
            part("settings.json", {"active": "Dev"}),
            part("valueSets/Dev.json", {"Region": value}),
            part(".platform", {"logicalId": platform}),
        ]
    }


def _write_folder(folder: Path, value: str) -> Path:
    folder.mkdir()
    (folder / "variables.json").write_text(
        json.dumps({"Region": value}), encoding="utf-8"
    )
    (folder / "settings.json").write_text(
        json.dumps({"active": "Dev"}), encoding="utf-8"
    )
    values = folder / "valueSets"
    values.mkdir()
    (values / "Dev.json").write_text(json.dumps({"Region": value}), encoding="utf-8")
    (folder / ".platform").write_text(
        json.dumps({"logicalId": "local"}), encoding="utf-8"
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
            "displayName": f"Library {item_id[-4:]}",
            "type": "VariableLibrary",
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
            return {"definition": self.definitions[path.split("/")[-2]]}
        raise AssertionError(f"Unexpected call {method} {path}")


def test_compare_identical_ignores_platform(tmp_path: Path) -> None:
    folder = _write_folder(tmp_path / "Config.VariableLibrary", "west")
    result = compare_variable_library(
        FakeClient({LIBRARY: _definition("west", platform="different")}),
        WorkItem(Target(WS, LIBRARY), folder),
    )
    assert result.ok
    assert result.identical
    assert result.diff_text == ""


def test_compare_reports_value_set_diff(tmp_path: Path) -> None:
    folder = _write_folder(tmp_path / "Config.VariableLibrary", "local")
    result = compare_variable_library(
        FakeClient({LIBRARY: _definition("remote")}),
        WorkItem(Target(WS, LIBRARY), folder),
    )
    assert result.ok
    assert not result.identical
    assert "local" in result.diff_text
    assert "remote" in result.diff_text
    assert "logicalId" not in result.diff_text


def test_compare_origin_to_target() -> None:
    result = compare_variable_library(
        FakeClient(
            {
                ORIGIN: _definition("origin"),
                LIBRARY: _definition("target"),
            }
        ),
        WorkItem(Target(WS, LIBRARY), None, origin=Target(WS, ORIGIN)),
    )
    assert result.ok
    assert not result.identical
    assert "origin" in result.diff_text
    assert "target" in result.diff_text

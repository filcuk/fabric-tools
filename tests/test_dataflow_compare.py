"""Tests for Dataflow Gen2 compare."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fabric_tools.client import FabricApiError
from fabric_tools.dataflow.compare import compare_dataflow
from fabric_tools.dataflow.definition import FORMAT_VERSION, PAYLOAD_TYPE
from fabric_tools.parsing import Target, WorkItem

WS = "11111111-1111-1111-1111-111111111111"
DF = "22222222-2222-2222-2222-222222222222"
ORIGIN = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _metadata(**overrides: object) -> dict[str, Any]:
    data: dict[str, Any] = {
        "formatVersion": FORMAT_VERSION,
        "name": "Sales",
        "queryGroups": [],
        "queriesMetadata": {},
        "connections": [],
    }
    data.update(overrides)
    return data


def _part(path: str, raw: bytes) -> dict[str, str]:
    return {
        "path": path,
        "payload": base64.b64encode(raw).decode("ascii"),
        "payloadType": PAYLOAD_TYPE,
    }


def _definition(
    *,
    name: str = "Sales",
    mashup: str = "section Section1;\nshared Q1 = 1;\n",
) -> dict[str, Any]:
    return {
        "parts": [
            _part(
                "queryMetadata.json",
                json.dumps(_metadata(name=name)).encode("utf-8"),
            ),
            _part("mashup.pq", mashup.encode("utf-8")),
        ]
    }


def _write_folder(
    folder: Path,
    *,
    name: str = "Sales",
    mashup: str = "section Section1;\nshared Q1 = 1;\n",
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "queryMetadata.json").write_text(
        json.dumps(_metadata(name=name), indent=2) + "\n",
        encoding="utf-8",
    )
    (folder / "mashup.pq").write_text(mashup, encoding="utf-8")
    return folder


class FakeClient:
    def __init__(self, definitions: dict[str, dict[str, Any]]) -> None:
        self.definitions = definitions

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        return {"id": workspace_id, "displayName": "Dev"}

    def get_item(self, workspace_id: str, item_id: str) -> dict[str, Any]:
        if item_id not in self.definitions:
            raise FabricApiError("missing", status_code=404)
        return {
            "id": item_id,
            "workspaceId": workspace_id,
            "displayName": "Sales",
            "type": "Dataflow",
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
            if item_id not in self.definitions:
                raise FabricApiError("missing", status_code=404)
            return {"definition": self.definitions[item_id]}
        raise AssertionError(f"Unexpected call {method} {path}")


def test_compare_identical(tmp_path: Path) -> None:
    mashup = "section Section1;\nshared Q1 = 1;\n"
    folder = _write_folder(tmp_path / "Sales.Dataflow", mashup=mashup)
    client = FakeClient({DF: _definition(mashup=mashup)})
    item = WorkItem(Target(WS, DF), folder)
    result = compare_dataflow(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert result.identical
    assert result.diff_text == ""


def test_compare_reports_diff(tmp_path: Path) -> None:
    folder = _write_folder(
        tmp_path / "Sales.Dataflow",
        mashup="section Section1;\nshared Q2 = 2;\n",
    )
    client = FakeClient({DF: _definition(mashup="section Section1;\nshared Q1 = 1;\n")})
    item = WorkItem(Target(WS, DF), folder)
    result = compare_dataflow(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert not result.identical
    assert "Q1" in result.diff_text
    assert "Q2" in result.diff_text


def test_compare_origin_to_target() -> None:
    client = FakeClient(
        {
            ORIGIN: _definition(name="A", mashup="section Section1;\nshared A = 1;\n"),
            DF: _definition(name="B", mashup="section Section1;\nshared B = 2;\n"),
        }
    )
    item = WorkItem(Target(WS, DF), None, origin=Target(WS, ORIGIN))
    result = compare_dataflow(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert not result.identical
    assert "A" in result.diff_text or "B" in result.diff_text

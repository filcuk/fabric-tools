"""Tests for semantic model compare."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fabric_tools.definition_parts import PAYLOAD_TYPE
from fabric_tools.parsing import Target, WorkItem
from fabric_tools.semantic_model.compare import compare_semantic_model

WS = "11111111-1111-1111-1111-111111111111"
SM = "22222222-2222-2222-2222-222222222222"
ORIGIN = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _part(path: str, raw: bytes) -> dict[str, str]:
    return {
        "path": path,
        "payload": base64.b64encode(raw).decode("ascii"),
        "payloadType": PAYLOAD_TYPE,
    }


def _definition(model: str) -> dict[str, Any]:
    return {
        "format": "TMDL",
        "parts": [
            _part("definition.pbism", json.dumps({"version": "5.0"}).encode()),
            _part("definition/model.tmdl", model.encode()),
        ],
    }


def _write_local(folder: Path, model: str) -> Path:
    (folder / "definition").mkdir(parents=True)
    (folder / "definition.pbism").write_text(
        json.dumps({"version": "5.0"}), encoding="utf-8"
    )
    (folder / "definition" / "model.tmdl").write_text(model, encoding="utf-8")
    return folder


class FakeClient:
    def __init__(self, definitions: dict[str, dict[str, Any]]) -> None:
        self.definitions = definitions

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        wait: bool = True,
    ) -> Any:
        del method, params, json, wait
        item_id = path.split("/")[-2]
        return {"definition": self.definitions[item_id]}

    def get_item(self, workspace_id: str, item_id: str) -> dict[str, Any]:
        del workspace_id
        return {
            "id": item_id,
            "displayName": f"Item-{item_id[:8]}",
            "type": "SemanticModel",
        }

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        return {"id": workspace_id, "displayName": "WS"}


def test_compare_identical(tmp_path: Path) -> None:
    folder = _write_local(tmp_path / "Sales.SemanticModel", "model Sales\n")
    client = FakeClient({SM: _definition("model Sales\n")})
    result = compare_semantic_model(
        client,
        WorkItem(Target(WS, SM), folder),  # type: ignore[arg-type]
    )
    assert result.ok
    assert result.identical
    assert result.diff_text == ""


def test_compare_diff(tmp_path: Path) -> None:
    folder = _write_local(tmp_path / "Sales.SemanticModel", "model Local\n")
    client = FakeClient({SM: _definition("model Remote\n")})
    result = compare_semantic_model(
        client,
        WorkItem(Target(WS, SM), folder),  # type: ignore[arg-type]
    )
    assert result.ok
    assert not result.identical
    assert "model Remote" in result.diff_text
    assert "model Local" in result.diff_text


def test_compare_origin(tmp_path: Path) -> None:
    del tmp_path
    client = FakeClient(
        {
            SM: _definition("model Target\n"),
            ORIGIN: _definition("model Origin\n"),
        }
    )
    result = compare_semantic_model(
        client,
        WorkItem(Target(WS, SM), None, Target(WS, ORIGIN)),  # type: ignore[arg-type]
    )
    assert result.ok
    assert not result.identical

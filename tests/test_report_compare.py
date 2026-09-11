"""Tests for report compare."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fabric_tools.client import FabricApiError
from fabric_tools.definition_parts import PAYLOAD_TYPE
from fabric_tools.parsing import Target, WorkItem
from fabric_tools.report.compare import compare_report

WS = "11111111-1111-1111-1111-111111111111"
REPORT = "22222222-2222-2222-2222-222222222222"
ORIGIN = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _part(path: str, raw: bytes) -> dict[str, str]:
    return {
        "path": path,
        "payload": base64.b64encode(raw).decode("ascii"),
        "payloadType": PAYLOAD_TYPE,
    }


def _definition(body: str = '{"version": "1.0"}\n') -> dict[str, Any]:
    pbir = json.dumps(
        {
            "version": "4.0",
            "datasetReference": {
                "byConnection": {
                    "connectionString": (
                        "semanticmodelid=77777777-7777-7777-7777-777777777777"
                    )
                }
            },
        }
    ).encode("utf-8")
    return {
        "format": "PBIR",
        "parts": [
            _part("definition.pbir", pbir),
            _part("definition/report.json", body.encode("utf-8")),
        ],
    }


def _write_local(folder: Path, *, body: str = '{"version": "1.0"}\n') -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "definition.pbir").write_bytes(
        json.dumps(
            {
                "version": "4.0",
                "datasetReference": {
                    "byConnection": {
                        "connectionString": (
                            "semanticmodelid=77777777-7777-7777-7777-777777777777"
                        )
                    }
                },
            }
        ).encode("utf-8")
    )
    (folder / "definition").mkdir(parents=True, exist_ok=True)
    (folder / "definition" / "report.json").write_text(body, encoding="utf-8")
    return folder


class FakeClient:
    def __init__(self, *, remote_body: str = '{"version": "1.0"}\n') -> None:
        self.remote_body = remote_body

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        wait: bool = True,
    ) -> Any:
        del params, json, wait
        if method == "POST" and path.endswith("/getDefinition"):
            item_id = path.split("/")[-2]
            body = self.remote_body
            if item_id == ORIGIN:
                body = '{"origin": true}\n'
            return {"definition": _definition(body)}
        raise FabricApiError(f"unexpected {method} {path}")

    def get_item(self, workspace_id: str, item_id: str) -> dict[str, Any]:
        del workspace_id
        return {"id": item_id, "displayName": "Sales", "type": "Report"}

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        return {"id": workspace_id, "displayName": "WS"}


def test_compare_identical(tmp_path: Path) -> None:
    local = _write_local(tmp_path / "Sales.Report")
    result = compare_report(
        FakeClient(),
        WorkItem(Target(WS, REPORT), local),  # type: ignore[arg-type]
    )
    assert result.ok
    assert result.identical


def test_compare_diff(tmp_path: Path) -> None:
    local = _write_local(tmp_path / "Sales.Report", body='{"version": "2.0"}\n')
    result = compare_report(
        FakeClient(),
        WorkItem(Target(WS, REPORT), local),  # type: ignore[arg-type]
    )
    assert result.ok
    assert not result.identical
    assert result.diff_text


def test_compare_rejects_pbix(tmp_path: Path) -> None:
    pbix = tmp_path / "Sales.pbix"
    pbix.write_bytes(b"x")
    result = compare_report(
        FakeClient(),
        WorkItem(Target(WS, REPORT), pbix),  # type: ignore[arg-type]
    )
    assert not result.ok
    assert ".pbix" in (result.error or "")


def test_compare_origin(tmp_path: Path) -> None:
    del tmp_path
    result = compare_report(
        FakeClient(),
        WorkItem(Target(WS, REPORT), None, origin=Target(WS, ORIGIN)),  # type: ignore[arg-type]
    )
    assert result.ok
    assert not result.identical

"""Tests for Microsoft Fabric Environment comparisons."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from fabric_tools.environment.compare import compare_environment
from fabric_tools.parsing import Target, WorkItem

WS = "11111111-1111-1111-1111-111111111111"
ENV = "22222222-2222-2222-2222-222222222222"


def _definition(value: str, *, platform: str = "remote") -> dict[str, Any]:
    def part(path: str, payload: bytes) -> dict[str, str]:
        return {
            "path": path,
            "payload": base64.b64encode(payload).decode(),
            "payloadType": "InlineBase64",
        }

    return {
        "parts": [
            part("Setting/Sparkcompute.yml", f"value: {value}\n".encode()),
            part(".platform", f'{{"logicalId":"{platform}"}}'.encode()),
        ]
    }


def _write_folder(folder: Path, value: str) -> Path:
    (folder / "Setting").mkdir(parents=True)
    (folder / "Setting" / "Sparkcompute.yml").write_text(f"value: {value}\n")
    (folder / ".platform").write_text('{"logicalId":"local"}')
    return folder


class FakeClient:
    def __init__(self, definition: dict[str, Any]) -> None:
        self.definition = definition

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        return {"id": workspace_id, "displayName": "Dev"}

    def get_item(self, workspace_id: str, item_id: str) -> dict[str, Any]:
        return {"id": item_id, "displayName": "Dev Env", "type": "Environment"}

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        wait: bool = True,
    ) -> Any:
        return {"definition": self.definition}


def test_compare_identical_ignores_platform(tmp_path: Path) -> None:
    folder = _write_folder(tmp_path / "Dev.Environment", "same")
    result = compare_environment(
        FakeClient(_definition("same", platform="different")),
        WorkItem(Target(WS, ENV), folder),  # type: ignore[arg-type]
    )
    assert result.ok
    assert result.identical


def test_compare_reports_definition_diff(tmp_path: Path) -> None:
    folder = _write_folder(tmp_path / "Dev.Environment", "local")
    result = compare_environment(
        FakeClient(_definition("remote")),
        WorkItem(Target(WS, ENV), folder),  # type: ignore[arg-type]
    )
    assert result.ok
    assert not result.identical
    assert "local" in result.diff_text
    assert "remote" in result.diff_text
    assert "logicalId" not in result.diff_text

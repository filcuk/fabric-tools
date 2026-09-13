"""Tests for Microsoft Fabric Environment operations."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from fabric_tools.environment.ops import (
    delete_environment,
    deploy_environment,
    download_environment,
)
from fabric_tools.parsing import Target, WorkItem

WS = "11111111-1111-1111-1111-111111111111"
ENV = "22222222-2222-2222-2222-222222222222"
CREATED = "99999999-9999-9999-9999-999999999999"


def _part(path: str, payload: bytes) -> dict[str, str]:
    return {
        "path": path,
        "payload": base64.b64encode(payload).decode(),
        "payloadType": "InlineBase64",
    }


class FakeClient:
    def __init__(self) -> None:
        self.last_create_payload: dict[str, Any] | None = None
        self.last_update_params: dict[str, Any] | None = None
        self.deleted: list[str] = []

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        wait: bool = True,
    ) -> Any:
        if path.endswith("/getDefinition"):
            return {
                "definition": {
                    "parts": [_part("Setting/Sparkcompute.yml", b"runtime: 1\n")]
                }
            }
        if method == "POST" and path.endswith("/items"):
            self.last_create_payload = json
            return {"id": CREATED, "type": "Environment"}
        if path.endswith("/updateDefinition"):
            self.last_update_params = params
            return None
        if method == "DELETE":
            self.deleted.append(path)
            return None
        raise AssertionError(f"Unexpected call {method} {path}")


def _write_environment(folder: Path, *, platform: bool = True) -> Path:
    (folder / "Setting").mkdir(parents=True)
    (folder / "Setting" / "Sparkcompute.yml").write_text("runtime: 1\n")
    if platform:
        (folder / ".platform").write_text("{}")
    return folder


def test_download_writes_folder(tmp_path: Path) -> None:
    destination = tmp_path / "Dev.Environment"
    result = download_environment(
        FakeClient(),
        WorkItem(Target(WS, ENV), destination),  # type: ignore[arg-type]
    )
    assert result.ok
    assert (destination / "Setting/Sparkcompute.yml").is_file()


def test_create_uses_environment_type_and_folder_name(tmp_path: Path) -> None:
    client = FakeClient()
    result = deploy_environment(
        client,
        WorkItem(  # type: ignore[arg-type]
            Target(WS), _write_environment(tmp_path / "Dev.Environment")
        ),
    )
    assert result.ok
    assert result.item_id == CREATED
    assert client.last_create_payload is not None
    assert client.last_create_payload["type"] == "Environment"
    assert client.last_create_payload["displayName"] == "Dev"


def test_overwrite_platform_controls_update_metadata(tmp_path: Path) -> None:
    client = FakeClient()
    deploy_environment(
        client,
        WorkItem(  # type: ignore[arg-type]
            Target(WS, ENV), _write_environment(tmp_path / "With.Environment")
        ),
    )
    assert client.last_update_params == {"updateMetadata": "true"}
    client = FakeClient()
    deploy_environment(
        client,
        WorkItem(  # type: ignore[arg-type]
            Target(WS, ENV),
            _write_environment(tmp_path / "Without.Environment", platform=False),
        ),
    )
    assert client.last_update_params is None


def test_delete_uses_environments_endpoint() -> None:
    client = FakeClient()
    result = delete_environment(
        client,
        WorkItem(Target(WS, ENV), None),  # type: ignore[arg-type]
    )
    assert result.ok
    assert client.deleted == [f"/workspaces/{WS}/environments/{ENV}"]

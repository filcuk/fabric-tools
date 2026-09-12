"""Tests for DataPipeline download/deploy/delete ops with a fake Fabric client."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fabric_tools.client import FabricApiError
from fabric_tools.parsing import Target, WorkItem
from fabric_tools.pipeline.definition import PAYLOAD_TYPE
from fabric_tools.pipeline.ops import (
    delete_pipeline,
    deploy_pipeline,
    download_pipeline,
)

WS = "11111111-1111-1111-1111-111111111111"
PL = "22222222-2222-2222-2222-222222222222"
ORIGIN = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CREATED = "99999999-9999-9999-9999-999999999999"


def _content(**overrides: object) -> dict[str, Any]:
    data: dict[str, Any] = {
        "properties": {
            "description": "etl",
            "activities": [
                {
                    "name": "Wait_1",
                    "type": "Wait",
                    "dependsOn": [],
                    "typeProperties": {"waitTimeInSeconds": 10},
                }
            ],
        }
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
    wait_seconds: int = 10,
    with_platform: bool = True,
    with_schedules: bool = False,
) -> dict[str, Any]:
    content = _content()
    content["properties"]["activities"][0]["typeProperties"]["waitTimeInSeconds"] = (
        wait_seconds
    )
    parts = [_part("pipeline-content.json", json.dumps(content).encode("utf-8"))]
    if with_platform:
        parts.append(
            _part(
                ".platform",
                json.dumps(
                    {"metadata": {"type": "DataPipeline", "displayName": "ETL"}}
                ).encode("utf-8"),
            )
        )
    if with_schedules:
        parts.append(_part(".schedules", b'{"schedules":[]}\n'))
    return {"parts": parts}


def _write_local_pipeline(
    folder: Path,
    *,
    wait_seconds: int = 10,
    with_platform: bool = True,
    with_schedules: bool = False,
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    content = _content()
    content["properties"]["activities"][0]["typeProperties"]["waitTimeInSeconds"] = (
        wait_seconds
    )
    (folder / "pipeline-content.json").write_text(
        json.dumps(content, indent=2) + "\n",
        encoding="utf-8",
    )
    if with_platform:
        (folder / ".platform").write_text(
            json.dumps({"metadata": {"type": "DataPipeline", "displayName": "ETL"}}),
            encoding="utf-8",
        )
    if with_schedules:
        (folder / ".schedules").write_text('{"schedules":[]}\n', encoding="utf-8")
    return folder


class FakeClient:
    def __init__(
        self,
        *,
        definitions_by_item: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None, Any]] = []
        self.definitions_by_item = definitions_by_item or {
            PL: _definition(wait_seconds=10),
            ORIGIN: _definition(wait_seconds=20),
        }
        self.create_response = {
            "id": CREATED,
            "type": "DataPipeline",
            "displayName": "ETL",
            "workspaceId": WS,
        }
        self.last_create_payload: dict[str, Any] | None = None
        self.last_update_definition: dict[str, Any] | None = None
        self.last_update_params: dict[str, Any] | None = None
        self.deleted: list[tuple[str, str]] = []

    def get_item(self, workspace_id: str, item_id: str) -> dict[str, Any]:
        return {
            "id": item_id,
            "workspaceId": workspace_id,
            "displayName": "Origin Pipeline",
            "type": "DataPipeline",
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
        self.calls.append((method, path, params, json))
        if method == "POST" and path.endswith("/getDefinition"):
            item_id = path.split("/")[-2]
            if item_id not in self.definitions_by_item:
                raise FabricApiError("missing", status_code=404)
            assert "/dataPipelines/" in path
            return {"definition": self.definitions_by_item[item_id]}
        if method == "POST" and path.endswith("/items"):
            self.last_create_payload = json
            return self.create_response
        if method == "POST" and path.endswith("/updateDefinition"):
            assert "/dataPipelines/" in path
            self.last_update_definition = json
            self.last_update_params = params
            return None
        if method == "DELETE" and "/dataPipelines/" in path:
            item_id = path.rstrip("/").split("/")[-1]
            self.deleted.append((path.split("/")[2], item_id))
            return None
        raise AssertionError(f"Unexpected call {method} {path}")


def test_download_writes_folder(tmp_path: Path) -> None:
    client = FakeClient()
    dest = tmp_path / "out.DataPipeline"
    item = WorkItem(Target(WS, PL), dest)
    result = download_pipeline(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert (dest / "pipeline-content.json").is_file()
    assert any(call[1].endswith("/getDefinition") for call in client.calls)
    assert any("/dataPipelines/" in call[1] for call in client.calls)


def test_deploy_create_from_folder(tmp_path: Path) -> None:
    client = FakeClient()
    src = _write_local_pipeline(tmp_path / "ETL.DataPipeline")
    item = WorkItem(Target(WS), src)
    result = deploy_pipeline(client, item, display_name="ETL")  # type: ignore[arg-type]
    assert result.ok
    assert result.item_id == CREATED
    assert client.last_create_payload is not None
    assert client.last_create_payload["type"] == "DataPipeline"
    assert client.last_create_payload["displayName"] == "ETL"
    assert "parts" in client.last_create_payload["definition"]


def test_deploy_create_default_name_from_folder(tmp_path: Path) -> None:
    client = FakeClient()
    src = _write_local_pipeline(tmp_path / "MyPipe.DataPipeline")
    item = WorkItem(Target(WS), src)
    result = deploy_pipeline(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert client.last_create_payload is not None
    assert client.last_create_payload["displayName"] == "MyPipe"


def test_deploy_create_from_origin() -> None:
    client = FakeClient()
    item = WorkItem(Target(WS), None, origin=Target(WS, ORIGIN))
    result = deploy_pipeline(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert result.item_id == CREATED
    assert client.last_create_payload is not None
    assert client.last_create_payload["displayName"] == "Origin Pipeline"


def test_deploy_overwrite_from_folder(tmp_path: Path) -> None:
    client = FakeClient()
    src = _write_local_pipeline(tmp_path / "ETL.DataPipeline")
    item = WorkItem(Target(WS, PL), src)
    result = deploy_pipeline(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert "updated" in result.message
    assert client.last_update_definition is not None
    assert client.last_update_params == {"updateMetadata": "true"}


def test_deploy_overwrite_without_platform_skips_metadata(tmp_path: Path) -> None:
    client = FakeClient()
    src = _write_local_pipeline(tmp_path / "ETL.DataPipeline", with_platform=False)
    item = WorkItem(Target(WS, PL), src)
    result = deploy_pipeline(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert client.last_update_params is None


def test_deploy_overwrite_from_origin() -> None:
    client = FakeClient()
    item = WorkItem(Target(WS, PL), None, origin=Target(WS, ORIGIN))
    result = deploy_pipeline(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert client.last_update_definition is not None


def test_delete_pipeline() -> None:
    client = FakeClient()
    item = WorkItem(Target(WS, PL), None)
    result = delete_pipeline(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert client.deleted == [(WS, PL)]


def test_delete_requires_item_id() -> None:
    client = FakeClient()
    item = WorkItem(Target(WS), None)
    result = delete_pipeline(client, item)  # type: ignore[arg-type]
    assert not result.ok


def test_download_rejects_bad_destination(tmp_path: Path) -> None:
    client = FakeClient()
    dest = tmp_path / "out.json"
    item = WorkItem(Target(WS, PL), dest)
    result = download_pipeline(client, item)  # type: ignore[arg-type]
    assert not result.ok
    assert "Unsupported pipeline path" in result.message


def test_download_default_omits_schedules(tmp_path: Path) -> None:
    client = FakeClient(definitions_by_item={PL: _definition(with_schedules=True)})
    dest = tmp_path / "out.DataPipeline"
    dest.mkdir()
    (dest / ".schedules").write_text(
        '{"schedules":[{"name":"stale"}]}\n', encoding="utf-8"
    )
    item = WorkItem(Target(WS, PL), dest)
    result = download_pipeline(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert (dest / "pipeline-content.json").is_file()
    assert not (dest / ".schedules").exists()


def test_download_include_schedules(tmp_path: Path) -> None:
    client = FakeClient(definitions_by_item={PL: _definition(with_schedules=True)})
    dest = tmp_path / "out.DataPipeline"
    item = WorkItem(Target(WS, PL), dest)
    result = download_pipeline(client, item, include_schedules=True)  # type: ignore[arg-type]
    assert result.ok
    assert (dest / ".schedules").is_file()


def test_deploy_overwrite_default_preserves_remote_schedules(tmp_path: Path) -> None:
    client = FakeClient(
        definitions_by_item={
            PL: _definition(wait_seconds=10, with_schedules=True),
        }
    )
    # Make remote schedules distinct so we can assert they were reattached.
    remote_schedules = _part(".schedules", b'{"schedules":[{"name":"remote"}]}\n')
    client.definitions_by_item[PL]["parts"] = [
        p for p in client.definitions_by_item[PL]["parts"] if p["path"] != ".schedules"
    ] + [remote_schedules]

    src = _write_local_pipeline(tmp_path / "ETL.DataPipeline", with_schedules=True)
    item = WorkItem(Target(WS, PL), src)
    result = deploy_pipeline(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert "preserved remote schedules" in result.message
    assert client.last_update_definition is not None
    paths = {
        part["path"] for part in client.last_update_definition["definition"]["parts"]
    }
    assert "pipeline-content.json" in paths
    assert ".schedules" in paths
    schedules = next(
        p
        for p in client.last_update_definition["definition"]["parts"]
        if p["path"] == ".schedules"
    )
    assert b"remote" in base64.b64decode(schedules["payload"])
    # Source schedules must not be sent when include_schedules is false.
    assert client.calls  # getDefinition for preserve + updateDefinition
    get_calls = [c for c in client.calls if str(c[1]).endswith("/getDefinition")]
    assert len(get_calls) == 1


def test_deploy_overwrite_include_schedules_from_folder(tmp_path: Path) -> None:
    client = FakeClient(
        definitions_by_item={PL: _definition(wait_seconds=10, with_schedules=True)}
    )
    src = _write_local_pipeline(tmp_path / "ETL.DataPipeline", with_schedules=True)
    # Distinct local schedules content
    (src / ".schedules").write_text(
        '{"schedules":[{"name":"local"}]}\n', encoding="utf-8"
    )
    item = WorkItem(Target(WS, PL), src)
    result = deploy_pipeline(client, item, include_schedules=True)  # type: ignore[arg-type]
    assert result.ok
    assert "preserved remote schedules" not in result.message
    assert client.last_update_definition is not None
    schedules = next(
        p
        for p in client.last_update_definition["definition"]["parts"]
        if p["path"] == ".schedules"
    )
    assert b"local" in base64.b64decode(schedules["payload"])
    # No preserve getDefinition when including source schedules.
    get_calls = [c for c in client.calls if str(c[1]).endswith("/getDefinition")]
    assert get_calls == []


def test_deploy_create_default_omits_schedules(tmp_path: Path) -> None:
    client = FakeClient()
    src = _write_local_pipeline(tmp_path / "ETL.DataPipeline", with_schedules=True)
    item = WorkItem(Target(WS), src)
    result = deploy_pipeline(client, item, display_name="ETL")  # type: ignore[arg-type]
    assert result.ok
    assert client.last_create_payload is not None
    paths = {part["path"] for part in client.last_create_payload["definition"]["parts"]}
    assert ".schedules" not in paths
    assert "pipeline-content.json" in paths


def test_deploy_include_schedules_from_origin() -> None:
    client = FakeClient(
        definitions_by_item={ORIGIN: _definition(wait_seconds=20, with_schedules=True)}
    )
    item = WorkItem(Target(WS, PL), None, origin=Target(WS, ORIGIN))
    # Target also needs a definition for FakeClient get_item, but include path
    # should not fetch target getDefinition for preserve.
    client.definitions_by_item[PL] = _definition(wait_seconds=10, with_schedules=True)
    result = deploy_pipeline(client, item, include_schedules=True)  # type: ignore[arg-type]
    assert result.ok
    assert client.last_update_definition is not None
    paths = {
        part["path"] for part in client.last_update_definition["definition"]["parts"]
    }
    assert ".schedules" in paths
    get_calls = [c for c in client.calls if str(c[1]).endswith("/getDefinition")]
    # Only origin getDefinition, not target preserve fetch.
    assert len(get_calls) == 1
    assert ORIGIN in get_calls[0][1]


def test_deploy_overwrite_from_origin_preserves_target_schedules() -> None:
    client = FakeClient(
        definitions_by_item={
            ORIGIN: _definition(wait_seconds=20, with_schedules=True),
            PL: _definition(wait_seconds=10, with_schedules=True),
        }
    )
    # Distinct target schedules
    client.definitions_by_item[PL]["parts"] = [
        p for p in client.definitions_by_item[PL]["parts"] if p["path"] != ".schedules"
    ] + [_part(".schedules", b'{"schedules":[{"name":"target"}]}\n')]

    item = WorkItem(Target(WS, PL), None, origin=Target(WS, ORIGIN))
    result = deploy_pipeline(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert "preserved remote schedules" in result.message
    assert client.last_update_definition is not None
    schedules = next(
        p
        for p in client.last_update_definition["definition"]["parts"]
        if p["path"] == ".schedules"
    )
    assert b"target" in base64.b64decode(schedules["payload"])
    # Origin getDefinition + target preserve getDefinition
    get_calls = [c for c in client.calls if str(c[1]).endswith("/getDefinition")]
    assert len(get_calls) == 2

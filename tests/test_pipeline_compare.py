"""Tests for DataPipeline compare."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fabric_tools.client import FabricApiError
from fabric_tools.parsing import Target, WorkItem
from fabric_tools.pipeline.compare import compare_pipeline
from fabric_tools.pipeline.definition import PAYLOAD_TYPE

WS = "11111111-1111-1111-1111-111111111111"
PL = "22222222-2222-2222-2222-222222222222"
ORIGIN = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _content(
    *, wait_seconds: int = 10, activity_name: str = "Wait_1"
) -> dict[str, Any]:
    return {
        "properties": {
            "description": "etl",
            "activities": [
                {
                    "name": activity_name,
                    "type": "Wait",
                    "dependsOn": [],
                    "typeProperties": {"waitTimeInSeconds": wait_seconds},
                }
            ],
        }
    }


def _part(path: str, raw: bytes) -> dict[str, str]:
    return {
        "path": path,
        "payload": base64.b64encode(raw).decode("ascii"),
        "payloadType": PAYLOAD_TYPE,
    }


def _definition(
    *,
    wait_seconds: int = 10,
    activity_name: str = "Wait_1",
    with_platform: bool = False,
    schedules: bytes | None = None,
) -> dict[str, Any]:
    parts = [
        _part(
            "pipeline-content.json",
            json.dumps(
                _content(wait_seconds=wait_seconds, activity_name=activity_name)
            ).encode("utf-8"),
        )
    ]
    if with_platform:
        parts.append(
            _part(
                ".platform",
                json.dumps(
                    {
                        "metadata": {
                            "type": "DataPipeline",
                            "logicalId": f"logical-{wait_seconds}",
                        }
                    }
                ).encode("utf-8"),
            )
        )
    if schedules is not None:
        parts.append(_part(".schedules", schedules))
    return {"parts": parts}


def _write_folder(
    folder: Path,
    *,
    wait_seconds: int = 10,
    activity_name: str = "Wait_1",
    schedules: str | None = None,
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pipeline-content.json").write_text(
        json.dumps(
            _content(wait_seconds=wait_seconds, activity_name=activity_name),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if schedules is not None:
        (folder / ".schedules").write_text(schedules, encoding="utf-8")
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
            "displayName": "ETL",
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
        if method == "POST" and path.endswith("/getDefinition"):
            item_id = path.split("/")[-2]
            if item_id not in self.definitions:
                raise FabricApiError("missing", status_code=404)
            assert "/dataPipelines/" in path
            return {"definition": self.definitions[item_id]}
        raise AssertionError(f"Unexpected call {method} {path}")


def test_compare_identical(tmp_path: Path) -> None:
    folder = _write_folder(tmp_path / "ETL.DataPipeline", wait_seconds=10)
    client = FakeClient({PL: _definition(wait_seconds=10)})
    item = WorkItem(Target(WS, PL), folder)
    result = compare_pipeline(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert result.identical
    assert result.diff_text == ""


def test_compare_reports_diff(tmp_path: Path) -> None:
    folder = _write_folder(tmp_path / "ETL.DataPipeline", wait_seconds=99)
    client = FakeClient({PL: _definition(wait_seconds=10)})
    item = WorkItem(Target(WS, PL), folder)
    result = compare_pipeline(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert not result.identical
    assert "10" in result.diff_text
    assert "99" in result.diff_text


def test_compare_ignores_platform_logical_id(tmp_path: Path) -> None:
    folder = _write_folder(tmp_path / "ETL.DataPipeline", wait_seconds=10)
    (folder / ".platform").write_text(
        json.dumps({"metadata": {"type": "DataPipeline", "logicalId": "local-id"}}),
        encoding="utf-8",
    )
    client = FakeClient({PL: _definition(wait_seconds=10, with_platform=True)})
    item = WorkItem(Target(WS, PL), folder)
    result = compare_pipeline(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert result.identical


def test_compare_origin_to_target() -> None:
    client = FakeClient(
        {
            ORIGIN: _definition(activity_name="OriginWait"),
            PL: _definition(activity_name="TargetWait"),
        }
    )
    item = WorkItem(Target(WS, PL), None, origin=Target(WS, ORIGIN))
    result = compare_pipeline(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert not result.identical
    assert "OriginWait" in result.diff_text or "TargetWait" in result.diff_text


def test_compare_default_omits_schedules(tmp_path: Path) -> None:
    folder = _write_folder(
        tmp_path / "ETL.DataPipeline",
        wait_seconds=10,
        schedules='{"schedules":[{"name":"local"}]}\n',
    )
    client = FakeClient(
        {
            PL: _definition(
                wait_seconds=10,
                schedules=b'{"schedules":[{"name":"remote"}]}\n',
            )
        }
    )
    item = WorkItem(Target(WS, PL), folder)
    default = compare_pipeline(client, item)  # type: ignore[arg-type]
    assert default.ok
    assert default.identical
    assert default.diff_text == ""

    included = compare_pipeline(client, item, include_schedules=True)  # type: ignore[arg-type]
    assert included.ok
    assert not included.identical


def test_compare_include_schedules_identical(tmp_path: Path) -> None:
    schedules = '{"schedules":[{"name":"same"}]}\n'
    folder = _write_folder(
        tmp_path / "ETL.DataPipeline",
        wait_seconds=10,
        schedules=schedules,
    )
    client = FakeClient(
        {PL: _definition(wait_seconds=10, schedules=schedules.encode("utf-8"))}
    )
    item = WorkItem(Target(WS, PL), folder)
    result = compare_pipeline(client, item, include_schedules=True)  # type: ignore[arg-type]
    assert result.ok
    assert result.identical
    assert result.diff_text == ""


def test_compare_missing_local_folder(tmp_path: Path) -> None:
    client = FakeClient({PL: _definition(wait_seconds=10)})
    item = WorkItem(Target(WS, PL), tmp_path / "missing.DataPipeline")
    result = compare_pipeline(client, item)  # type: ignore[arg-type]
    assert not result.ok
    assert result.error is not None


def test_compare_missing_remote(tmp_path: Path) -> None:
    folder = _write_folder(tmp_path / "ETL.DataPipeline", wait_seconds=10)
    client = FakeClient({})
    item = WorkItem(Target(WS, PL), folder)
    result = compare_pipeline(client, item)  # type: ignore[arg-type]
    assert not result.ok
    assert result.error is not None
    assert "failed to fetch" in result.error


def test_compare_non_utf8_remote_payload(tmp_path: Path) -> None:
    folder = _write_folder(tmp_path / "ETL.DataPipeline", wait_seconds=10)
    bad = {
        "parts": [
            _part("pipeline-content.json", b"\xff\xfe"),
        ]
    }
    client = FakeClient({PL: bad})
    item = WorkItem(Target(WS, PL), folder)
    result = compare_pipeline(client, item)  # type: ignore[arg-type]
    assert not result.ok
    assert result.error is not None
    assert "UTF-8" in result.error


def test_compare_requires_target_item() -> None:
    client = FakeClient({})
    item = WorkItem(Target(WS), None)
    result = compare_pipeline(client, item)  # type: ignore[arg-type]
    assert not result.ok
    assert result.error is not None
    assert "workspace:artifact" in result.error

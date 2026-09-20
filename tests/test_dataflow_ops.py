"""Tests for Dataflow Gen2 download/deploy/delete ops with a fake Fabric client."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fabric_tools.client import FabricApiError
from fabric_tools.dataflow.definition import FORMAT_VERSION, PAYLOAD_TYPE
from fabric_tools.dataflow.ops import (
    delete_dataflow,
    deploy_dataflow,
    download_dataflow,
)
from fabric_tools.parsing import Target, WorkItem

WS = "11111111-1111-1111-1111-111111111111"
DF = "22222222-2222-2222-2222-222222222222"
ORIGIN = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CREATED = "99999999-9999-9999-9999-999999999999"


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
    with_platform: bool = True,
) -> dict[str, Any]:
    parts = [
        _part(
            "queryMetadata.json",
            json.dumps(_metadata(name=name)).encode("utf-8"),
        ),
        _part("mashup.pq", mashup.encode("utf-8")),
    ]
    if with_platform:
        parts.append(
            _part(
                ".platform",
                json.dumps(
                    {"metadata": {"type": "Dataflow", "displayName": name}}
                ).encode("utf-8"),
            )
        )
    return {"parts": parts}


def _write_local_dataflow(
    folder: Path,
    *,
    name: str = "Sales",
    mashup: str = "section Section1;\nshared Q1 = 1;\n",
    with_platform: bool = True,
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "queryMetadata.json").write_text(
        json.dumps(_metadata(name=name), indent=2) + "\n",
        encoding="utf-8",
    )
    (folder / "mashup.pq").write_text(mashup, encoding="utf-8")
    if with_platform:
        (folder / ".platform").write_text(
            json.dumps({"metadata": {"type": "Dataflow", "displayName": name}}),
            encoding="utf-8",
        )
    return folder


class FakeClient:
    def __init__(
        self,
        *,
        definitions_by_item: dict[str, dict[str, Any]] | None = None,
        apply_changes_error: FabricApiError | None = None,
    ) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None, Any]] = []
        self.definitions_by_item = definitions_by_item or {
            DF: _definition(name="Sales"),
            ORIGIN: _definition(name="OriginFlow", mashup="section Section1;\n"),
        }
        self.create_response = {
            "id": CREATED,
            "type": "Dataflow",
            "displayName": "Sales",
            "workspaceId": WS,
        }
        self.last_create_payload: dict[str, Any] | None = None
        self.last_update_definition: dict[str, Any] | None = None
        self.last_update_params: dict[str, Any] | None = None
        self.deleted: list[tuple[str, str]] = []
        self.apply_changes: list[tuple[str, str]] = []
        self.apply_changes_error = apply_changes_error

    def get_item(self, workspace_id: str, item_id: str) -> dict[str, Any]:
        return {
            "id": item_id,
            "workspaceId": workspace_id,
            "displayName": "Origin Flow",
            "type": "Dataflow",
        }

    def run_dataflow_apply_changes(self, workspace_id: str, dataflow_id: str) -> Any:
        path = (
            f"/workspaces/{workspace_id}/dataflows/{dataflow_id}"
            "/jobs/applyChanges/instances"
        )
        self.calls.append(("POST", path, None, None))
        self.apply_changes.append((workspace_id, dataflow_id))
        if self.apply_changes_error is not None:
            raise self.apply_changes_error
        return None

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
            assert "/dataflows/" in path
            return {"definition": self.definitions_by_item[item_id]}
        if method == "POST" and path.endswith("/items"):
            self.last_create_payload = json
            return self.create_response
        if method == "POST" and path.endswith("/updateDefinition"):
            assert "/dataflows/" in path
            self.last_update_definition = json
            self.last_update_params = params
            return None
        if method == "DELETE" and "/dataflows/" in path:
            item_id = path.rstrip("/").split("/")[-1]
            self.deleted.append((path.split("/")[2], item_id))
            return None
        raise AssertionError(f"Unexpected call {method} {path}")


def test_download_writes_folder(tmp_path: Path) -> None:
    client = FakeClient()
    dest = tmp_path / "out.Dataflow"
    item = WorkItem(Target(WS, DF), dest)
    result = download_dataflow(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert (dest / "queryMetadata.json").is_file()
    assert (dest / "mashup.pq").is_file()
    assert any(call[1].endswith("/getDefinition") for call in client.calls)


def test_deploy_create_from_folder(tmp_path: Path) -> None:
    client = FakeClient()
    src = _write_local_dataflow(tmp_path / "Sales.Dataflow")
    item = WorkItem(Target(WS), src)
    result = deploy_dataflow(client, item, display_name="Sales")  # type: ignore[arg-type]
    assert result.ok
    assert result.item_id == CREATED
    assert client.last_create_payload is not None
    assert client.last_create_payload["type"] == "Dataflow"
    assert client.last_create_payload["displayName"] == "Sales"
    assert "parts" in client.last_create_payload["definition"]


def test_deploy_create_default_name_from_folder(tmp_path: Path) -> None:
    client = FakeClient()
    src = _write_local_dataflow(tmp_path / "MyFlow.Dataflow")
    item = WorkItem(Target(WS), src)
    result = deploy_dataflow(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert client.last_create_payload is not None
    assert client.last_create_payload["displayName"] == "MyFlow"


def test_deploy_create_from_origin() -> None:
    client = FakeClient()
    item = WorkItem(Target(WS), None, origin=Target(WS, ORIGIN))
    result = deploy_dataflow(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert result.item_id == CREATED
    assert client.last_create_payload is not None
    assert client.last_create_payload["displayName"] == "Origin Flow"


def test_deploy_overwrite_from_folder(tmp_path: Path) -> None:
    client = FakeClient()
    src = _write_local_dataflow(tmp_path / "Sales.Dataflow")
    item = WorkItem(Target(WS, DF), src)
    result = deploy_dataflow(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert "updated" in result.message
    assert client.last_update_definition is not None
    assert client.last_update_params == {"updateMetadata": "true"}


def test_deploy_overwrite_without_platform_skips_metadata(tmp_path: Path) -> None:
    client = FakeClient()
    src = _write_local_dataflow(tmp_path / "Sales.Dataflow", with_platform=False)
    item = WorkItem(Target(WS, DF), src)
    result = deploy_dataflow(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert client.last_update_params is None


def test_deploy_overwrite_from_origin() -> None:
    client = FakeClient()
    item = WorkItem(Target(WS, DF), None, origin=Target(WS, ORIGIN))
    result = deploy_dataflow(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert client.last_update_definition is not None


def test_delete_dataflow() -> None:
    client = FakeClient()
    item = WorkItem(Target(WS, DF), None)
    result = delete_dataflow(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert client.deleted == [(WS, DF)]


def test_delete_requires_item_id() -> None:
    client = FakeClient()
    item = WorkItem(Target(WS), None)
    result = delete_dataflow(client, item)  # type: ignore[arg-type]
    assert not result.ok


def test_download_appends_kind_suffix_for_stem_destination(tmp_path: Path) -> None:
    client = FakeClient()
    dest = tmp_path / "out.json"
    item = WorkItem(Target(WS, DF), dest)
    # ops still call detect; stem destinations are normalized by detect.
    result = download_dataflow(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert (tmp_path / "out.json.Dataflow" / "queryMetadata.json").is_file()


def test_deploy_create_applies_guid_map_to_mashup(tmp_path: Path) -> None:
    lh_src = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    lh_dst = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    mashup = f'section Section1;\nshared Q1 = "{lh_src}";\n'
    src = _write_local_dataflow(tmp_path / "Sales.Dataflow", mashup=mashup)
    client = FakeClient()
    item = WorkItem(Target(WS), src)
    result = deploy_dataflow(
        client, item, display_name="Sales", guid_map={lh_src: lh_dst}
    )  # type: ignore[arg-type]
    assert result.ok
    assert "remapped 1 GUID(s)" in result.message
    assert client.last_create_payload is not None
    parts = {
        p["path"]: base64.b64decode(p["payload"]).decode("utf-8")
        for p in client.last_create_payload["definition"]["parts"]
    }
    assert lh_dst in parts["mashup.pq"]
    assert lh_src not in parts["mashup.pq"]
    assert lh_src in (src / "mashup.pq").read_text(encoding="utf-8")


def test_deploy_publish_after_create(tmp_path: Path) -> None:
    client = FakeClient()
    src = _write_local_dataflow(tmp_path / "Sales.Dataflow")
    item = WorkItem(Target(WS), src)
    result = deploy_dataflow(client, item, display_name="Sales", publish=True)  # type: ignore[arg-type]
    assert result.ok
    assert "(published)" in result.message
    assert client.apply_changes == [(WS, CREATED)]


def test_deploy_publish_after_overwrite(tmp_path: Path) -> None:
    client = FakeClient()
    src = _write_local_dataflow(tmp_path / "Sales.Dataflow")
    item = WorkItem(Target(WS, DF), src)
    result = deploy_dataflow(client, item, publish=True)  # type: ignore[arg-type]
    assert result.ok
    assert "(published)" in result.message
    assert client.apply_changes == [(WS, DF)]


def test_deploy_publish_failure_keeps_definition_applied(tmp_path: Path) -> None:
    client = FakeClient(
        apply_changes_error=FabricApiError("apply failed", status_code=400)
    )
    src = _write_local_dataflow(tmp_path / "Sales.Dataflow")
    item = WorkItem(Target(WS, DF), src)
    result = deploy_dataflow(client, item, publish=True)  # type: ignore[arg-type]
    assert not result.ok
    assert "updated" in result.message
    assert "publish (Apply Changes) failed" in result.message
    assert client.last_update_definition is not None
    assert client.apply_changes == [(WS, DF)]


def test_deploy_without_publish_skips_apply_changes(tmp_path: Path) -> None:
    client = FakeClient()
    src = _write_local_dataflow(tmp_path / "Sales.Dataflow")
    item = WorkItem(Target(WS, DF), src)
    result = deploy_dataflow(client, item)  # type: ignore[arg-type]
    assert result.ok
    assert "(published)" not in result.message
    assert client.apply_changes == []

"""Tests for cross-workspace GUID map load and apply."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from fabric_tools.guid_map import (
    GuidMapError,
    apply_guid_map_to_definition,
    load_guid_map,
    replace_guids_in_text,
    resolve_guid_maps,
)
from fabric_tools.pipeline.definition import PAYLOAD_TYPE

SRC = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
DST = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
SRC_UPPER = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
OTHER = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _part(path: str, raw: bytes) -> dict[str, str]:
    return {
        "path": path,
        "payload": base64.b64encode(raw).decode("ascii"),
        "payloadType": PAYLOAD_TYPE,
    }


def test_load_guid_map_normalizes_case(tmp_path: Path) -> None:
    path = tmp_path / "map.json"
    path.write_text(json.dumps({SRC_UPPER: DST}), encoding="utf-8")
    mapping = load_guid_map(path)
    assert mapping == {SRC: DST}


def test_load_guid_map_rejects_empty(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(GuidMapError, match="empty"):
        load_guid_map(path)


def test_load_guid_map_rejects_bad_guid(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"not-a-guid": DST}), encoding="utf-8")
    with pytest.raises(GuidMapError, match="invalid GUID"):
        load_guid_map(path)


def test_resolve_guid_maps_broadcast(tmp_path: Path) -> None:
    path = tmp_path / "map.json"
    path.write_text(json.dumps({SRC: DST}), encoding="utf-8")
    specs = resolve_guid_maps([str(path)], 3)
    assert len(specs) == 3
    assert all(s is not None and s.mapping == {SRC: DST} for s in specs)


def test_resolve_guid_maps_count_mismatch(tmp_path: Path) -> None:
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps({SRC: DST}), encoding="utf-8")
    b.write_text(json.dumps({SRC: OTHER}), encoding="utf-8")
    with pytest.raises(GuidMapError, match="mismatch"):
        resolve_guid_maps([str(a), str(b)], 3)


def test_replace_guids_case_insensitive() -> None:
    text = f'notebookId="{SRC_UPPER}" workspaceId="{OTHER}"'
    out, count = replace_guids_in_text(text, {SRC: DST})
    assert count == 1
    assert DST in out
    assert OTHER in out
    assert SRC_UPPER not in out


def test_apply_guid_map_skips_platform_and_does_not_mutate() -> None:
    content = {
        "properties": {
            "activities": [
                {
                    "name": "Notebook1",
                    "type": "TridentNotebook",
                    "typeProperties": {
                        "notebookId": SRC,
                        "workspaceId": OTHER,
                    },
                }
            ]
        }
    }
    platform = {"metadata": {"type": "DataPipeline", "logicalId": SRC}}
    definition = {
        "parts": [
            _part("pipeline-content.json", json.dumps(content).encode("utf-8")),
            _part(".platform", json.dumps(platform).encode("utf-8")),
        ]
    }
    original_payload = definition["parts"][0]["payload"]

    rewritten, count = apply_guid_map_to_definition(definition, {SRC: DST})
    assert count == 1
    assert definition["parts"][0]["payload"] == original_payload

    new_content = json.loads(
        base64.b64decode(rewritten["parts"][0]["payload"]).decode("utf-8")
    )
    assert (
        new_content["properties"]["activities"][0]["typeProperties"]["notebookId"]
        == DST
    )
    new_platform = json.loads(
        base64.b64decode(rewritten["parts"][1]["payload"]).decode("utf-8")
    )
    assert new_platform["metadata"]["logicalId"] == SRC

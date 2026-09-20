"""Tests for Microsoft Fabric Org App definition packing."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from fabric_tools.org_app.definition import (
    DefinitionError,
    definition_has_platform,
    definition_to_diff_text,
    detect_org_app_path,
    display_name_from_path,
    folder_to_diff_text,
    pack_definition,
    unpack_definition,
    validate_local_org_app,
)


def _write_folder(
    folder: Path,
    *,
    definition: object | None = None,
    platform: object | None = None,
) -> Path:
    folder.mkdir(parents=True)
    body = definition if definition is not None else {"elements": [{"id": "one"}]}
    (folder / "definition.json").write_text(json.dumps(body), encoding="utf-8")
    if platform is not None:
        (folder / ".platform").write_text(json.dumps(platform), encoding="utf-8")
    return folder


def test_detect_suffix_and_bare_folder(tmp_path: Path) -> None:
    suffixed = tmp_path / "Sales.OrgApp"
    suffixed.mkdir()
    bare = _write_folder(tmp_path / "bare")
    assert detect_org_app_path(suffixed) == suffixed
    assert detect_org_app_path(bare) == bare
    assert display_name_from_path(suffixed) == "Sales"
    assert display_name_from_path(tmp_path / "sales.orgapp") == "sales"
    assert detect_org_app_path(tmp_path / "myApp") == tmp_path / "myApp.OrgApp"


def test_validate_rejects_missing_or_invalid_elements(tmp_path: Path) -> None:
    missing = tmp_path / "Missing.OrgApp"
    missing.mkdir()
    with pytest.raises(DefinitionError, match="definition.json"):
        validate_local_org_app(missing)

    invalid = _write_folder(tmp_path / "Invalid.OrgApp", definition={"elements": {}})
    with pytest.raises(DefinitionError, match="elements"):
        validate_local_org_app(invalid)


def test_validate_rejects_non_string_schema(tmp_path: Path) -> None:
    folder = _write_folder(
        tmp_path / "InvalidSchema.OrgApp",
        definition={"$schema": 1, "elements": []},
    )
    with pytest.raises(DefinitionError, match=r"\$schema"):
        validate_local_org_app(folder)


def test_pack_unpack_round_trip(tmp_path: Path) -> None:
    folder = _write_folder(
        tmp_path / "Sales.OrgApp",
        definition={"$schema": "https://example/schema", "elements": []},
        platform={"metadata": {"type": "OrgApp"}},
    )
    definition = pack_definition(folder)
    assert definition_has_platform(definition)
    assert {part["path"] for part in definition["parts"]} == {
        "definition.json",
        ".platform",
    }

    destination = tmp_path / "Restored.OrgApp"
    assert unpack_definition(definition, destination) == destination
    assert json.loads((destination / "definition.json").read_text())["elements"] == []
    assert (destination / ".platform").is_file()


def test_unpack_rejects_missing_definition() -> None:
    payload = base64.b64encode(b"{}").decode("ascii")
    with pytest.raises(DefinitionError, match="definition.json"):
        unpack_definition(
            {
                "parts": [
                    {
                        "path": ".platform",
                        "payload": payload,
                        "payloadType": "InlineBase64",
                    }
                ]
            },
            "unused.OrgApp",
        )


def test_diff_is_sorted_and_excludes_platform(tmp_path: Path) -> None:
    folder = _write_folder(
        tmp_path / "Sales.OrgApp",
        definition={"elements": [], "z": 1, "a": 2},
        platform={"logicalId": "local"},
    )
    packed = pack_definition(folder)
    packed["parts"][1]["payload"] = base64.b64encode(
        json.dumps({"logicalId": "remote"}).encode()
    ).decode()
    local_text = folder_to_diff_text(folder)
    remote_text = definition_to_diff_text(packed)
    assert local_text == remote_text
    assert local_text.index('"a"') < local_text.index('"z"')
    assert "logicalId" not in local_text

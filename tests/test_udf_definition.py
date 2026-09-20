"""Tests for User Data Function definition pack/unpack."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from fabric_tools.udf.definition import (
    DEFINITION_JSON_PATH,
    FUNCTION_APP_PATH,
    FUNCTIONS_JSON_PATH,
    PAYLOAD_TYPE,
    DefinitionError,
    definition_has_platform,
    definition_json_from_definition,
    detect_udf_folder,
    display_name_from_path,
    merge_remote_connections,
    pack_definition,
    replace_definition_json_part,
    strip_connected_data_sources,
    unpack_definition,
    validate_local_udf,
)


def _minimal_definition_json(
    *,
    connected: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "$schema": (
            "https://developer.microsoft.com/json-schemas/fabric/item/"
            "userDataFunction/definition/1.1.0/schema.json"
        ),
        "runtime": "PYTHON",
        "connectedDataSources": connected if connected is not None else [],
        "functions": [
            {"name": "hello", "description": "", "isPublicEndpointEnabled": True}
        ],
        "libraries": {"public": [], "private": []},
    }


def _write_udf_folder(
    folder: Path,
    *,
    definition_name: str = "definition.json",
    app_name: str = "function_app.py",
    connected: list[dict[str, object]] | None = None,
    with_platform: bool = False,
    with_wheel: bool = False,
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / definition_name).write_text(
        json.dumps(_minimal_definition_json(connected=connected)),
        encoding="utf-8",
    )
    (folder / app_name).write_text(
        "import fabric.functions as fn\n\nudf = fn.UserDataFunctions()\n",
        encoding="utf-8",
    )
    resources = folder / "resources"
    resources.mkdir(exist_ok=True)
    (resources / "functions.json").write_text("{}", encoding="utf-8")
    if with_platform:
        (folder / ".platform").write_text(
            json.dumps({"version": "2.0", "type": "UserDataFunction"}),
            encoding="utf-8",
        )
    if with_wheel:
        private = folder / "privateLibraries"
        private.mkdir(exist_ok=True)
        (private / "custom.whl").write_bytes(b"wheel-bytes")
    return folder


def test_pack_unpack_roundtrip(tmp_path: Path) -> None:
    folder = _write_udf_folder(
        tmp_path / "Demo.UserDataFunction",
        with_platform=True,
        with_wheel=True,
    )
    assert display_name_from_path(folder) == "Demo"
    validate_local_udf(folder)

    definition = pack_definition(folder)
    paths = {part["path"] for part in definition["parts"]}
    assert DEFINITION_JSON_PATH in paths
    assert FUNCTION_APP_PATH in paths
    assert FUNCTIONS_JSON_PATH in paths
    assert ".platform" in paths
    assert "privateLibraries/custom.whl" in paths
    assert definition_has_platform(definition)

    out = tmp_path / "Restored.UserDataFunction"
    unpack_definition(definition, out)
    assert (out / "function_app.py").is_file()
    assert (out / "definition.json").is_file()
    assert (out / "resources" / "functions.json").is_file()
    assert (out / ".platform").is_file()
    assert (out / "privateLibraries" / "custom.whl").read_bytes() == b"wheel-bytes"


def test_pack_accepts_git_alias_filenames(tmp_path: Path) -> None:
    folder = _write_udf_folder(
        tmp_path / "Aliased.UserDataFunction",
        definition_name="definitions.json",
        app_name="function-app.py",
    )
    definition = pack_definition(folder)
    paths = {part["path"] for part in definition["parts"]}
    assert paths == {
        DEFINITION_JSON_PATH,
        FUNCTION_APP_PATH,
        FUNCTIONS_JSON_PATH,
    }


def test_missing_required_part(tmp_path: Path) -> None:
    folder = tmp_path / "Bad.UserDataFunction"
    folder.mkdir()
    (folder / "function_app.py").write_text("x=1\n", encoding="utf-8")
    with pytest.raises(DefinitionError, match="definition.json"):
        validate_local_udf(folder)


def test_detect_appends_suffix_for_empty_bare_folder(tmp_path: Path) -> None:
    path = tmp_path / "not-a-udf"
    path.mkdir()
    assert detect_udf_folder(path) == tmp_path / "not-a-udf.UserDataFunction"
    with pytest.raises(DefinitionError, match="UDF folder not found"):
        validate_local_udf(path)


def test_detect_keeps_contentful_bare_folder(tmp_path: Path) -> None:
    bare = _write_udf_folder(tmp_path / "Helpers")
    assert detect_udf_folder(bare) == bare
    assert validate_local_udf(bare) == bare


def test_merge_remote_connections_replaces_list() -> None:
    source = _minimal_definition_json(
        connected=[{"alias": "src", "artifactId": "a", "artifactType": "Lakehouse"}]
    )
    remote = _minimal_definition_json(
        connected=[{"alias": "tgt", "artifactId": "b", "artifactType": "Warehouse"}]
    )
    merged, preserved = merge_remote_connections(source, remote)
    assert preserved is True
    assert merged["connectedDataSources"] == remote["connectedDataSources"]
    assert source["connectedDataSources"][0]["alias"] == "src"


def test_strip_connected_data_sources() -> None:
    data = _minimal_definition_json(
        connected=[{"alias": "x", "artifactId": "a", "artifactType": "Lakehouse"}]
    )
    stripped = strip_connected_data_sources(data)
    assert stripped["connectedDataSources"] == []
    assert data["connectedDataSources"]


def test_replace_definition_json_part_roundtrip() -> None:
    raw = json.dumps(_minimal_definition_json()).encode("utf-8")
    definition = {
        "parts": [
            {
                "path": DEFINITION_JSON_PATH,
                "payload": base64.b64encode(raw).decode("ascii"),
                "payloadType": PAYLOAD_TYPE,
            }
        ]
    }
    updated = _minimal_definition_json(
        connected=[{"alias": "n", "artifactId": "id", "artifactType": "Lakehouse"}]
    )
    new_def = replace_definition_json_part(definition, updated)
    parsed = definition_json_from_definition(new_def)
    assert parsed["connectedDataSources"][0]["alias"] == "n"

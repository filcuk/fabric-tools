"""Tests for Microsoft Fabric Variable Library definition packing."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from fabric_tools.variable_library.definition import (
    DefinitionError,
    definition_has_platform,
    definition_to_diff_text,
    detect_variable_library_path,
    display_name_from_path,
    folder_to_diff_text,
    pack_definition,
    unpack_definition,
    validate_local_variable_library,
)


def _write_folder(folder: Path, *, legacy: bool = False) -> Path:
    folder.mkdir(parents=True)
    (folder / "variables.json").write_text(
        json.dumps({"variables": [{"name": "Region"}]}), encoding="utf-8"
    )
    (folder / "settings.json").write_text(
        json.dumps({"activeValueSet": "Dev"}), encoding="utf-8"
    )
    values = folder / ("valueSet" if legacy else "valueSets")
    values.mkdir()
    (values / "Dev.json").write_text(json.dumps({"Region": "west"}), encoding="utf-8")
    (folder / ".platform").write_text("{}", encoding="utf-8")
    return folder


def test_detect_suffix_bare_and_display_name(tmp_path: Path) -> None:
    suffixed = tmp_path / "Config.VariableLibrary"
    suffixed.mkdir()
    bare = _write_folder(tmp_path / "bare")
    assert detect_variable_library_path(suffixed) == suffixed
    assert detect_variable_library_path(bare) == bare
    assert display_name_from_path(suffixed) == "Config"
    assert display_name_from_path(tmp_path / "x.variablelibrary") == "x"


def test_validate_requires_both_object_files(tmp_path: Path) -> None:
    folder = tmp_path / "Broken.VariableLibrary"
    folder.mkdir()
    (folder / "variables.json").write_text("[]", encoding="utf-8")
    with pytest.raises(DefinitionError, match="settings.json"):
        validate_local_variable_library(folder)
    (folder / "settings.json").write_text("{}", encoding="utf-8")
    with pytest.raises(DefinitionError, match="expected a JSON object"):
        validate_local_variable_library(folder)


def test_pack_normalizes_legacy_value_set_and_round_trips(tmp_path: Path) -> None:
    folder = _write_folder(tmp_path / "Config.VariableLibrary", legacy=True)
    definition = pack_definition(folder)
    assert definition_has_platform(definition)
    assert {part["path"] for part in definition["parts"]} == {
        "variables.json",
        "settings.json",
        "valueSets/Dev.json",
        ".platform",
    }
    destination = tmp_path / "Restored.VariableLibrary"
    unpack_definition(definition, destination)
    assert (destination / "valueSets" / "Dev.json").is_file()
    assert not (destination / "valueSet").exists()


def test_unpack_accepts_legacy_remote_path(tmp_path: Path) -> None:
    def part(path: str, value: object) -> dict[str, str]:
        return {
            "path": path,
            "payload": base64.b64encode(json.dumps(value).encode()).decode(),
            "payloadType": "InlineBase64",
        }

    definition = {
        "parts": [
            part("variables.json", {}),
            part("settings.json", {}),
            part("valueSet/Prod.json", {"Region": "east"}),
        ]
    }
    destination = tmp_path / "Restored.VariableLibrary"
    unpack_definition(definition, destination)
    assert (destination / "valueSets" / "Prod.json").is_file()


def test_diff_pretty_sorts_json_paths_and_excludes_platform(tmp_path: Path) -> None:
    folder = _write_folder(tmp_path / "Config.VariableLibrary")
    packed = pack_definition(folder)
    local = folder_to_diff_text(folder)
    remote = definition_to_diff_text(packed)
    assert local == remote
    assert ".platform" not in local
    assert local.index("--- settings.json") < local.index("--- valueSets/Dev.json")
    assert local.index("--- valueSets/Dev.json") < local.index("--- variables.json")

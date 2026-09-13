"""Tests for Microsoft Fabric Environment definition packing."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from fabric_tools.environment.definition import (
    DefinitionError,
    definition_has_platform,
    definition_to_diff_text,
    detect_environment_path,
    display_name_from_path,
    folder_to_diff_text,
    pack_definition,
    unpack_definition,
    validate_local_environment,
)


def _write_environment(folder: Path) -> Path:
    (folder / "Setting").mkdir(parents=True)
    (folder / "Libraries" / "CustomLibraries").mkdir(parents=True)
    (folder / "Setting" / "Sparkcompute.yml").write_text(
        "runtime:\r\n  version: 1\r\n", encoding="utf-8"
    )
    (folder / "Libraries" / "CustomLibraries" / "custom.whl").write_bytes(b"\x00\x01")
    (folder / ".platform").write_text('{"z": 1}', encoding="utf-8")
    return folder


def test_detect_suffix_and_bare_folder(tmp_path: Path) -> None:
    suffixed = tmp_path / "Dev.Environment"
    suffixed.mkdir()
    bare = tmp_path / "bare"
    (bare / "Libraries").mkdir(parents=True)
    assert detect_environment_path(suffixed) == suffixed
    assert detect_environment_path(bare) == bare
    assert display_name_from_path(suffixed) == "Dev"
    assert display_name_from_path(tmp_path / "dev.environment") == "dev"


def test_validate_rejects_empty_folder(tmp_path: Path) -> None:
    folder = tmp_path / "Empty.Environment"
    folder.mkdir()
    with pytest.raises(DefinitionError, match="no definition content"):
        validate_local_environment(folder)


def test_pack_unpack_recursive_binary_round_trip(tmp_path: Path) -> None:
    source = _write_environment(tmp_path / "Dev.Environment")
    definition = pack_definition(source)
    assert definition_has_platform(definition)
    assert {part["path"] for part in definition["parts"]} == {
        "Setting/Sparkcompute.yml",
        "Libraries/CustomLibraries/custom.whl",
        ".platform",
    }
    destination = tmp_path / "Restored.Environment"
    unpack_definition(definition, destination)
    assert (
        destination / "Libraries/CustomLibraries/custom.whl"
    ).read_bytes() == b"\x00\x01"


def test_diff_normalizes_text_sorts_json_and_marks_binary(tmp_path: Path) -> None:
    folder = _write_environment(tmp_path / "Dev.Environment")
    json_file = folder / "Libraries" / "PublicLibraries" / "config.json"
    json_file.parent.mkdir(parents=True)
    json_file.write_text('{"z":1,"a":2}', encoding="utf-8")
    text = folder_to_diff_text(folder)
    assert ".platform" not in text
    assert "<binary 2 bytes>" in text
    assert text.index('"a"') < text.index('"z"')
    assert "\r" not in text


def test_remote_diff_excludes_platform() -> None:
    parts = [
        {
            "path": ".platform",
            "payload": base64.b64encode(
                json.dumps({"logicalId": "x"}).encode()
            ).decode(),
            "payloadType": "InlineBase64",
        },
        {
            "path": "Setting/Sparkcompute.yml",
            "payload": base64.b64encode(b"a: 1\r\n").decode(),
            "payloadType": "InlineBase64",
        },
    ]
    text = definition_to_diff_text({"parts": parts})
    assert "logicalId" not in text
    assert text.endswith("a: 1\n")

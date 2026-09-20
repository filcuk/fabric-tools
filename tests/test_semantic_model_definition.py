"""Tests for semantic model definition pack/unpack."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from fabric_tools.definition_parts import PAYLOAD_TYPE
from fabric_tools.semantic_model.definition import (
    DefinitionError,
    SemanticModelFormat,
    definition_has_platform,
    definition_to_diff_text,
    detect_format,
    detect_semantic_model_path,
    display_name_from_path,
    folder_to_diff_text,
    pack_definition,
    unpack_definition,
    validate_local_semantic_model,
)


def _pbism() -> str:
    return json.dumps(
        {
            "$schema": (
                "https://developer.microsoft.com/json-schemas/fabric/item/"
                "semanticModel/definitionProperties/1.0.0/schema.json"
            ),
            "version": "5.0",
        }
    )


def _write_tmdl_folder(folder: Path, *, with_platform: bool = False) -> Path:
    (folder / "definition" / "tables").mkdir(parents=True)
    (folder / "definition.pbism").write_text(_pbism() + "\n", encoding="utf-8")
    (folder / "definition" / "model.tmdl").write_text("model Sales\n", encoding="utf-8")
    (folder / "definition" / "tables" / "product.tmdl").write_text(
        "table Product\n", encoding="utf-8"
    )
    if with_platform:
        (folder / ".platform").write_text(
            json.dumps({"metadata": {"type": "SemanticModel", "displayName": "Sales"}}),
            encoding="utf-8",
        )
    return folder


def test_detect_and_display_name(tmp_path: Path) -> None:
    folder = tmp_path / "Sales.SemanticModel"
    folder.mkdir()
    assert detect_semantic_model_path(folder) == folder
    assert display_name_from_path(folder) == "Sales"
    assert display_name_from_path(tmp_path / "other.semanticmodel") == "other"


def test_detect_folder_with_pbism_without_suffix(tmp_path: Path) -> None:
    folder = _write_tmdl_folder(tmp_path / "plain-folder")
    assert detect_semantic_model_path(folder) == folder
    assert validate_local_semantic_model(folder) == folder


def test_rejects_unsupported_path(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("nope", encoding="utf-8")
    with pytest.raises(DefinitionError, match="Unsupported semantic model path"):
        detect_semantic_model_path(path)


def test_pack_unpack_tmdl_round_trip(tmp_path: Path) -> None:
    src = _write_tmdl_folder(tmp_path / "Sales.SemanticModel", with_platform=True)
    definition = pack_definition(src)
    assert definition["format"] == SemanticModelFormat.TMDL.value
    paths = {p["path"] for p in definition["parts"]}
    assert "definition.pbism" in paths
    assert "definition/model.tmdl" in paths
    assert "definition/tables/product.tmdl" in paths
    assert ".platform" in paths
    assert definition_has_platform(definition)

    out = tmp_path / "Out.SemanticModel"
    unpack_definition(definition, out)
    assert detect_format(out) is SemanticModelFormat.TMDL
    assert (out / "definition" / "tables" / "product.tmdl").read_text(
        encoding="utf-8"
    ) == "table Product\n"


def test_tmsl_format(tmp_path: Path) -> None:
    folder = tmp_path / "Sales.SemanticModel"
    folder.mkdir()
    (folder / "definition.pbism").write_text(_pbism(), encoding="utf-8")
    (folder / "model.bim").write_text(
        json.dumps({"compatibilityLevel": 1702, "model": {}}),
        encoding="utf-8",
    )
    assert detect_format(folder) is SemanticModelFormat.TMSL
    definition = pack_definition(folder)
    assert definition["format"] == "TMSL"


def test_rejects_both_tmdl_and_tmsl(tmp_path: Path) -> None:
    folder = _write_tmdl_folder(tmp_path / "Sales.SemanticModel")
    (folder / "model.bim").write_text("{}", encoding="utf-8")
    with pytest.raises(DefinitionError, match="both"):
        validate_local_semantic_model(folder)


def test_diff_text_stable(tmp_path: Path) -> None:
    folder = _write_tmdl_folder(tmp_path / "Sales.SemanticModel")
    text = folder_to_diff_text(folder)
    assert "=== definition/model.tmdl ===" in text
    definition = pack_definition(folder)
    assert definition_to_diff_text(definition) == text


def test_unpack_from_api_shape(tmp_path: Path) -> None:
    definition = {
        "format": "TMDL",
        "parts": [
            {
                "path": "definition.pbism",
                "payload": base64.b64encode(_pbism().encode()).decode(),
                "payloadType": PAYLOAD_TYPE,
            },
            {
                "path": "definition/model.tmdl",
                "payload": base64.b64encode(b"model X\n").decode(),
                "payloadType": PAYLOAD_TYPE,
            },
        ],
    }
    dest = unpack_definition(definition, tmp_path / "X.SemanticModel")
    assert (dest / "definition" / "model.tmdl").read_text(encoding="utf-8") == (
        "model X\n"
    )

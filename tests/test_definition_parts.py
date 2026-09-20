"""Tests for Fabric definition folder pack/unpack helpers."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from fabric_tools.definition_parts import (
    PAYLOAD_TYPE,
    DefinitionPartsError,
    decode_part,
    encode_part,
    pack_definition,
    pack_folder,
    unpack_definition,
    unpack_parts,
)


def test_pack_unpack_round_trip_nested(tmp_path: Path) -> None:
    root = tmp_path / "Sales.SemanticModel"
    (root / "definition" / "tables").mkdir(parents=True)
    (root / "definition" / "model.tmdl").write_text("model Sales\n", encoding="utf-8")
    (root / "definition" / "tables" / "product.tmdl").write_text(
        "table Product\n", encoding="utf-8"
    )
    (root / "definition.pbism").write_text('{"version":"5.0"}\n', encoding="utf-8")
    (root / "diagramLayout.json").write_bytes(b'{"version":"1.1.0"}')

    parts = pack_folder(root)
    paths = {p["path"] for p in parts}
    assert paths == {
        "definition/model.tmdl",
        "definition/tables/product.tmdl",
        "definition.pbism",
        "diagramLayout.json",
    }
    assert all(p["payloadType"] == PAYLOAD_TYPE for p in parts)

    out = tmp_path / "out.SemanticModel"
    unpack_parts(parts, out)
    assert (out / "definition" / "model.tmdl").read_text(encoding="utf-8") == (
        "model Sales\n"
    )
    assert (out / "definition" / "tables" / "product.tmdl").read_text(
        encoding="utf-8"
    ) == "table Product\n"
    assert (out / "diagramLayout.json").read_bytes() == b'{"version":"1.1.0"}'


def test_pack_definition_includes_format(tmp_path: Path) -> None:
    root = tmp_path / "item"
    root.mkdir()
    (root / "definition.pbism").write_text("{}", encoding="utf-8")
    definition = pack_definition(root, format="TMDL")
    assert definition["format"] == "TMDL"
    assert len(definition["parts"]) == 1


def test_unpack_definition_object(tmp_path: Path) -> None:
    payload = base64.b64encode(b"hello").decode("ascii")
    definition = {
        "parts": [
            {
                "path": "a.txt",
                "payload": payload,
                "payloadType": PAYLOAD_TYPE,
            }
        ]
    }
    dest = unpack_definition(definition, tmp_path / "dest")
    assert (dest / "a.txt").read_bytes() == b"hello"


def test_empty_folder_rejected(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(DefinitionPartsError, match="no files"):
        pack_folder(empty)


def test_missing_folder_rejected(tmp_path: Path) -> None:
    with pytest.raises(DefinitionPartsError, match="not found"):
        pack_folder(tmp_path / "missing")


def test_path_traversal_rejected_on_decode() -> None:
    with pytest.raises(DefinitionPartsError, match="unsafe"):
        decode_part(
            {
                "path": "../escape.txt",
                "payload": base64.b64encode(b"x").decode("ascii"),
                "payloadType": PAYLOAD_TYPE,
            }
        )


def test_encode_part_rejects_absolute() -> None:
    with pytest.raises(DefinitionPartsError, match="unsafe|invalid"):
        encode_part("/etc/passwd", b"x")

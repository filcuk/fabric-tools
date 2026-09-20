"""Tests for Dataflow Gen2 definition pack/unpack."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from fabric_tools.dataflow.definition import (
    FORMAT_VERSION,
    DefinitionError,
    definition_has_platform,
    detect_dataflow_path,
    display_name_from_metadata,
    display_name_from_path,
    load_query_metadata,
    pack_definition,
    part_payloads,
    unpack_definition,
    validate_local_dataflow,
    validate_query_metadata_dict,
)


def _sample_metadata(**overrides: object) -> dict:
    metadata: dict = {
        "formatVersion": FORMAT_VERSION,
        "name": "Sales",
        "queryGroups": [],
        "queriesMetadata": {},
        "connections": [],
    }
    metadata.update(overrides)
    return metadata


def _write_dataflow_folder(
    folder: Path,
    *,
    mashup: str = "section Section1;\nshared Q1 = 1;\n",
    metadata: dict | None = None,
    platform: str | None = '{"metadata":{"type":"Dataflow","displayName":"Sales"}}',
    mdf_name: str | None = None,
    mdf_body: str = '{"name":"MDF"}',
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "queryMetadata.json").write_text(
        json.dumps(metadata or _sample_metadata(), indent=2) + "\n",
        encoding="utf-8",
    )
    (folder / "mashup.pq").write_text(mashup, encoding="utf-8")
    if platform is not None:
        (folder / ".platform").write_text(platform, encoding="utf-8")
    if mdf_name is not None:
        (folder / mdf_name).write_text(mdf_body, encoding="utf-8")
    return folder


def test_detect_and_display_name_from_dataflow_suffix(tmp_path: Path) -> None:
    folder = tmp_path / "MyFlow.Dataflow"
    folder.mkdir()
    assert detect_dataflow_path(folder) == folder
    assert display_name_from_path(folder) == "MyFlow"
    assert display_name_from_path(tmp_path / "other.dataflow") == "other"


def test_detect_folder_with_required_files_without_suffix(tmp_path: Path) -> None:
    folder = _write_dataflow_folder(tmp_path / "plain-folder", platform=None)
    assert detect_dataflow_path(folder) == folder
    assert validate_local_dataflow(folder) == folder


def test_detect_appends_stem_suffix(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("nope", encoding="utf-8")
    assert detect_dataflow_path(path) == tmp_path / "notes.txt.Dataflow"


def test_detect_appends_missing_stem(tmp_path: Path) -> None:
    assert detect_dataflow_path(tmp_path / "Ingest") == tmp_path / "Ingest.Dataflow"


def test_validate_requires_metadata_and_mashup(tmp_path: Path) -> None:
    folder = tmp_path / "Bad.Dataflow"
    folder.mkdir()
    with pytest.raises(DefinitionError, match="queryMetadata.json"):
        validate_local_dataflow(folder)

    (folder / "queryMetadata.json").write_text(
        json.dumps(_sample_metadata()), encoding="utf-8"
    )
    with pytest.raises(DefinitionError, match="mashup.pq"):
        validate_local_dataflow(folder)


def test_validate_rejects_bad_format_version(tmp_path: Path) -> None:
    folder = _write_dataflow_folder(
        tmp_path / "BadVersion.Dataflow",
        metadata=_sample_metadata(formatVersion="1"),
        platform=None,
    )
    with pytest.raises(DefinitionError, match="formatVersion"):
        validate_local_dataflow(folder)


def test_validate_rejects_empty_mashup(tmp_path: Path) -> None:
    folder = _write_dataflow_folder(
        tmp_path / "EmptyMashup.Dataflow", mashup="", platform=None
    )
    with pytest.raises(DefinitionError, match="mashup is empty"):
        validate_local_dataflow(folder)


def test_load_query_metadata_and_display_name(tmp_path: Path) -> None:
    folder = _write_dataflow_folder(tmp_path / "Sales.Dataflow", platform=None)
    loaded = load_query_metadata(folder / "queryMetadata.json")
    assert loaded["name"] == "Sales"
    assert display_name_from_metadata(loaded) == "Sales"
    assert validate_query_metadata_dict(loaded)["formatVersion"] == FORMAT_VERSION


def test_pack_unpack_round_trip(tmp_path: Path) -> None:
    folder = _write_dataflow_folder(
        tmp_path / "Sales.Dataflow",
        mdf_name="MDF transform.mdf",
    )
    definition = pack_definition(folder)
    assert definition_has_platform(definition)
    paths = {part["path"] for part in definition["parts"]}
    assert paths == {
        "queryMetadata.json",
        "mashup.pq",
        ".platform",
        "MDF transform.mdf",
    }

    out = tmp_path / "Restored.Dataflow"
    written = unpack_definition(definition, out)
    assert written == out
    assert (out / "mashup.pq").read_text(encoding="utf-8").startswith("section")
    assert (
        json.loads((out / "queryMetadata.json").read_text(encoding="utf-8"))["name"]
        == "Sales"
    )
    assert (out / "MDF transform.mdf").is_file()
    assert (out / ".platform").is_file()


def test_pack_without_optional_parts(tmp_path: Path) -> None:
    folder = _write_dataflow_folder(tmp_path / "Minimal.Dataflow", platform=None)
    definition = pack_definition(folder)
    assert not definition_has_platform(definition)
    assert {part["path"] for part in definition["parts"]} == {
        "queryMetadata.json",
        "mashup.pq",
    }


def test_unpack_rejects_missing_required_part() -> None:
    payload = base64.b64encode(b"section Section1;\n").decode("ascii")
    with pytest.raises(DefinitionError, match="queryMetadata.json"):
        unpack_definition(
            {
                "parts": [
                    {
                        "path": "mashup.pq",
                        "payload": payload,
                        "payloadType": "InlineBase64",
                    }
                ]
            },
            "unused.Dataflow",
        )


def test_part_payloads_decodes_by_filename() -> None:
    metadata = json.dumps(_sample_metadata()).encode("utf-8")
    mashup = b"section Section1;\n"
    definition = {
        "parts": [
            {
                "path": "queryMetadata.json",
                "payload": base64.b64encode(metadata).decode("ascii"),
                "payloadType": "InlineBase64",
            },
            {
                "path": "mashup.pq",
                "payload": base64.b64encode(mashup).decode("ascii"),
                "payloadType": "InlineBase64",
            },
        ]
    }
    payloads = part_payloads(definition)
    assert payloads["mashup.pq"] == mashup
    assert json.loads(payloads["queryMetadata.json"])["name"] == "Sales"

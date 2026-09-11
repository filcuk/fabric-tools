"""Tests for DataPipeline definition pack/unpack."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from fabric_tools.pipeline.definition import (
    DefinitionError,
    definition_has_platform,
    definition_to_diff_text,
    detect_pipeline_path,
    display_name_from_path,
    folder_to_diff_text,
    load_pipeline_content,
    pack_definition,
    part_payloads,
    unpack_definition,
    validate_local_pipeline,
    validate_pipeline_content_dict,
)


def _sample_content(**overrides: object) -> dict:
    content: dict = {
        "properties": {
            "description": "wait then stop",
            "activities": [
                {
                    "name": "Wait_1",
                    "type": "Wait",
                    "dependsOn": [],
                    "typeProperties": {"waitTimeInSeconds": 10},
                }
            ],
        }
    }
    content.update(overrides)
    return content


def _write_pipeline_folder(
    folder: Path,
    *,
    content: dict | None = None,
    platform: str | None = '{"metadata":{"type":"DataPipeline","displayName":"ETL"}}',
    schedules: str | None = None,
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pipeline-content.json").write_text(
        json.dumps(content or _sample_content(), indent=2) + "\n",
        encoding="utf-8",
    )
    if platform is not None:
        (folder / ".platform").write_text(platform, encoding="utf-8")
    if schedules is not None:
        (folder / ".schedules").write_text(schedules, encoding="utf-8")
    return folder


def test_detect_and_display_name_from_datapipeline_suffix(tmp_path: Path) -> None:
    folder = tmp_path / "MyPipe.DataPipeline"
    folder.mkdir()
    assert detect_pipeline_path(folder) == folder
    assert display_name_from_path(folder) == "MyPipe"
    assert display_name_from_path(tmp_path / "other.datapipeline") == "other"


def test_detect_folder_with_content_without_suffix(tmp_path: Path) -> None:
    folder = _write_pipeline_folder(tmp_path / "plain-folder", platform=None)
    assert detect_pipeline_path(folder) == folder
    assert validate_local_pipeline(folder) == folder


def test_rejects_unsupported_path(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("nope", encoding="utf-8")
    with pytest.raises(DefinitionError, match="Unsupported pipeline path"):
        detect_pipeline_path(path)


def test_validate_requires_pipeline_content(tmp_path: Path) -> None:
    folder = tmp_path / "Bad.DataPipeline"
    folder.mkdir()
    with pytest.raises(DefinitionError, match="pipeline-content.json"):
        validate_local_pipeline(folder)


def test_validate_rejects_missing_properties(tmp_path: Path) -> None:
    folder = _write_pipeline_folder(
        tmp_path / "BadContent.DataPipeline",
        content={"notProperties": {}},
        platform=None,
    )
    with pytest.raises(DefinitionError, match="properties"):
        validate_local_pipeline(folder)


def test_load_pipeline_content(tmp_path: Path) -> None:
    folder = _write_pipeline_folder(tmp_path / "ETL.DataPipeline", platform=None)
    loaded = load_pipeline_content(folder / "pipeline-content.json")
    assert loaded["properties"]["activities"][0]["name"] == "Wait_1"
    assert validate_pipeline_content_dict(loaded)["properties"]["description"] == (
        "wait then stop"
    )


def test_pack_unpack_round_trip(tmp_path: Path) -> None:
    folder = _write_pipeline_folder(
        tmp_path / "ETL.DataPipeline",
        schedules='{"schedules":[]}\n',
    )
    definition = pack_definition(folder)
    assert definition_has_platform(definition)
    paths = {part["path"] for part in definition["parts"]}
    assert paths == {
        "pipeline-content.json",
        ".platform",
        ".schedules",
    }

    out = tmp_path / "Restored.DataPipeline"
    written = unpack_definition(definition, out)
    assert written == out
    restored = json.loads((out / "pipeline-content.json").read_text(encoding="utf-8"))
    assert restored["properties"]["activities"][0]["type"] == "Wait"
    assert (out / ".platform").is_file()
    assert (out / ".schedules").is_file()


def test_pack_without_optional_parts(tmp_path: Path) -> None:
    folder = _write_pipeline_folder(tmp_path / "Minimal.DataPipeline", platform=None)
    definition = pack_definition(folder)
    assert not definition_has_platform(definition)
    assert {part["path"] for part in definition["parts"]} == {"pipeline-content.json"}


def test_unpack_rejects_missing_required_part() -> None:
    payload = base64.b64encode(b'{"schedules":[]}').decode("ascii")
    with pytest.raises(DefinitionError, match="pipeline-content.json"):
        unpack_definition(
            {
                "parts": [
                    {
                        "path": ".schedules",
                        "payload": payload,
                        "payloadType": "InlineBase64",
                    }
                ]
            },
            "unused.DataPipeline",
        )


def test_part_payloads_decodes_by_filename() -> None:
    content = json.dumps(_sample_content()).encode("utf-8")
    definition = {
        "parts": [
            {
                "path": "pipeline-content.json",
                "payload": base64.b64encode(content).decode("ascii"),
                "payloadType": "InlineBase64",
            }
        ]
    }
    payloads = part_payloads(definition)
    assert (
        json.loads(payloads["pipeline-content.json"])["properties"]["activities"][0][
            "name"
        ]
        == "Wait_1"
    )


def test_diff_text_excludes_platform(tmp_path: Path) -> None:
    folder = _write_pipeline_folder(
        tmp_path / "Diff.DataPipeline",
        schedules='{"schedules":[{"name":"daily"}]}\n',
    )
    text = folder_to_diff_text(folder)
    assert "=== pipeline-content.json ===" in text
    assert "=== .schedules ===" in text
    assert ".platform" not in text
    assert "Wait_1" in text

    definition = pack_definition(folder)
    assert ".platform" not in definition_to_diff_text(definition)


def test_pack_ignore_schedules(tmp_path: Path) -> None:
    folder = _write_pipeline_folder(
        tmp_path / "ETL.DataPipeline",
        schedules='{"schedules":[{"name":"daily"}]}\n',
    )
    definition = pack_definition(folder, ignore_schedules=True)
    assert {part["path"] for part in definition["parts"]} == {
        "pipeline-content.json",
        ".platform",
    }


def test_unpack_ignore_schedules_skips_and_removes_leftover(tmp_path: Path) -> None:
    folder = _write_pipeline_folder(
        tmp_path / "ETL.DataPipeline",
        schedules='{"schedules":[]}\n',
    )
    definition = pack_definition(folder)
    out = tmp_path / "Restored.DataPipeline"
    out.mkdir()
    (out / ".schedules").write_text(
        '{"schedules":[{"name":"stale"}]}\n', encoding="utf-8"
    )
    unpack_definition(definition, out, ignore_schedules=True)
    assert (out / "pipeline-content.json").is_file()
    assert (out / ".platform").is_file()
    assert not (out / ".schedules").exists()


def test_definition_without_schedules() -> None:
    from fabric_tools.pipeline.definition import definition_without_schedules

    content = json.dumps(_sample_content()).encode("utf-8")
    definition = {
        "parts": [
            {
                "path": "pipeline-content.json",
                "payload": base64.b64encode(content).decode("ascii"),
                "payloadType": "InlineBase64",
            },
            {
                "path": ".schedules",
                "payload": base64.b64encode(b'{"schedules":[]}').decode("ascii"),
                "payloadType": "InlineBase64",
            },
        ]
    }
    stripped = definition_without_schedules(definition)
    assert {part["path"] for part in stripped["parts"]} == {"pipeline-content.json"}
    assert definition_without_schedules(stripped) is stripped


def test_diff_text_ignore_schedules(tmp_path: Path) -> None:
    folder = _write_pipeline_folder(
        tmp_path / "Diff.DataPipeline",
        schedules='{"schedules":[{"name":"daily"}]}\n',
    )
    text = folder_to_diff_text(folder, ignore_schedules=True)
    assert "=== pipeline-content.json ===" in text
    assert ".schedules" not in text
    definition = pack_definition(folder)
    assert ".schedules" not in definition_to_diff_text(
        definition, ignore_schedules=True
    )

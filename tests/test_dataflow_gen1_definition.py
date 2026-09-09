"""Tests for Dataflow Gen1 model.json helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fabric_tools.dataflow_gen1.definition import (
    DefinitionError,
    display_name_from_model,
    load_model,
    model_to_bytes,
    model_to_diff_text,
    normalize_model_for_compare,
    prepare_model_for_import,
    strip_partitions,
    validate_local_model,
    write_model,
)


def _sample_model(**overrides: object) -> dict:
    model: dict = {
        "name": "Sales",
        "description": "demo",
        "entities": [
            {
                "name": "Query1",
                "partitions": [{"name": "part1", "location": "https://example"}],
            }
        ],
    }
    model.update(overrides)
    return model


def test_load_and_validate_model(tmp_path: Path) -> None:
    path = tmp_path / "model.json"
    write_model(_sample_model(), path)
    loaded = load_model(path)
    assert loaded["name"] == "Sales"
    assert validate_local_model(path) == path


def test_load_model_rejects_missing_name(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"entities": []}), encoding="utf-8")
    with pytest.raises(DefinitionError, match="name"):
        load_model(path)


def test_strip_partitions_and_prepare() -> None:
    cleaned = strip_partitions(_sample_model())
    assert "partitions" not in cleaned["entities"][0]
    prepared = prepare_model_for_import(_sample_model(), display_name="Renamed")
    assert prepared["name"] == "Renamed"
    assert "partitions" not in prepared["entities"][0]


def test_prepare_rejects_empty_display_name() -> None:
    with pytest.raises(DefinitionError, match="display name"):
        prepare_model_for_import(_sample_model(), display_name="  ")


def test_model_to_bytes_and_diff_text_ignore_partitions() -> None:
    left = _sample_model()
    right = _sample_model()
    right["entities"][0].pop("partitions")
    assert model_to_diff_text(left) == model_to_diff_text(right)
    assert normalize_model_for_compare(left)["entities"][0].get("partitions") is None
    raw = model_to_bytes(prepare_model_for_import(left))
    assert b"partitions" not in raw
    assert display_name_from_model(left) == "Sales"

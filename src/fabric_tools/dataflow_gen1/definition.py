"""Local Dataflow Gen1 model.json load / validate / prepare helpers."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from fabric_tools.parsing import ensure_kind_path_suffix


class DefinitionError(ValueError):
    """Invalid local or remote Dataflow Gen1 model.json."""


def ensure_model_path(path: Path | str) -> Path:
    """Append ``.json`` when *path* is not already a ``.json`` file path."""
    p = Path(path)
    if p.suffix.lower() == ".json":
        return p
    return ensure_kind_path_suffix(p, canonical_suffix=".json")


def load_model(path: Path) -> dict[str, Any]:
    """Read and validate a local model.json file."""
    path = ensure_model_path(path)
    if not path.is_file():
        raise DefinitionError(f"model file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise DefinitionError(f"cannot read model file {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DefinitionError(f"invalid JSON in {path}: {exc}") from exc
    return validate_model_dict(data, label=str(path))


def validate_local_model(path: Path) -> Path:
    """Ensure ``path`` is a readable Gen1 model.json; return the path."""
    path = ensure_model_path(path)
    load_model(path)
    return path


def validate_model_dict(data: Any, *, label: str = "model") -> dict[str, Any]:
    """Validate a parsed Gen1 dataflow model object."""
    if not isinstance(data, dict):
        raise DefinitionError(f"{label}: expected a JSON object")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise DefinitionError(f"{label}: missing non-empty string 'name'")
    entities = data.get("entities")
    if entities is not None and not isinstance(entities, list):
        raise DefinitionError(f"{label}: 'entities' must be a list when present")
    return data


def display_name_from_model(model: dict[str, Any]) -> str:
    """Return the dataflow display name from model.json."""
    name = model.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return "Dataflow"


def write_model(model: dict[str, Any], path: Path) -> Path:
    """Write model.json with stable UTF-8 formatting."""
    path = ensure_model_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(model, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def strip_partitions(model: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy with entity ``partitions`` removed (required for import)."""
    cleaned = copy.deepcopy(model)
    entities = cleaned.get("entities")
    if isinstance(entities, list):
        for entity in entities:
            if isinstance(entity, dict):
                entity.pop("partitions", None)
    cleaned.pop("partitions", None)
    return cleaned


def prepare_model_for_import(
    model: dict[str, Any],
    *,
    display_name: str | None = None,
) -> dict[str, Any]:
    """Prepare a model for Power BI import (strip partitions; optional rename)."""
    prepared = strip_partitions(model)
    if display_name is not None:
        name = display_name.strip()
        if not name:
            raise DefinitionError("display name must be non-empty")
        prepared["name"] = name
    return validate_model_dict(prepared, label="import model")


def model_to_bytes(model: dict[str, Any]) -> bytes:
    """Serialize a model to UTF-8 JSON bytes for multipart import."""
    return json.dumps(model, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def normalize_model_for_compare(model: dict[str, Any]) -> dict[str, Any]:
    """Normalize a model for equality / text diff (strip partitions, stable shape)."""
    return strip_partitions(model)


def model_to_diff_text(model: dict[str, Any]) -> str:
    """Pretty JSON text used for unified diffs."""
    return (
        json.dumps(
            normalize_model_for_compare(model),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
    )

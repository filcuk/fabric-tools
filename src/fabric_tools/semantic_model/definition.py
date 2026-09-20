"""Pack and unpack Fabric semantic model public definitions."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any

from fabric_tools.definition_parts import (
    DefinitionPartsError,
    decode_part,
)
from fabric_tools.definition_parts import (
    pack_definition as pack_folder_definition,
)
from fabric_tools.definition_parts import (
    unpack_definition as unpack_folder_definition,
)
from fabric_tools.parsing import ensure_kind_path_suffix

PBISM_PART = "definition.pbism"
BIM_PART = "model.bim"
DEFINITION_DIR = "definition"
PLATFORM_PART = ".platform"


class SemanticModelFormat(str, Enum):
    TMDL = "TMDL"
    TMSL = "TMSL"


class DefinitionError(ValueError):
    """Invalid local semantic model path or definition payload."""


def is_semantic_model_folder_name(name: str) -> bool:
    """True when *name* looks like a Fabric Git ``*.SemanticModel`` folder."""
    return name.endswith(".SemanticModel") or name.endswith(".semanticmodel")


def detect_semantic_model_path(path: Path | str) -> Path:
    """Resolve *path* as a semantic model folder path (does not fully validate).

    Bare stems (e.g. ``SalesModel``) become ``SalesModel.SemanticModel``.
    Existing folders that already contain ``definition.pbism`` are left unchanged.
    """
    return ensure_kind_path_suffix(
        path,
        canonical_suffix=".SemanticModel",
        accepted_suffixes=(".SemanticModel", ".semanticmodel"),
        bare_content_ok=lambda p: p.is_dir() and (p / PBISM_PART).is_file(),
    )


def display_name_from_path(path: Path | str) -> str:
    """Default Fabric display name from a local ``*.SemanticModel`` folder stem."""
    p = Path(path)
    name = p.name
    if name.endswith(".SemanticModel"):
        return name[: -len(".SemanticModel")]
    if name.endswith(".semanticmodel"):
        return name[: -len(".semanticmodel")]
    return p.name


def _has_tmdl_files(folder: Path) -> bool:
    definition = folder / DEFINITION_DIR
    return definition.is_dir() and any(p.is_file() for p in definition.rglob("*"))


def detect_format(path: Path | str) -> SemanticModelFormat:
    """Infer TMDL vs TMSL from a validated semantic model folder."""
    folder = validate_local_semantic_model(path)
    if _has_tmdl_files(folder):
        return SemanticModelFormat.TMDL
    return SemanticModelFormat.TMSL


def validate_local_semantic_model(path: Path | str) -> Path:
    """Ensure *path* is a packable semantic model folder; return the folder path."""
    folder = detect_semantic_model_path(path)
    if not folder.is_dir():
        raise DefinitionError(f"Semantic model folder not found: {folder}")
    pbism = folder / PBISM_PART
    if not pbism.is_file():
        raise DefinitionError(
            f"Semantic model folder is missing '{PBISM_PART}': {folder}"
        )
    try:
        text = pbism.read_text(encoding="utf-8-sig")
        data = json.loads(text)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DefinitionError(f"invalid {PBISM_PART} in {folder}: {exc}") from exc
    if not isinstance(data, dict):
        raise DefinitionError(f"{PBISM_PART} must be a JSON object: {folder}")

    has_tmdl = _has_tmdl_files(folder)
    has_tmsl = (folder / BIM_PART).is_file()
    if has_tmdl and has_tmsl:
        raise DefinitionError(
            f"semantic model folder has both '{DEFINITION_DIR}/' and '{BIM_PART}' "
            f"(use one format): {folder}"
        )
    if not has_tmdl and not has_tmsl:
        raise DefinitionError(
            f"semantic model folder needs '{DEFINITION_DIR}/' (TMDL) or '{BIM_PART}' "
            f"(TMSL): {folder}"
        )
    return folder


def pack_definition(path: Path | str) -> dict[str, Any]:
    """Build a Fabric semantic model definition from a local folder."""
    folder = validate_local_semantic_model(path)
    fmt = detect_format(folder)
    try:
        return pack_folder_definition(folder, format=fmt.value)
    except DefinitionPartsError as exc:
        raise DefinitionError(str(exc)) from exc


def unpack_definition(definition: dict[str, Any], destination: Path | str) -> Path:
    """Write a Fabric definition response to a local semantic model folder."""
    try:
        return unpack_folder_definition(definition, destination)
    except DefinitionPartsError as exc:
        raise DefinitionError(str(exc)) from exc


def definition_has_platform(definition: dict[str, Any]) -> bool:
    """True when the definition includes a ``.platform`` part."""
    parts = definition.get("parts") or []
    for part in parts:
        if (
            isinstance(part, dict)
            and Path(str(part.get("path", ""))).name == PLATFORM_PART
        ):
            return True
    return False


def part_payloads(definition: dict[str, Any]) -> dict[str, bytes]:
    """Decode definition parts to a ``{relative_path: bytes}`` map."""
    parts = definition.get("parts")
    if not isinstance(parts, list) or not parts:
        raise DefinitionError("Definition response has no parts")
    out: dict[str, bytes] = {}
    for part in parts:
        try:
            path, payload = decode_part(part)
        except DefinitionPartsError as exc:
            raise DefinitionError(str(exc)) from exc
        out[path.replace("\\", "/")] = payload
    return out


def folder_payloads(path: Path | str) -> dict[str, bytes]:
    """Read all files under a local semantic model folder as relative-path payloads."""
    folder = validate_local_semantic_model(path)
    payloads: dict[str, bytes] = {}
    for file_path in sorted(folder.rglob("*"), key=lambda p: p.as_posix().lower()):
        if file_path.is_file():
            payloads[file_path.relative_to(folder).as_posix()] = file_path.read_bytes()
    return payloads


def definition_to_diff_text(definition: dict[str, Any]) -> str:
    """Stable multi-file text used for unified diffs of a Fabric definition."""
    return payloads_to_diff_text(part_payloads(definition))


def folder_to_diff_text(path: Path | str) -> str:
    """Stable multi-file text for unified diffs of a local semantic model folder."""
    return payloads_to_diff_text(folder_payloads(path))


def payloads_to_diff_text(payloads: dict[str, bytes]) -> str:
    """Render part payloads as a deterministic multi-section text blob."""
    chunks: list[str] = []
    for name in sorted(payloads):
        chunks.append(f"=== {name} ===\n")
        chunks.append(_normalize_part_text(name, payloads[name]))
    return "".join(chunks)


def _normalize_part_text(name: str, payload: bytes) -> str:
    text = payload.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    lower = name.lower()
    if lower.endswith(".json") or lower.endswith(".pbism") or lower.endswith(".bim"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return text if text.endswith("\n") else text + "\n"
        return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    return text if text.endswith("\n") else text + "\n"

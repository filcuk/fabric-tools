"""Pack and unpack Microsoft Fabric Environment definitions."""

from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path
from typing import Any

from fabric_tools.definition_parts import (
    DefinitionPartsError,
    decode_part,
    pack_folder,
    unpack_parts,
)
from fabric_tools.parsing import ensure_kind_path_suffix

PLATFORM_PART = ".platform"
SPARK_COMPUTE_PART = "Setting/Sparkcompute.yml"
PUBLIC_LIBRARIES_PART = "Libraries/PublicLibraries/environment.yml"
TEXT_SUFFIXES = {".yml", ".yaml", ".py", ".json"}


class DefinitionError(ValueError):
    """Invalid local Environment path or definition payload."""


def _is_environment_folder_name(name: str) -> bool:
    return name.lower().endswith(".environment")


def _environment_bare_content_ok(folder: Path) -> bool:
    return folder.is_dir() and (
        (folder / SPARK_COMPUTE_PART).is_file()
        or (folder / "Libraries").is_dir()
        or (folder / PLATFORM_PART).is_file()
    )


def detect_environment_path(path: Path | str) -> Path:
    """Resolve *path* as an Environment folder path.

    Bare stems (e.g. ``SparkDev``) become ``SparkDev.Environment``. Existing
    folders that already look like an Environment unpack are left unchanged.
    """
    folder = Path(path)
    if _is_environment_folder_name(folder.name):
        return folder
    return ensure_kind_path_suffix(
        folder,
        canonical_suffix=".Environment",
        accepted_suffixes=(".Environment", ".environment"),
        bare_content_ok=_environment_bare_content_ok,
    )


def display_name_from_path(path: Path | str) -> str:
    """Return the default Fabric display name for a local Environment folder."""
    name = Path(path).name
    if name.lower().endswith(".environment"):
        return name[: -len(".Environment")]
    return name


def validate_local_environment(path: Path | str) -> Path:
    """Ensure *path* is a non-empty, packable Environment folder."""
    folder = detect_environment_path(path)
    if not folder.is_dir():
        raise DefinitionError(f"Environment folder not found: {folder}")
    known_files = [
        file
        for file in folder.rglob("*")
        if file.is_file() and _is_known_content(file.relative_to(folder).as_posix())
    ]
    if not known_files:
        raise DefinitionError(
            "Environment folder has no definition content; expected at least one file "
            f"under Libraries/, {SPARK_COMPUTE_PART}, or {PLATFORM_PART}: {folder}"
        )
    return folder


def pack_definition(path: Path | str) -> dict[str, Any]:
    """Build a Fabric Environment definition from a local folder."""
    folder = validate_local_environment(path)
    try:
        parts = pack_folder(folder)
    except DefinitionPartsError as exc:
        raise DefinitionError(str(exc)) from exc
    return {"parts": parts}


def unpack_definition(definition: dict[str, Any], destination: Path | str) -> Path:
    """Write a Fabric Environment definition to a local folder."""
    parts = definition.get("parts")
    if not isinstance(parts, list) or not parts:
        raise DefinitionError("Definition response has no parts")
    try:
        decoded = [decode_part(part) for part in parts]
        if not any(_is_known_content(path) for path, _payload in decoded):
            raise DefinitionError("Definition has no recognized Environment parts")
        return unpack_parts(parts, destination)
    except DefinitionPartsError as exc:
        raise DefinitionError(str(exc)) from exc


def definition_has_platform(definition: dict[str, Any]) -> bool:
    """True when the definition includes a ``.platform`` part."""
    return any(
        isinstance(part, dict)
        and str(part.get("path", "")).replace("\\", "/") == PLATFORM_PART
        for part in definition.get("parts") or []
    )


def folder_to_diff_text(path: Path | str) -> str:
    """Return stable multipart comparison text for a local Environment."""
    return _parts_to_diff_text(pack_definition(path).get("parts", []))


def definition_to_diff_text(definition: dict[str, Any]) -> str:
    """Return stable multipart comparison text for a remote Environment."""
    parts = definition.get("parts")
    if not isinstance(parts, list) or not parts:
        raise DefinitionError("Definition response has no parts")
    return _parts_to_diff_text(parts)


def _parts_to_diff_text(parts: list[Any]) -> str:
    rendered: list[tuple[str, str]] = []
    try:
        decoded = [decode_part(part) for part in parts]
    except DefinitionPartsError as exc:
        raise DefinitionError(str(exc)) from exc
    for path, payload in decoded:
        normalized_path = path.replace("\\", "/")
        if normalized_path == PLATFORM_PART:
            continue
        rendered.append((normalized_path, _render_payload(normalized_path, payload)))
    rendered.sort(key=lambda item: item[0].lower())
    return "".join(f"--- {path}\n{body}" for path, body in rendered)


def _render_payload(path: str, payload: bytes) -> str:
    suffix = Path(path).suffix.lower()
    if suffix not in TEXT_SUFFIXES:
        return f"<binary {len(payload)} bytes>\n"
    try:
        text = payload.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError:
        return f"<binary {len(payload)} bytes>\n"
    if suffix == ".json":
        with suppress(json.JSONDecodeError):
            text = json.dumps(
                json.loads(text), indent=2, ensure_ascii=False, sort_keys=True
            )
    return text.rstrip("\n") + "\n"


def _is_known_content(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized in (
        PLATFORM_PART,
        SPARK_COMPUTE_PART,
    ) or normalized.startswith("Libraries/")

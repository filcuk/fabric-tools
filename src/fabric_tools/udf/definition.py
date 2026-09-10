"""Pack and unpack Fabric User Data Function public definitions."""

from __future__ import annotations

import base64
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

PLATFORM_PART_PATH = ".platform"
DEFINITION_JSON_PATH = "definition.json"
FUNCTION_APP_PATH = "function_app.py"
FUNCTIONS_JSON_PATH = "resources/functions.json"
PAYLOAD_TYPE = "InlineBase64"

# Git integration docs sometimes use alternate filenames; normalize to REST paths.
_DEFINITION_JSON_ALIASES = (DEFINITION_JSON_PATH, "definitions.json")
_FUNCTION_APP_ALIASES = (FUNCTION_APP_PATH, "function-app.py")
_FUNCTIONS_JSON_ALIASES = (
    FUNCTIONS_JSON_PATH,
    "resources\\functions.json",
)

FOLDER_SUFFIXES = (".UserDataFunction", ".userdatafunction")


class DefinitionError(ValueError):
    """Invalid local UDF path or definition payload."""


def detect_udf_folder(path: Path | str) -> Path:
    """Ensure *path* looks like a ``*.UserDataFunction`` folder; return it."""
    p = Path(path)
    name = p.name
    if not any(name.endswith(suffix) for suffix in FOLDER_SUFFIXES):
        raise DefinitionError(
            f"Unsupported UDF path '{p}'. Expected a *.UserDataFunction folder."
        )
    return p


def display_name_from_path(path: Path | str) -> str:
    """Default Fabric display name from a local ``*.UserDataFunction`` folder."""
    p = Path(path)
    name = p.name
    for suffix in (".UserDataFunction", ".userdatafunction"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return p.stem


def validate_local_udf(path: Path | str) -> Path:
    """Ensure the path exists and has required UDF definition parts. Returns path."""
    p = detect_udf_folder(path)
    if not p.is_dir():
        raise DefinitionError(f"UDF folder not found: {p}")
    if _resolve_local_file(p, _DEFINITION_JSON_ALIASES) is None:
        raise DefinitionError(f"UDF folder is missing '{DEFINITION_JSON_PATH}': {p}")
    if _resolve_local_file(p, _FUNCTION_APP_ALIASES) is None:
        raise DefinitionError(f"UDF folder is missing '{FUNCTION_APP_PATH}': {p}")
    if _resolve_local_file(p, _FUNCTIONS_JSON_ALIASES) is None:
        raise DefinitionError(f"UDF folder is missing '{FUNCTIONS_JSON_PATH}': {p}")
    return p


def pack_definition(path: Path | str) -> dict[str, Any]:
    """Build a Fabric User Data Function definition object from a local folder."""
    p = validate_local_udf(path)
    parts: list[dict[str, str]] = []

    definition_file = _resolve_local_file(p, _DEFINITION_JSON_ALIASES)
    assert definition_file is not None
    parts.append(_part(DEFINITION_JSON_PATH, definition_file.read_bytes()))

    function_app = _resolve_local_file(p, _FUNCTION_APP_ALIASES)
    assert function_app is not None
    parts.append(_part(FUNCTION_APP_PATH, function_app.read_bytes()))

    functions_json = _resolve_local_file(p, _FUNCTIONS_JSON_ALIASES)
    assert functions_json is not None
    parts.append(_part(FUNCTIONS_JSON_PATH, functions_json.read_bytes()))

    platform = p / PLATFORM_PART_PATH
    if platform.is_file():
        parts.append(_part(PLATFORM_PART_PATH, platform.read_bytes()))

    private_dir = p / "privateLibraries"
    if private_dir.is_dir():
        for wheel in sorted(private_dir.glob("*.whl")):
            if wheel.is_file():
                parts.append(
                    _part(f"privateLibraries/{wheel.name}", wheel.read_bytes())
                )

    return {"parts": parts}


def unpack_definition(
    definition: dict[str, Any],
    destination: Path | str,
) -> Path:
    """Write a Fabric UDF definition response to a local ``*.UserDataFunction`` folder.

    Returns the destination path written.
    """
    dest = detect_udf_folder(destination)
    parts = definition.get("parts")
    if not isinstance(parts, list) or not parts:
        raise DefinitionError("Definition response has no parts")

    decoded_parts = [_decode_part(part) for part in parts]
    dest.mkdir(parents=True, exist_ok=True)
    for relative_path, payload in decoded_parts:
        # Preserve nested paths (resources/, privateLibraries/).
        rel = Path(_normalize_part_path(relative_path))
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    return dest


def definition_has_platform(definition: dict[str, Any]) -> bool:
    """True when the definition includes a ``.platform`` part."""
    parts = definition.get("parts") or []
    for part in parts:
        if (
            isinstance(part, dict)
            and Path(str(part.get("path", ""))).name == PLATFORM_PART_PATH
        ):
            return True
    return False


def definition_json_from_definition(definition: dict[str, Any]) -> dict[str, Any]:
    """Decode and parse the ``definition.json`` part from a definition object."""
    raw = _part_bytes(definition, _DEFINITION_JSON_ALIASES)
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DefinitionError(f"Invalid definition.json content: {exc}") from exc
    if not isinstance(data, dict):
        raise DefinitionError("definition.json must be a JSON object")
    return data


def replace_definition_json_part(
    definition: dict[str, Any],
    definition_json: dict[str, Any],
) -> dict[str, Any]:
    """Return a copy of *definition* with ``definition.json`` replaced."""
    parts = definition.get("parts")
    if not isinstance(parts, list) or not parts:
        raise DefinitionError("Definition has no parts")

    raw = json.dumps(definition_json, ensure_ascii=False, indent=2).encode("utf-8")
    new_part = _part(DEFINITION_JSON_PATH, raw)
    new_parts: list[Any] = []
    replaced = False
    for part in parts:
        if not isinstance(part, dict):
            new_parts.append(part)
            continue
        path = _normalize_part_path(str(part.get("path", "")))
        if path in _DEFINITION_JSON_ALIASES or Path(path).name in {
            "definition.json",
            "definitions.json",
        }:
            new_parts.append(new_part)
            replaced = True
        else:
            new_parts.append(part)
    if not replaced:
        new_parts.insert(0, new_part)
    return {**definition, "parts": new_parts}


def strip_connected_data_sources(definition_json: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *definition_json* with ``connectedDataSources`` cleared."""
    stripped = deepcopy(definition_json)
    stripped["connectedDataSources"] = []
    return stripped


def merge_remote_connections(
    source: dict[str, Any],
    remote: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Copy remote ``connectedDataSources`` into *source*.

    Always replaces the source list with the remote list (including empty) so
    overwrite deploys keep the target item's workspace connections.

    Returns ``(merged_definition_json, preserved)`` where *preserved* is True
    when remote had a ``connectedDataSources`` key (list or otherwise normalized).
    """
    merged = deepcopy(source)
    if "connectedDataSources" not in remote:
        return merged, False
    remote_sources = remote.get("connectedDataSources")
    if not isinstance(remote_sources, list):
        remote_sources = []
    merged["connectedDataSources"] = deepcopy(remote_sources)
    return merged, True


def _resolve_local_file(folder: Path, candidates: tuple[str, ...]) -> Path | None:
    for relative in candidates:
        # Try both forward-slash and native separators.
        candidate = folder / Path(_normalize_part_path(relative))
        if candidate.is_file():
            return candidate
    return None


def _part_bytes(definition: dict[str, Any], aliases: tuple[str, ...]) -> bytes:
    parts = definition.get("parts")
    if not isinstance(parts, list) or not parts:
        raise DefinitionError("Definition has no parts")
    alias_names = {Path(_normalize_part_path(a)).name for a in aliases}
    alias_paths = {_normalize_part_path(a) for a in aliases}
    for part in parts:
        path, payload = _decode_part(part)
        normalized = _normalize_part_path(path)
        if normalized in alias_paths or Path(normalized).name in alias_names:
            return payload
    expected = aliases[0]
    raise DefinitionError(f"Definition is missing part '{expected}'")


def _normalize_part_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _part(path: str, payload: bytes) -> dict[str, str]:
    return {
        "path": path,
        "payload": base64.b64encode(payload).decode("ascii"),
        "payloadType": PAYLOAD_TYPE,
    }


def _decode_part(part: Any) -> tuple[str, bytes]:
    if not isinstance(part, dict):
        raise DefinitionError("Definition part must be an object")
    path = part.get("path")
    payload = part.get("payload")
    payload_type = part.get("payloadType", PAYLOAD_TYPE)
    if not isinstance(path, str) or not path:
        raise DefinitionError("Definition part is missing path")
    if not isinstance(payload, str):
        raise DefinitionError(f"Definition part '{path}' is missing payload")
    if payload_type != PAYLOAD_TYPE:
        raise DefinitionError(
            f"Unsupported payloadType '{payload_type}' for part '{path}' "
            f"(expected {PAYLOAD_TYPE})"
        )
    try:
        return path, base64.b64decode(payload, validate=False)
    except Exception as exc:  # noqa: BLE001 - surface as DefinitionError
        raise DefinitionError(f"Invalid base64 payload for part '{path}'") from exc

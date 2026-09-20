"""Pack and unpack Microsoft Fabric Variable Library definitions."""

from __future__ import annotations

import base64
import json
from contextlib import suppress
from pathlib import Path
from typing import Any

VARIABLES_PART = "variables.json"
SETTINGS_PART = "settings.json"
PLATFORM_PART = ".platform"
VALUE_SETS_DIR = "valueSets"
LEGACY_VALUE_SET_DIR = "valueSet"
REQUIRED_PARTS = (VARIABLES_PART, SETTINGS_PART)
PAYLOAD_TYPE = "InlineBase64"


class DefinitionError(ValueError):
    """Invalid local Variable Library path or definition payload."""


def detect_variable_library_path(path: Path | str) -> Path:
    """Resolve *path* as a Variable Library folder path."""
    folder = Path(path)
    if folder.name.lower().endswith(".variablelibrary"):
        return folder
    if folder.is_dir() and all((folder / name).is_file() for name in REQUIRED_PARTS):
        return folder
    raise DefinitionError(
        f"Unsupported Variable Library path '{folder}'. Expected a "
        f"*.VariableLibrary folder containing {VARIABLES_PART} and {SETTINGS_PART}."
    )


def display_name_from_path(path: Path | str) -> str:
    """Return the default Fabric display name for a local Variable Library."""
    name = Path(path).name
    if name.lower().endswith(".variablelibrary"):
        return name[: -len(".VariableLibrary")]
    return name


def validate_json_dict(payload: bytes, *, label: str) -> dict[str, Any]:
    """Decode JSON and require an object at its root."""
    try:
        data = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DefinitionError(f"invalid JSON in {label}: {exc}") from exc
    if not isinstance(data, dict):
        raise DefinitionError(f"{label}: expected a JSON object")
    return data


def validate_local_variable_library(path: Path | str) -> Path:
    """Ensure *path* is a packable Variable Library folder."""
    folder = detect_variable_library_path(path)
    if not folder.is_dir():
        raise DefinitionError(f"Variable Library folder not found: {folder}")
    for required in REQUIRED_PARTS:
        file_path = folder / required
        if not file_path.is_file():
            raise DefinitionError(
                f"Variable Library folder is missing '{required}': {folder}"
            )
    for required in REQUIRED_PARTS:
        file_path = folder / required
        validate_json_dict(file_path.read_bytes(), label=str(file_path))
    for file_path in _value_set_files(folder):
        validate_json_dict(file_path.read_bytes(), label=str(file_path))
    return folder


def pack_definition(path: Path | str) -> dict[str, Any]:
    """Build a Fabric Variable Library definition from a local folder."""
    folder = validate_local_variable_library(path)
    parts = [_part(name, (folder / name).read_bytes()) for name in REQUIRED_PARTS]
    seen: set[str] = set()
    for file_path in _value_set_files(folder):
        normalized = f"{VALUE_SETS_DIR}/{file_path.name}"
        key = normalized.lower()
        if key in seen:
            raise DefinitionError(
                f"duplicate Variable Library value set after normalization: {normalized}"
            )
        seen.add(key)
        parts.append(_part(normalized, file_path.read_bytes()))
    platform = folder / PLATFORM_PART
    if platform.is_file():
        parts.append(_part(PLATFORM_PART, platform.read_bytes()))
    return {"parts": parts}


def unpack_definition(definition: dict[str, Any], destination: Path | str) -> Path:
    """Write a Fabric definition to a normalized Variable Library folder."""
    payloads = part_payloads(definition)
    for required in REQUIRED_PARTS:
        if required not in payloads:
            raise DefinitionError(f"Definition is missing required part: {required}")
        validate_json_dict(payloads[required], label=f"remote {required}")
    for path, payload in payloads.items():
        if path.startswith(f"{VALUE_SETS_DIR}/"):
            validate_json_dict(payload, label=f"remote {path}")

    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    legacy_dir = dest / LEGACY_VALUE_SET_DIR
    if legacy_dir.is_dir():
        for child in legacy_dir.iterdir():
            if child.is_file():
                child.unlink()
        with suppress(OSError):
            legacy_dir.rmdir()
    for path, payload in payloads.items():
        output = dest / Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)
    return dest


def definition_has_platform(definition: dict[str, Any]) -> bool:
    """True when the definition includes a ``.platform`` part."""
    return any(
        isinstance(part, dict)
        and str(part.get("path", "")).replace("\\", "/") == PLATFORM_PART
        for part in definition.get("parts") or []
    )


def part_payloads(definition: dict[str, Any]) -> dict[str, bytes]:
    """Decode recognized parts, normalizing legacy ``valueSet/`` paths."""
    parts = definition.get("parts")
    if not isinstance(parts, list) or not parts:
        raise DefinitionError("Definition response has no parts")
    payloads: dict[str, bytes] = {}
    for part in parts:
        path, payload = _decode_part(part)
        normalized = _normalize_known_path(path)
        if normalized is not None:
            payloads[normalized] = payload
    return payloads


def folder_to_diff_text(path: Path | str) -> str:
    """Return stable multipart comparison text for a local Variable Library."""
    return _parts_to_diff_text(pack_definition(path))


def definition_to_diff_text(definition: dict[str, Any]) -> str:
    """Return stable multipart comparison text for a remote Variable Library."""
    return _parts_to_diff_text(definition)


def _parts_to_diff_text(definition: dict[str, Any]) -> str:
    payloads = part_payloads(definition)
    for required in REQUIRED_PARTS:
        if required not in payloads:
            raise DefinitionError(f"Definition is missing required part: {required}")
    rendered: list[tuple[str, str]] = []
    for path, payload in payloads.items():
        if path == PLATFORM_PART:
            continue
        data = validate_json_dict(payload, label=path)
        body = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        rendered.append((path, body))
    rendered.sort(key=lambda item: (item[0].lower(), item[0]))
    return "".join(f"--- {path}\n{body}" for path, body in rendered)


def _value_set_files(folder: Path) -> list[Path]:
    files: list[Path] = []
    for directory_name in (VALUE_SETS_DIR, LEGACY_VALUE_SET_DIR):
        directory = folder / directory_name
        if directory.is_dir():
            files.extend(
                file
                for file in directory.iterdir()
                if file.is_file() and file.suffix.lower() == ".json"
            )
    return sorted(files, key=lambda file: (file.name.lower(), file.name))


def _normalize_known_path(path: str) -> str | None:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized in {*REQUIRED_PARTS, PLATFORM_PART}:
        return normalized
    pieces = normalized.split("/")
    if (
        len(pieces) == 2
        and pieces[0] in {VALUE_SETS_DIR, LEGACY_VALUE_SET_DIR}
        and pieces[1].lower().endswith(".json")
        and pieces[1] not in {"", ".", ".."}
    ):
        return f"{VALUE_SETS_DIR}/{pieces[1]}"
    return None


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
    except Exception as exc:  # noqa: BLE001
        raise DefinitionError(f"Invalid base64 payload for part '{path}'") from exc

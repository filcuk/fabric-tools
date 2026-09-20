"""Pack and unpack Microsoft Fabric Org App definitions."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fabric_tools.parsing import ensure_kind_path_suffix

DEFINITION_PART = "definition.json"
PLATFORM_PART = ".platform"
REQUIRED_PARTS = (DEFINITION_PART,)
PAYLOAD_TYPE = "InlineBase64"


class DefinitionError(ValueError):
    """Invalid local Org App path or definition payload."""


def is_org_app_folder_name(name: str) -> bool:
    """True when *name* looks like a Fabric Git ``*.OrgApp`` folder."""
    return name.endswith(".OrgApp") or name.endswith(".orgapp")


def detect_org_app_path(path: Path | str) -> Path:
    """Resolve *path* as an Org App folder path (does not check contents).

    Bare stems (e.g. ``myApp``) become ``myApp.OrgApp``. Existing folders that
    already contain ``definition.json`` are left unchanged.
    """
    return ensure_kind_path_suffix(
        path,
        canonical_suffix=".OrgApp",
        accepted_suffixes=(".OrgApp", ".orgapp"),
        bare_content_ok=lambda p: p.is_dir() and (p / DEFINITION_PART).is_file(),
    )


def display_name_from_path(path: Path | str) -> str:
    """Return the default Fabric display name for a local Org App folder."""
    folder = Path(path)
    name = folder.name
    if name.endswith(".OrgApp"):
        return name[: -len(".OrgApp")]
    if name.endswith(".orgapp"):
        return name[: -len(".orgapp")]
    return name


def validate_definition_dict(
    data: Any, *, label: str = DEFINITION_PART
) -> dict[str, Any]:
    """Lightly validate a parsed ``definition.json`` object."""
    if not isinstance(data, dict):
        raise DefinitionError(f"{label}: expected a JSON object")
    if not isinstance(data.get("elements"), list):
        raise DefinitionError(f"{label}: missing list 'elements'")
    schema = data.get("$schema")
    if schema is not None and not isinstance(schema, str):
        raise DefinitionError(f"{label}: '$schema' must be a string when present")
    return data


def load_org_app_definition(path: Path | str) -> dict[str, Any]:
    """Read and validate a local ``definition.json`` file."""
    definition_path = Path(path)
    if not definition_path.is_file():
        raise DefinitionError(f"Org App definition file not found: {definition_path}")
    try:
        text = definition_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise DefinitionError(
            f"cannot read Org App definition {definition_path}: {exc}"
        ) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DefinitionError(f"invalid JSON in {definition_path}: {exc}") from exc
    return validate_definition_dict(data, label=str(definition_path))


def validate_local_org_app(path: Path | str) -> Path:
    """Ensure *path* is a packable Org App folder; return the folder path."""
    folder = detect_org_app_path(path)
    if not folder.is_dir():
        raise DefinitionError(f"Org App folder not found: {folder}")
    definition_path = folder / DEFINITION_PART
    if not definition_path.is_file():
        raise DefinitionError(
            f"Org App folder is missing '{DEFINITION_PART}': {folder}"
        )
    load_org_app_definition(definition_path)
    return folder


def pack_definition(path: Path | str) -> dict[str, Any]:
    """Build a Fabric Org App definition from a local folder."""
    folder = validate_local_org_app(path)
    parts = [_part(DEFINITION_PART, (folder / DEFINITION_PART).read_bytes())]
    platform = folder / PLATFORM_PART
    if platform.is_file():
        parts.append(_part(PLATFORM_PART, platform.read_bytes()))
    return {"parts": parts}


def unpack_definition(definition: dict[str, Any], destination: Path | str) -> Path:
    """Write a Fabric definition response to a local Org App folder."""
    dest = Path(destination)
    payloads = part_payloads(definition)
    if DEFINITION_PART not in payloads:
        raise DefinitionError(f"Definition is missing required part: {DEFINITION_PART}")
    try:
        data = json.loads(payloads[DEFINITION_PART].decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DefinitionError(f"Invalid remote {DEFINITION_PART}: {exc}") from exc
    validate_definition_dict(data, label=f"remote {DEFINITION_PART}")

    dest.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        if name in {DEFINITION_PART, PLATFORM_PART}:
            (dest / name).write_bytes(payload)
    return dest


def definition_has_platform(definition: dict[str, Any]) -> bool:
    """True when the definition includes a ``.platform`` part."""
    parts = definition.get("parts") or []
    return any(
        isinstance(part, dict) and Path(str(part.get("path", ""))).name == PLATFORM_PART
        for part in parts
    )


def part_payloads(definition: dict[str, Any]) -> dict[str, bytes]:
    """Decode definition parts to a ``{filename: bytes}`` map (last wins)."""
    parts = definition.get("parts")
    if not isinstance(parts, list) or not parts:
        raise DefinitionError("Definition response has no parts")
    payloads: dict[str, bytes] = {}
    for part in parts:
        path, payload = _decode_part(part)
        payloads[Path(path).name] = payload
    return payloads


def folder_to_diff_text(path: Path | str) -> str:
    """Return stable pretty JSON for a local Org App comparison."""
    folder = validate_local_org_app(path)
    return _normalize_definition((folder / DEFINITION_PART).read_bytes())


def definition_to_diff_text(definition: dict[str, Any]) -> str:
    """Return stable pretty JSON for a remote Org App comparison."""
    payloads = part_payloads(definition)
    if DEFINITION_PART not in payloads:
        raise DefinitionError(f"Definition is missing required part: {DEFINITION_PART}")
    return _normalize_definition(payloads[DEFINITION_PART])


def _normalize_definition(payload: bytes) -> str:
    try:
        data = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DefinitionError(f"Invalid {DEFINITION_PART}: {exc}") from exc
    validate_definition_dict(data)
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


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

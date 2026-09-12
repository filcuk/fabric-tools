"""Pack and unpack Fabric DataPipeline public definitions (Git-style folders)."""

from __future__ import annotations

import base64
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

CONTENT_PART = "pipeline-content.json"
PLATFORM_PART = ".platform"
SCHEDULES_PART = ".schedules"
REQUIRED_PARTS = (CONTENT_PART,)
OPTIONAL_PARTS = (PLATFORM_PART, SCHEDULES_PART)
# Parts included in compare diffs (exclude .platform — logicalId noise).
DIFF_PARTS = (CONTENT_PART, SCHEDULES_PART)
PAYLOAD_TYPE = "InlineBase64"


class DefinitionError(ValueError):
    """Invalid local pipeline path or definition payload."""


def is_pipeline_folder_name(name: str) -> bool:
    """True when *name* looks like a Fabric Git ``*.DataPipeline`` folder."""
    return name.endswith(".DataPipeline") or name.endswith(".datapipeline")


def detect_pipeline_path(path: Path | str) -> Path:
    """Resolve *path* as a DataPipeline folder path (does not check contents)."""
    p = Path(path)
    if is_pipeline_folder_name(p.name):
        return p
    if p.is_dir() and (p / CONTENT_PART).is_file():
        return p
    raise DefinitionError(
        f"Unsupported pipeline path '{p}'. Expected a *.DataPipeline folder "
        f"(with {CONTENT_PART})."
    )


def display_name_from_path(path: Path | str) -> str:
    """Default Fabric display name from a local ``*.DataPipeline`` folder stem."""
    p = Path(path)
    name = p.name
    if name.endswith(".DataPipeline"):
        return name[: -len(".DataPipeline")]
    if name.endswith(".datapipeline"):
        return name[: -len(".datapipeline")]
    return p.name


def validate_pipeline_content_dict(
    data: Any, *, label: str = CONTENT_PART
) -> dict[str, Any]:
    """Validate a parsed ``pipeline-content.json`` object (light structural check)."""
    if not isinstance(data, dict):
        raise DefinitionError(f"{label}: expected a JSON object")
    properties = data.get("properties")
    if not isinstance(properties, dict):
        raise DefinitionError(f"{label}: missing object 'properties'")
    return data


def load_pipeline_content(path: Path | str) -> dict[str, Any]:
    """Read and validate a local ``pipeline-content.json`` file."""
    p = Path(path)
    if not p.is_file():
        raise DefinitionError(f"pipeline content file not found: {p}")
    try:
        text = p.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise DefinitionError(f"cannot read pipeline content {p}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DefinitionError(f"invalid JSON in {p}: {exc}") from exc
    return validate_pipeline_content_dict(data, label=str(p))


def validate_local_pipeline(path: Path | str) -> Path:
    """Ensure *path* is a packable DataPipeline folder; return the folder path."""
    folder = detect_pipeline_path(path)
    if not folder.is_dir():
        raise DefinitionError(f"DataPipeline folder not found: {folder}")

    content_path = folder / CONTENT_PART
    if not content_path.is_file():
        raise DefinitionError(
            f"DataPipeline folder is missing '{CONTENT_PART}': {folder}"
        )

    load_pipeline_content(content_path)
    return folder


def pack_definition(
    path: Path | str,
    *,
    include_schedules: bool = False,
) -> dict[str, Any]:
    """Build a Fabric pipeline definition object from a local ``*.DataPipeline`` folder.

    By default omits ``.schedules`` (pipeline-only sync). Pass
    ``include_schedules=True`` to pack a local ``.schedules`` file when present.
    """
    folder = validate_local_pipeline(path)
    parts = [_part(CONTENT_PART, (folder / CONTENT_PART).read_bytes())]
    for name in _optional_part_names(include_schedules=include_schedules):
        optional = folder / name
        if optional.is_file():
            parts.append(_part(name, optional.read_bytes()))
    return {"parts": parts}


def unpack_definition(
    definition: dict[str, Any],
    destination: Path | str,
    *,
    include_schedules: bool = False,
) -> Path:
    """Write a Fabric definition response to a local pipeline folder.

    By default skips ``.schedules`` and removes a leftover local ``.schedules``.
    Returns the destination folder written.
    """
    dest = Path(destination)
    parts = definition.get("parts")
    if not isinstance(parts, list) or not parts:
        raise DefinitionError("Definition response has no parts")

    decoded_parts = [_decode_part(part) for part in parts]
    by_name = {Path(rel).name: payload for rel, payload in decoded_parts}
    missing = [name for name in REQUIRED_PARTS if name not in by_name]
    if missing:
        raise DefinitionError(
            "Definition is missing required part(s): " + ", ".join(missing)
        )

    try:
        content = json.loads(by_name[CONTENT_PART].decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DefinitionError(f"Invalid remote {CONTENT_PART}: {exc}") from exc
    validate_pipeline_content_dict(content, label=f"remote {CONTENT_PART}")

    dest.mkdir(parents=True, exist_ok=True)
    for relative_path, payload in decoded_parts:
        name = Path(relative_path).name
        if not include_schedules and name == SCHEDULES_PART:
            continue
        target = dest / name
        target.write_bytes(payload)
    if not include_schedules:
        leftover = dest / SCHEDULES_PART
        if leftover.is_file():
            leftover.unlink()
    return dest


def definition_without_schedules(definition: dict[str, Any]) -> dict[str, Any]:
    """Return *definition* with any ``.schedules`` parts removed (copy when needed)."""
    parts = definition.get("parts")
    if not isinstance(parts, list) or not parts:
        return definition
    filtered = [
        part
        for part in parts
        if not (
            isinstance(part, dict)
            and Path(str(part.get("path", ""))).name == SCHEDULES_PART
        )
    ]
    if len(filtered) == len(parts):
        return definition
    return {**definition, "parts": filtered}


def schedules_parts(definition: dict[str, Any]) -> list[dict[str, Any]]:
    """Return deep-copied ``.schedules`` part objects from *definition*."""
    parts = definition.get("parts")
    if not isinstance(parts, list) or not parts:
        return []
    return [
        deepcopy(part)
        for part in parts
        if isinstance(part, dict)
        and Path(str(part.get("path", ""))).name == SCHEDULES_PART
    ]


def definition_with_remote_schedules(
    definition: dict[str, Any],
    remote: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Attach remote ``.schedules`` parts onto *definition* (pipeline-only overwrite).

    Strips any schedules already on *definition*, then appends schedules from
    *remote* when present. Returns ``(merged, preserved)``.
    """
    base = definition_without_schedules(definition)
    remote_schedules = schedules_parts(remote)
    if not remote_schedules:
        return base, False
    parts = list(base.get("parts") or [])
    parts.extend(remote_schedules)
    return {**base, "parts": parts}, True


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


def part_payloads(
    definition: dict[str, Any],
    *,
    include_schedules: bool = False,
) -> dict[str, bytes]:
    """Decode definition parts to a ``{filename: bytes}`` map (last wins)."""
    parts = definition.get("parts")
    if not isinstance(parts, list) or not parts:
        raise DefinitionError("Definition response has no parts")
    out: dict[str, bytes] = {}
    for part in parts:
        path, payload = _decode_part(part)
        name = Path(path).name
        if not include_schedules and name == SCHEDULES_PART:
            continue
        out[name] = payload
    return out


def folder_payloads(
    path: Path | str,
    *,
    include_schedules: bool = False,
) -> dict[str, bytes]:
    """Read packable local pipeline parts into a ``{filename: bytes}`` map."""
    folder = validate_local_pipeline(path)
    payloads: dict[str, bytes] = {
        CONTENT_PART: (folder / CONTENT_PART).read_bytes(),
    }
    for name in _optional_part_names(include_schedules=include_schedules):
        optional = folder / name
        if optional.is_file():
            payloads[name] = optional.read_bytes()
    return payloads


def definition_to_diff_text(
    definition: dict[str, Any],
    *,
    include_schedules: bool = False,
) -> str:
    """Stable multi-file text used for unified diffs of a Fabric definition."""
    return payloads_to_diff_text(
        part_payloads(definition, include_schedules=include_schedules),
        include_schedules=include_schedules,
    )


def folder_to_diff_text(
    path: Path | str,
    *,
    include_schedules: bool = False,
) -> str:
    """Stable multi-file text used for unified diffs of a local pipeline folder."""
    return payloads_to_diff_text(
        folder_payloads(path, include_schedules=include_schedules),
        include_schedules=include_schedules,
    )


def payloads_to_diff_text(
    payloads: dict[str, bytes],
    *,
    include_schedules: bool = False,
) -> str:
    """Render compare-relevant part payloads as a deterministic multi-section text blob.

    Excludes ``.platform`` (logicalId differs across workspaces).
    """
    chunks: list[str] = []
    for name in _diff_part_names(include_schedules=include_schedules):
        if name not in payloads:
            continue
        chunks.append(f"=== {name} ===\n")
        chunks.append(_normalize_part_text(name, payloads[name]))
    return "".join(chunks)


def _optional_part_names(*, include_schedules: bool) -> tuple[str, ...]:
    if include_schedules:
        return OPTIONAL_PARTS
    return (PLATFORM_PART,)


def _diff_part_names(*, include_schedules: bool) -> tuple[str, ...]:
    if include_schedules:
        return DIFF_PARTS
    return (CONTENT_PART,)


def _normalize_part_text(name: str, payload: bytes) -> str:
    text = payload.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    lower = name.lower()
    if lower.endswith(".json") or lower in (PLATFORM_PART, SCHEDULES_PART):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return text if text.endswith("\n") else text + "\n"
        return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    return text if text.endswith("\n") else text + "\n"


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

"""Pack and unpack Fabric Dataflow Gen2 public definitions (Git-style folders)."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fabric_tools.parsing import ensure_kind_path_suffix

QUERY_METADATA_PART = "queryMetadata.json"
MASHUP_PART = "mashup.pq"
PLATFORM_PART = ".platform"
REQUIRED_PARTS = (QUERY_METADATA_PART, MASHUP_PART)
PAYLOAD_TYPE = "InlineBase64"
FORMAT_VERSION = "202502"


class DefinitionError(ValueError):
    """Invalid local dataflow path or definition payload."""


def is_dataflow_folder_name(name: str) -> bool:
    """True when *name* looks like a Fabric Git ``*.Dataflow`` folder."""
    return name.endswith(".Dataflow") or name.endswith(".dataflow")


def detect_dataflow_path(path: Path | str) -> Path:
    """Resolve *path* as a Dataflow Gen2 folder path (does not check contents).

    Bare stems (e.g. ``Ingest``) become ``Ingest.Dataflow``. Existing folders
    that already contain the required parts are left unchanged.
    """
    return ensure_kind_path_suffix(
        path,
        canonical_suffix=".Dataflow",
        accepted_suffixes=(".Dataflow", ".dataflow"),
        bare_content_ok=lambda p: (
            p.is_dir()
            and (p / QUERY_METADATA_PART).is_file()
            and (p / MASHUP_PART).is_file()
        ),
    )


def display_name_from_path(path: Path | str) -> str:
    """Default Fabric display name from a local ``*.Dataflow`` folder stem."""
    p = Path(path)
    name = p.name
    if name.endswith(".Dataflow"):
        return name[: -len(".Dataflow")]
    if name.endswith(".dataflow"):
        return name[: -len(".dataflow")]
    return p.name


def display_name_from_metadata(metadata: dict[str, Any]) -> str:
    """Return the dataflow name from ``queryMetadata.json``."""
    name = metadata.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return "Dataflow"


def validate_query_metadata_dict(
    data: Any, *, label: str = "queryMetadata.json"
) -> dict[str, Any]:
    """Validate a parsed ``queryMetadata.json`` object."""
    if not isinstance(data, dict):
        raise DefinitionError(f"{label}: expected a JSON object")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise DefinitionError(f"{label}: missing non-empty string 'name'")
    version = data.get("formatVersion")
    if version != FORMAT_VERSION:
        raise DefinitionError(
            f"{label}: formatVersion must be '{FORMAT_VERSION}' (got {version!r})"
        )
    return data


def load_query_metadata(path: Path | str) -> dict[str, Any]:
    """Read and validate a local ``queryMetadata.json`` file."""
    p = Path(path)
    if not p.is_file():
        raise DefinitionError(f"query metadata file not found: {p}")
    try:
        text = p.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise DefinitionError(f"cannot read query metadata {p}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DefinitionError(f"invalid JSON in {p}: {exc}") from exc
    return validate_query_metadata_dict(data, label=str(p))


def validate_local_dataflow(path: Path | str) -> Path:
    """Ensure *path* is a packable Dataflow Gen2 folder; return the folder path."""
    folder = detect_dataflow_path(path)
    if not folder.is_dir():
        raise DefinitionError(f"Dataflow folder not found: {folder}")

    metadata_path = folder / QUERY_METADATA_PART
    mashup_path = folder / MASHUP_PART
    if not metadata_path.is_file():
        raise DefinitionError(
            f"Dataflow folder is missing '{QUERY_METADATA_PART}': {folder}"
        )
    if not mashup_path.is_file():
        raise DefinitionError(f"Dataflow folder is missing '{MASHUP_PART}': {folder}")

    load_query_metadata(metadata_path)
    if mashup_path.stat().st_size == 0:
        raise DefinitionError(f"Dataflow mashup is empty: {mashup_path}")
    return folder


def pack_definition(path: Path | str) -> dict[str, Any]:
    """Build a Fabric dataflow definition object from a local ``*.Dataflow`` folder."""
    folder = validate_local_dataflow(path)
    parts = [
        _part(QUERY_METADATA_PART, (folder / QUERY_METADATA_PART).read_bytes()),
        _part(MASHUP_PART, (folder / MASHUP_PART).read_bytes()),
    ]
    platform = folder / PLATFORM_PART
    if platform.is_file():
        parts.append(_part(PLATFORM_PART, platform.read_bytes()))
    for mdf in sorted(folder.glob("*.mdf")):
        if mdf.is_file():
            parts.append(_part(mdf.name, mdf.read_bytes()))
    return {"parts": parts}


def unpack_definition(definition: dict[str, Any], destination: Path | str) -> Path:
    """Write a Fabric definition response to a local dataflow folder.

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

    # Light-validate metadata when present as JSON.
    try:
        metadata = json.loads(by_name[QUERY_METADATA_PART].decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DefinitionError(f"Invalid remote {QUERY_METADATA_PART}: {exc}") from exc
    validate_query_metadata_dict(metadata, label=f"remote {QUERY_METADATA_PART}")

    dest.mkdir(parents=True, exist_ok=True)
    for relative_path, payload in decoded_parts:
        target = dest / Path(relative_path).name
        target.write_bytes(payload)
    return dest


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
    """Decode definition parts to a ``{filename: bytes}`` map (last wins)."""
    parts = definition.get("parts")
    if not isinstance(parts, list) or not parts:
        raise DefinitionError("Definition response has no parts")
    out: dict[str, bytes] = {}
    for part in parts:
        path, payload = _decode_part(part)
        out[Path(path).name] = payload
    return out


def folder_payloads(path: Path | str) -> dict[str, bytes]:
    """Read packable local dataflow parts into a ``{filename: bytes}`` map."""
    folder = validate_local_dataflow(path)
    payloads: dict[str, bytes] = {
        QUERY_METADATA_PART: (folder / QUERY_METADATA_PART).read_bytes(),
        MASHUP_PART: (folder / MASHUP_PART).read_bytes(),
    }
    platform = folder / PLATFORM_PART
    if platform.is_file():
        payloads[PLATFORM_PART] = platform.read_bytes()
    for mdf in sorted(folder.glob("*.mdf")):
        if mdf.is_file():
            payloads[mdf.name] = mdf.read_bytes()
    return payloads


def definition_to_diff_text(definition: dict[str, Any]) -> str:
    """Stable multi-file text used for unified diffs of a Fabric definition."""
    return payloads_to_diff_text(part_payloads(definition))


def folder_to_diff_text(path: Path | str) -> str:
    """Stable multi-file text used for unified diffs of a local dataflow folder."""
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
    if lower.endswith(".json") or lower == PLATFORM_PART or lower.endswith(".mdf"):
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

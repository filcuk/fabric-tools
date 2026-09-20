"""Pack and unpack Fabric item definition parts (InlineBase64 folder trees)."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

PAYLOAD_TYPE = "InlineBase64"


class DefinitionPartsError(ValueError):
    """Invalid local folder or definition parts payload."""


def encode_part(path: str, payload: bytes) -> dict[str, str]:
    """Build one Fabric definition part from a relative path and raw bytes."""
    if not path or path.startswith("/") or "\\" in path:
        raise DefinitionPartsError(
            f"invalid definition part path {path!r}: use relative forward-slash paths"
        )
    if Path(path).is_absolute() or ".." in Path(path).parts:
        raise DefinitionPartsError(f"unsafe definition part path: {path}")
    return {
        "path": path.replace("\\", "/"),
        "payload": base64.b64encode(payload).decode("ascii"),
        "payloadType": PAYLOAD_TYPE,
    }


def decode_part(part: Any) -> tuple[str, bytes]:
    """Decode one definition part to ``(relative_path, bytes)``."""
    if not isinstance(part, dict):
        raise DefinitionPartsError("Definition part must be an object")
    path = part.get("path")
    payload = part.get("payload")
    payload_type = part.get("payloadType", PAYLOAD_TYPE)
    if not isinstance(path, str) or not path:
        raise DefinitionPartsError("Definition part is missing path")
    if not isinstance(payload, str):
        raise DefinitionPartsError(f"Definition part '{path}' is missing payload")
    if payload_type != PAYLOAD_TYPE:
        raise DefinitionPartsError(
            f"Unsupported payloadType '{payload_type}' for part '{path}' "
            f"(expected {PAYLOAD_TYPE})"
        )
    normalized = path.replace("\\", "/")
    if normalized.startswith("/") or ".." in Path(normalized).parts:
        raise DefinitionPartsError(f"unsafe definition part path: {path}")
    try:
        return normalized, base64.b64decode(payload, validate=False)
    except Exception as exc:  # noqa: BLE001 - surface as DefinitionPartsError
        raise DefinitionPartsError(f"Invalid base64 payload for part '{path}'") from exc


def pack_folder(root: Path | str) -> list[dict[str, str]]:
    """Recursively pack all files under *root* into Fabric definition parts.

    Paths are relative to *root* using forward slashes. Empty directories are
    omitted (Fabric definitions are file parts only).
    """
    base = Path(root)
    if not base.is_dir():
        raise DefinitionPartsError(f"definition folder not found: {base}")

    parts: list[dict[str, str]] = []
    for path in sorted(base.rglob("*"), key=lambda p: p.as_posix().lower()):
        if not path.is_file():
            continue
        relative = path.relative_to(base).as_posix()
        parts.append(encode_part(relative, path.read_bytes()))
    if not parts:
        raise DefinitionPartsError(f"definition folder has no files: {base}")
    return parts


def unpack_parts(
    parts: list[Any] | tuple[Any, ...],
    destination: Path | str,
) -> Path:
    """Write decoded definition parts under *destination*; returns the folder."""
    dest = Path(destination)
    if not parts:
        raise DefinitionPartsError("Definition has no parts")

    dest.mkdir(parents=True, exist_ok=True)
    for part in parts:
        relative, payload = decode_part(part)
        target = dest / relative
        # Resolve and ensure we stay under dest (belt-and-suspenders with decode).
        resolved = target.resolve()
        try:
            resolved.relative_to(dest.resolve())
        except ValueError as exc:
            raise DefinitionPartsError(
                f"definition part escapes destination: {relative}"
            ) from exc
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    return dest


def parts_from_definition(definition: dict[str, Any]) -> list[Any]:
    """Extract the ``parts`` list from a Fabric definition response object."""
    parts = definition.get("parts")
    if not isinstance(parts, list) or not parts:
        raise DefinitionPartsError("Definition response has no parts")
    return parts


def unpack_definition(
    definition: dict[str, Any],
    destination: Path | str,
) -> Path:
    """Unpack a Fabric ``{parts: [...]}`` definition object to a local folder."""
    return unpack_parts(parts_from_definition(definition), destination)


def pack_definition(
    root: Path | str,
    *,
    format: str | None = None,
) -> dict[str, Any]:
    """Build a Fabric definition object from a local folder.

    When *format* is set it is included on the definition (e.g. ``TMDL``, ``PBIR``).
    """
    definition: dict[str, Any] = {"parts": pack_folder(root)}
    if format is not None:
        definition["format"] = format
    return definition

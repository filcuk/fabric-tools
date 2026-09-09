"""Pack and unpack Fabric notebook public definitions."""

from __future__ import annotations

import base64
import json
from copy import deepcopy
from enum import Enum
from pathlib import Path
from typing import Any

FABRIC_GIT_CONTENT_NAMES = (
    "notebook-content.py",
    "notebook-content.sql",
    "notebook-content.scala",
    "notebook-content.r",
)
IPYNB_PART_PATH = "artifact.content.ipynb"
PLATFORM_PART_PATH = ".platform"
PAYLOAD_TYPE = "InlineBase64"
# Fabric stores default lakehouse / environment under metadata.dependencies.
PRESERVE_DEPENDENCY_KEYS = ("lakehouse", "environment")


class NotebookFormat(str, Enum):
    IPYNB = "ipynb"
    FABRIC_GIT = "fabricGitSource"


class DefinitionError(ValueError):
    """Invalid local notebook path or definition payload."""


def detect_format(path: Path | str) -> NotebookFormat:
    """Infer definition format from a local file or `.Notebook` folder path."""
    p = Path(path)
    name = p.name
    if name.endswith(".Notebook") or name.endswith(".notebook"):
        return NotebookFormat.FABRIC_GIT
    if p.suffix.lower() == ".ipynb":
        return NotebookFormat.IPYNB
    raise DefinitionError(
        f"Unsupported notebook path '{p}'. Expected a .ipynb file or a *.Notebook folder."
    )


def display_name_from_path(path: Path | str) -> str:
    """Default Fabric display name from a local path stem."""
    p = Path(path)
    name = p.name
    if name.endswith(".Notebook"):
        return name[: -len(".Notebook")]
    if name.endswith(".notebook"):
        return name[: -len(".notebook")]
    return p.stem


def validate_local_notebook(path: Path | str) -> NotebookFormat:
    """Ensure the path exists and looks like a packable notebook. Returns format."""
    p = Path(path)
    fmt = detect_format(p)
    if fmt is NotebookFormat.IPYNB:
        if not p.is_file():
            raise DefinitionError(f"Notebook file not found: {p}")
        _read_ipynb(p)  # validate JSON shape
        return fmt

    if not p.is_dir():
        raise DefinitionError(f"Notebook folder not found: {p}")
    content = _find_fabric_git_content(p)
    platform = p / PLATFORM_PART_PATH
    if not platform.is_file():
        raise DefinitionError(
            f"Fabric Git notebook folder is missing '{PLATFORM_PART_PATH}': {p}"
        )
    if content is None:
        expected = ", ".join(FABRIC_GIT_CONTENT_NAMES)
        raise DefinitionError(
            f"Fabric Git notebook folder is missing a content file ({expected}): {p}"
        )
    return fmt


def pack_definition(path: Path | str) -> dict[str, Any]:
    """Build a Fabric notebook definition object from a local path."""
    p = Path(path)
    fmt = validate_local_notebook(p)
    if fmt is NotebookFormat.IPYNB:
        return pack_ipynb_bytes(p.read_bytes())

    content_path = _find_fabric_git_content(p)
    assert content_path is not None
    parts = [
        _part(content_path.name, content_path.read_bytes()),
        _part(PLATFORM_PART_PATH, (p / PLATFORM_PART_PATH).read_bytes()),
    ]
    # Include known optional top-level definition companions when present.
    for optional_name in ("notebook-settings.json", "fs-settings.json"):
        optional = p / optional_name
        if optional.is_file():
            parts.append(_part(optional_name, optional.read_bytes()))
    return {"format": fmt.value, "parts": parts}


def pack_ipynb_bytes(raw: bytes) -> dict[str, Any]:
    """Build an ipynb-format Fabric definition from raw .ipynb bytes."""
    return {
        "format": NotebookFormat.IPYNB.value,
        "parts": [_part(IPYNB_PART_PATH, raw)],
    }


def pack_ipynb_dict(notebook: dict[str, Any]) -> dict[str, Any]:
    """Build an ipynb-format Fabric definition from a notebook object."""
    if "cells" not in notebook:
        raise DefinitionError("Invalid notebook object: missing cells")
    raw = json.dumps(notebook, ensure_ascii=False).encode("utf-8")
    return pack_ipynb_bytes(raw)


def read_ipynb(path: Path | str) -> dict[str, Any]:
    """Load and validate a local ``.ipynb`` file."""
    return _read_ipynb(Path(path))


def merge_remote_dependencies(
    local: dict[str, Any],
    remote: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Copy remote Fabric dependency metadata into *local* when omitted.

    Under ``metadata.dependencies``, for each of ``lakehouse`` and
    ``environment``: if the local notebook lacks that key, copy the remote
    value. Explicit local values (including empty ``{}``) are left unchanged so
    intentional clears are possible.

    Returns ``(merged_notebook, preserved_keys)`` where *preserved_keys* lists
    dependency keys that were filled from remote.
    """
    merged = deepcopy(local)
    remote_meta = remote.get("metadata")
    if not isinstance(remote_meta, dict):
        return merged, []
    remote_deps = remote_meta.get("dependencies")
    if not isinstance(remote_deps, dict) or not remote_deps:
        return merged, []

    local_meta = merged.get("metadata")
    if not isinstance(local_meta, dict):
        local_meta = {}
        merged["metadata"] = local_meta

    local_deps = local_meta.get("dependencies")
    if not isinstance(local_deps, dict):
        local_deps = {}
        local_meta["dependencies"] = local_deps

    preserved: list[str] = []
    for key in PRESERVE_DEPENDENCY_KEYS:
        if key in local_deps:
            continue
        remote_val = remote_deps.get(key)
        if remote_val is None:
            continue
        local_deps[key] = deepcopy(remote_val)
        preserved.append(key)
    return merged, preserved


def ipynb_from_definition(definition: dict[str, Any]) -> dict[str, Any]:
    """Decode the ``.ipynb`` content part from a Fabric definition response."""
    parts = definition.get("parts")
    if not isinstance(parts, list) or not parts:
        raise DefinitionError("Definition response has no parts")
    decoded = [_decode_part(part) for part in parts]
    raw = _select_ipynb_bytes(decoded)
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DefinitionError(f"Invalid remote .ipynb content: {exc}") from exc
    if not isinstance(data, dict) or "cells" not in data:
        raise DefinitionError("Invalid remote .ipynb content: missing cells")
    return data


def unpack_definition(
    definition: dict[str, Any],
    destination: Path | str,
    *,
    format_hint: NotebookFormat | None = None,
) -> Path:
    """Write a Fabric definition response to a local .ipynb or `.Notebook` folder.

    Returns the destination path written.
    """
    dest = Path(destination)
    parts = definition.get("parts")
    if not isinstance(parts, list) or not parts:
        raise DefinitionError("Definition response has no parts")

    fmt = format_hint
    if fmt is None:
        raw_format = definition.get("format")
        if isinstance(raw_format, str) and raw_format.lower() == NotebookFormat.IPYNB.value:
            fmt = NotebookFormat.IPYNB
        elif isinstance(raw_format, str) and raw_format.lower() in {
            NotebookFormat.FABRIC_GIT.value.lower(),
            "fabricgitsource",
        }:
            fmt = NotebookFormat.FABRIC_GIT
        else:
            fmt = detect_format(dest)

    decoded_parts = [_decode_part(part) for part in parts]

    if fmt is NotebookFormat.IPYNB:
        content = _select_ipynb_bytes(decoded_parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        return dest

    dest.mkdir(parents=True, exist_ok=True)
    for relative_path, payload in decoded_parts:
        # Keep definition parts flat under the .Notebook folder.
        target = dest / Path(relative_path).name
        target.write_bytes(payload)
    return dest


def definition_has_platform(definition: dict[str, Any]) -> bool:
    """True when the definition includes a `.platform` part."""
    parts = definition.get("parts") or []
    for part in parts:
        if isinstance(part, dict) and Path(str(part.get("path", ""))).name == PLATFORM_PART_PATH:
            return True
    return False


def format_for_api(fmt: NotebookFormat) -> str:
    """Format query/body value expected by Fabric notebook APIs."""
    return fmt.value


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


def _find_fabric_git_content(folder: Path) -> Path | None:
    for name in FABRIC_GIT_CONTENT_NAMES:
        candidate = folder / name
        if candidate.is_file():
            return candidate
    return None


def _read_ipynb(path: Path) -> dict[str, Any]:
    try:
        # utf-8-sig tolerates a Windows BOM from editors/shells.
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DefinitionError(f"Invalid .ipynb file '{path}': {exc}") from exc
    if not isinstance(data, dict) or "cells" not in data:
        raise DefinitionError(f"Invalid .ipynb file '{path}': missing cells")
    return data


def _select_ipynb_bytes(parts: list[tuple[str, bytes]]) -> bytes:
    preferred_names = {
        IPYNB_PART_PATH,
        "notebook-content.ipynb",
        "artifact.content.ipynb",
    }
    for path, payload in parts:
        name = Path(path).name
        if name in preferred_names or name.endswith(".ipynb"):
            return payload
    raise DefinitionError("Definition has no .ipynb content part")

"""Load and apply cross-workspace GUID remapping for Fabric definitions."""

from __future__ import annotations

import json
import re
import uuid
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fabric_tools.definition_parts import decode_part, encode_part

# Standard GUID / UUID text form (any hex case).
_GUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

# Metadata part: logicalId remapping is rarely desired for promote.
_SKIP_PART_NAMES = frozenset({".platform"})

# Known binary / non-text parts (extend as needed).
_BINARY_SUFFIXES = (".whl",)


class GuidMapError(ValueError):
    """Invalid GUID map file or pairing."""


@dataclass(frozen=True)
class GuidMapSpec:
    """One loaded GUID map and the path it came from."""

    path: Path
    mapping: dict[str, str]


def load_guid_map(path: Path | str) -> dict[str, str]:
    """Load a flat JSON object of source GUID → target GUID.

    Keys and values are normalized to canonical UUID strings (lowercase).
    """
    p = Path(path)
    if not p.is_file():
        raise GuidMapError(f"GUID map file not found: {p}")
    try:
        text = p.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise GuidMapError(f"cannot read GUID map {p}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GuidMapError(f"invalid JSON in GUID map {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise GuidMapError(f"GUID map {p}: expected a JSON object")
    if not data:
        raise GuidMapError(f"GUID map {p}: map is empty")

    mapping: dict[str, str] = {}
    for raw_key, raw_value in data.items():
        key = _parse_guid(raw_key, what=f"key in {p}")
        if not isinstance(raw_value, str):
            raise GuidMapError(
                f"GUID map {p}: value for {raw_key!r} must be a GUID string"
            )
        value = _parse_guid(raw_value, what=f"value for {raw_key!r} in {p}")
        if key in mapping and mapping[key] != value:
            raise GuidMapError(
                f"GUID map {p}: duplicate key {key} with conflicting values"
            )
        mapping[key] = value
    return mapping


def resolve_guid_maps(
    remap_values: list[str] | None,
    n_targets: int,
) -> list[GuidMapSpec | None]:
    """Parse ``--remap`` / ``-r`` paths and pair 1:1 or broadcast one file to all targets.

    Returns one spec (or ``None``) per target. When *remap_values* is empty,
    returns ``[None] * n_targets``.
    """
    if not remap_values:
        return [None] * max(n_targets, 0)
    if n_targets < 1:
        raise GuidMapError("--remap / -r requires at least one target")

    paths: list[Path] = []
    for raw in remap_values:
        for piece in _split_csv(raw):
            paths.append(Path(piece))
    if not paths:
        raise GuidMapError("empty --remap / -r value")

    specs = [GuidMapSpec(path=path, mapping=load_guid_map(path)) for path in paths]
    if len(specs) == n_targets:
        return list(specs)
    if len(specs) == 1 and n_targets > 1:
        return [specs[0]] * n_targets
    raise GuidMapError(
        f"target/remap count mismatch: {n_targets} target(s), {len(specs)} remap "
        "file(s). Use equal counts, or one remap file to broadcast to all targets."
    )


def apply_guid_map_to_definition(
    definition: dict[str, Any],
    mapping: dict[str, str],
) -> tuple[dict[str, Any], int]:
    """Return a deep-copied definition with GUID string replacements applied.

    Replaces GUID tokens in UTF-8 text parts (case-insensitive match). Skips
    ``.platform`` and known binary suffixes. Does not mutate *definition*.
    Returns ``(new_definition, replacement_count)``.
    """
    if not mapping:
        return deepcopy(definition), 0

    parts = definition.get("parts")
    if not isinstance(parts, list) or not parts:
        raise GuidMapError("Definition has no parts to remap")

    new_parts: list[Any] = []
    total = 0
    for part in parts:
        if not isinstance(part, dict):
            new_parts.append(deepcopy(part))
            continue
        try:
            path, payload = decode_part(part)
        except Exception:
            new_parts.append(deepcopy(part))
            continue

        name = Path(path).name
        if name in _SKIP_PART_NAMES or name.lower().endswith(_BINARY_SUFFIXES):
            new_parts.append(encode_part(path, payload))
            continue

        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            new_parts.append(encode_part(path, payload))
            continue

        rewritten, count = replace_guids_in_text(text, mapping)
        total += count
        new_parts.append(encode_part(path, rewritten.encode("utf-8")))

    out = deepcopy(definition)
    out["parts"] = new_parts
    return out, total


def replace_guids_in_text(text: str, mapping: dict[str, str]) -> tuple[str, int]:
    """Replace GUID tokens in *text* using lowercase-keyed *mapping*."""
    if not mapping:
        return text, 0

    count = 0

    def _repl(match: re.Match[str]) -> str:
        nonlocal count
        key = match.group(0).lower()
        if key in mapping:
            count += 1
            return mapping[key]
        return match.group(0)

    return _GUID_RE.sub(_repl, text), count


def guid_map_confirm_line(specs: list[GuidMapSpec | None] | None) -> str | None:
    """One confirm/dry-run line describing applied GUID remaps, or ``None``."""
    if not specs or all(s is None for s in specs):
        return None
    concrete = [s for s in specs if s is not None]
    paths = [str(s.path) for s in concrete]
    if len(set(paths)) == 1 and len(concrete) == len(specs):
        n = len(concrete[0].mapping)
        return (
            f"GUID remap: {paths[0]} ({n} entr{'y' if n == 1 else 'ies'}; "
            "source GUID → target GUID in definition text)."
        )
    bits = [
        f"{s.path} ({len(s.mapping)})" if s is not None else "(none)" for s in specs
    ]
    return "GUID remaps: " + "; ".join(bits)


def _parse_guid(value: str, *, what: str) -> str:
    try:
        return str(uuid.UUID(str(value).strip()))
    except (ValueError, AttributeError, TypeError) as exc:
        raise GuidMapError(f"invalid GUID for {what}: {value!r}") from exc


def _split_csv(raw: str) -> list[str]:
    return [piece.strip() for piece in raw.split(",") if piece.strip()]

"""Local paginated-report ``.rdl`` load / validate / normalize helpers."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


class DefinitionError(ValueError):
    """Invalid local or remote paginated-report RDL."""


def load_rdl(path: Path) -> bytes:
    """Read and validate a local ``.rdl`` file; return raw bytes."""
    if not path.is_file():
        raise DefinitionError(f"rdl file not found: {path}")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise DefinitionError(f"cannot read rdl file {path}: {exc}") from exc
    validate_rdl_bytes(data, label=str(path))
    return data


def validate_local_rdl(path: Path) -> Path:
    """Ensure ``path`` is a readable ``.rdl``; return the path."""
    load_rdl(path)
    return path


def validate_rdl_bytes(data: bytes, *, label: str = "rdl") -> bytes:
    """Validate RDL bytes (non-empty XML with a ``Report`` root)."""
    if not data or not data.strip():
        raise DefinitionError(f"{label}: empty rdl content")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DefinitionError(f"{label}: not valid UTF-8: {exc}") from exc
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise DefinitionError(f"{label}: invalid XML: {exc}") from exc
    local = root.tag.rsplit("}", 1)[-1]
    if local != "Report":
        raise DefinitionError(f"{label}: expected root element 'Report', got '{local}'")
    return data


def display_name_from_path(path: Path) -> str:
    """Display name from a local ``.rdl`` path (file stem)."""
    stem = path.stem.strip()
    return stem if stem else "PaginatedReport"


def display_name_from_report(meta: dict[str, Any]) -> str:
    """Display name from Power BI report metadata."""
    name = meta.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return "PaginatedReport"


def ensure_paginated_report(
    meta: dict[str, Any], *, label: str = "report"
) -> dict[str, Any]:
    """Require ``reportType == PaginatedReport`` on metadata from Get Report."""
    report_type = meta.get("reportType")
    if report_type != "PaginatedReport":
        raise DefinitionError(
            f"{label}: expected reportType 'PaginatedReport', got {report_type!r}"
        )
    return meta


def write_rdl(data: bytes, path: Path) -> Path:
    """Write RDL bytes to ``path`` (creates parent dirs)."""
    validate_rdl_bytes(data, label=str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def normalize_rdl_for_compare(data: bytes) -> str:
    """Normalize RDL text for equality / unified diffs.

    Decodes UTF-8 (BOM-tolerant), normalizes newlines to ``\\n``, and ensures a
    trailing newline. Does not rewrite XML structure (prefixes/attrs stay intact).
    """
    validate_rdl_bytes(data, label="rdl")
    text = data.decode("utf-8-sig")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n"):
        text += "\n"
    return text


def rdl_to_diff_text(data: bytes) -> str:
    """Text used for unified diffs."""
    return normalize_rdl_for_compare(data)

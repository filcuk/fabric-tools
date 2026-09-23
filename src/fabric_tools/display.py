"""Formatting for GUIDs and local paths in informational CLI lines.

Command results (inspect list/get, compare ``TARGET``, manifest selectors) keep
full GUIDs and do not use these helpers.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

GUID_LENGTH_ENV = "FABRIC_TOOLS_GUID_LENGTH"
DEFAULT_GUID_LENGTH = 7
_FULL_GUID_LENGTH = 36
_FULL_VALUES = frozenset({"full", "0", str(_FULL_GUID_LENGTH)})

GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def is_guid(value: str) -> bool:
    return bool(GUID_RE.fullmatch(value.strip()))


def resolve_guid_length() -> int | None:
    """Return the GUID prefix length for display, or ``None`` for full GUIDs.

    Invalid values fall back to the default: a display preference must not
    fail the command.
    """
    raw = os.environ.get(GUID_LENGTH_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_GUID_LENGTH
    text = raw.strip().lower()
    if text in _FULL_VALUES:
        return None
    try:
        value = int(text)
    except ValueError:
        return DEFAULT_GUID_LENGTH
    if 1 <= value < _FULL_GUID_LENGTH:
        return value
    return DEFAULT_GUID_LENGTH


def format_guid(value: str, *, length: int | None = None) -> str:
    """Shorten a GUID to its prefix (e.g. ``a1b2c3d``); non-GUIDs pass through."""
    text = value.strip()
    if not is_guid(text):
        return value
    n = resolve_guid_length() if length is None else length
    if n is None or n < 1 or n >= len(text):
        return text
    return text[:n]


def format_item_ref(name: str | None, item_id: str | None) -> str:
    """``Sales (a1b2c3d)``; only the short id when the name is missing or a GUID."""
    label = (name or "").strip()
    if not item_id:
        return label or "-"
    short = format_guid(item_id)
    if not label or label == item_id or is_guid(label):
        return short
    return f"{label} ({short})"


def format_local_path(path: str | Path) -> str:
    """Return *path* relative to the current directory when it lies under it.

    Paths outside the current directory stay absolute: ``..\\..\\AppData\\…`` is
    harder to read than the full path.
    """
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(resolved)

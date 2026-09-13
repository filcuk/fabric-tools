"""Transient activity status for long-running CLI work."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from rich.console import Console
from rich.status import Status

_console = Console(stderr=True)
_active: ContextVar[Status | None] = ContextVar("fabric_tools_status", default=None)
_message: ContextVar[str | None] = ContextVar(
    "fabric_tools_status_message", default=None
)
_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def short_guid(value: str, *, length: int = 8) -> str:
    """Return a truncated GUID for spinner text (e.g. ``a1b2c3d4…``)."""
    if length < 1 or len(value) <= length:
        return value
    return f"{value[:length]}…"


def progress_message(current: int, total: int, detail: str) -> str:
    """Format a step-prefixed status line: ``1 of 4 · detail``."""
    return f"{current} of {total} · {detail}"


def status_detail(verb: str, kind: str, label: str | None = None) -> str:
    """Build spinner detail text: ``Comparing report (Sales)…``.

    Full GUIDs are shortened; other labels (display names) are shown clipped.
    """
    if label:
        return f"{verb} {kind} ({_format_label(label)})…"
    return f"{verb} {kind}…"


def _format_label(label: str, *, max_length: int = 48) -> str:
    text = label.strip()
    if _GUID_RE.fullmatch(text):
        return short_guid(text)
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 1]}…"


@dataclass
class BatchProgress:
    """Mutable ``n of m`` counter for batch spinner updates."""

    current: int = 0
    total: int = 0

    def advance(self, detail: str) -> None:
        self.current += 1
        update(progress_message(self.current, self.total, detail))

    def skip_planned(self) -> None:
        if self.total > self.current:
            self.total -= 1


@contextmanager
def busy(message: str) -> Iterator[None]:
    """Show a spinner status line while work runs.

    Nested ``busy`` calls rewrite the same spinner and restore the parent
    message on exit. On a non-TTY stderr, prints each distinct message once.
    """
    parent = _active.get()
    if parent is not None:
        prev = _message.get()
        parent.update(message)
        token_msg = _message.set(message)
        try:
            yield
        finally:
            _message.reset(token_msg)
            if prev is not None:
                parent.update(prev)
        return

    if not _console.is_terminal:
        _console.print(message, highlight=False)
        token_msg = _message.set(message)
        try:
            yield
        finally:
            _message.reset(token_msg)
        return

    with _console.status(message, spinner="dots") as status:
        token = _active.set(status)
        token_msg = _message.set(message)
        try:
            yield
        finally:
            _message.reset(token_msg)
            _active.reset(token)


def update(message: str) -> None:
    """Update the active status message, if any.

    No-op when no ``busy`` context is active. On non-TTY, prints only when the
    message changes (e.g. phase transitions during a batch).
    """
    current = _message.get()
    if current == message:
        return

    status = _active.get()
    if status is not None:
        status.update(message)
        _message.set(message)
        return

    if current is not None and not _console.is_terminal:
        _console.print(message, highlight=False)
        _message.set(message)


def current_message() -> str | None:
    """Return the active status message, if any."""
    return _message.get()

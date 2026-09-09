"""Transient activity status for long-running CLI work."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from rich.console import Console
from rich.status import Status

_console = Console(stderr=True)
_active: ContextVar[Status | None] = ContextVar("fabric_tools_status", default=None)
_message: ContextVar[str | None] = ContextVar("fabric_tools_status_message", default=None)


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
    message changes (e.g. phase transitions during LRO waits).
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

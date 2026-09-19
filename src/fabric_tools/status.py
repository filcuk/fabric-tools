"""Transient activity status for long-running CLI work."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

_console = Console(stderr=True)
_active: ContextVar[_BusyHandle | None] = ContextVar(
    "fabric_tools_status", default=None
)
_message: ContextVar[str | None] = ContextVar(
    "fabric_tools_status_message", default=None
)
_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# Prefix used while Azure auth is in progress (nested busy / update guard).
AUTH_STATUS_PREFIX = "auth: authenticating"

# Spinner glyph colour (text stays primary / default — see DESIGN.md).
_SPINNER_STYLE = "green"


@dataclass
class _BusyHandle:
    """Spinner + Live pair; ``stop`` clears the line without advancing."""

    live: Live
    spinner: Spinner

    def update(self, message: str) -> None:
        self.spinner.update(text=Text(message))

    def stop(self) -> None:
        """End live rendering without Rich's trailing ``console.line()``.

        Clears the spinner line in place via ``position_cursor`` (erase current
        live lines). Do **not** use ``restore_cursor``: for a 1-line spinner it
        cursor-ups into the previous line (confirm prompt / prior output) and
        leaves a blank gap.
        """
        live = self.live
        with live._lock:
            if not live._started:
                return
            live._started = False
            live.console.clear_live()
            if live.auto_refresh and live._refresh_thread is not None:
                live._refresh_thread.stop()
                live._refresh_thread = None
            live._disable_redirect_io()
            live.console.pop_render_hook()
            live.console.show_cursor(True)
            if live.transient and not live._alt_screen:
                # Erase the spinner line(s) only — stay on that row.
                live.console.control(live._live_render.position_cursor())


def short_guid(value: str, *, length: int = 8) -> str:
    """Return a truncated GUID for spinner text (e.g. ``a1b2c3d4…``)."""
    if length < 1 or len(value) <= length:
        return value
    return f"{value[:length]}…"


def progress_message(current: int, total: int, detail: str) -> str:
    """Format a step-prefixed status line: ``1 of 4 · detail``."""
    return f"{current} of {total} · {detail}"


def status_detail(module: str, action: str, name: str | None = None) -> str:
    """Build spinner text: ``notebook: downloading (Sales)…``.

    *module* is the CLI group (e.g. ``notebook``, ``semantic-model``, ``auth``).
    *action* is a lowercase verb phrase (e.g. ``downloading``, ``adding role member``).
    *name* is an optional display name or short GUID; omitted when absent.
    """
    if name:
        return f"{module}: {action} ({_format_label(name)})…"
    return f"{module}: {action}…"


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

    Stopping does **not** advance the cursor (unlike Rich ``Status`` /
    ``Live.stop``), so the next prompt or spinner is not pushed down a blank
    line after confirms.

    Live must not redirect stdout/stderr — otherwise ``typer.confirm`` and auth
    hints are swallowed into the spinner and overwrite the prompt.
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

    spinner = Spinner("dots", text=Text(message), style=_SPINNER_STYLE)
    live = Live(
        spinner,
        console=_console,
        refresh_per_second=12.5,
        transient=True,
        redirect_stdout=False,
        redirect_stderr=False,
    )
    handle = _BusyHandle(live=live, spinner=spinner)
    live.start()
    token = _active.set(handle)
    token_msg = _message.set(message)
    try:
        yield
    finally:
        _message.reset(token_msg)
        _active.reset(token)
        handle.stop()


def update(message: str) -> None:
    """Update the active status message, if any.

    No-op when no ``busy`` context is active. On non-TTY, prints only when the
    message changes (e.g. phase transitions during a batch).
    """
    current = _message.get()
    if current == message:
        return

    handle = _active.get()
    if handle is not None:
        handle.update(message)
        _message.set(message)
        return

    if current is not None and not _console.is_terminal:
        _console.print(message, highlight=False)
        _message.set(message)


def clear() -> None:
    """Stop the active spinner so following stderr output is not mid-line.

    Safe to call when no ``busy`` context is active. The outer ``busy``
    ``finally`` still resets context tokens; calling ``stop`` twice is fine.
    """
    handle = _active.get()
    if handle is None:
        return
    handle.stop()


def current_message() -> str | None:
    """Return the active status message, if any."""
    return _message.get()

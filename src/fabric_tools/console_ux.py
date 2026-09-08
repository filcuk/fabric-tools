"""Console helpers for Windows exe UX."""

from __future__ import annotations

import sys


def owns_console_alone() -> bool:
    """True when this process is the only one attached to the console (typical double-click)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        # Probe size first.
        count = ctypes.windll.kernel32.GetConsoleProcessList(None, 0)
        if count <= 0:
            # Fallback: allocate a small buffer and ask again.
            buf = (ctypes.c_uint * 8)()
            count = ctypes.windll.kernel32.GetConsoleProcessList(buf, 8)
        return count == 1
    except Exception:
        return False


def pause_if_double_clicked(message: str | None = None) -> None:
    """Keep the window open after a double-click launch so the user can read output."""
    if not owns_console_alone():
        return
    if message:
        print(message)
    try:
        input("Press Enter to close...")
    except EOFError:
        pass

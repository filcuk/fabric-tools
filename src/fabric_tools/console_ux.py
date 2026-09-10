"""Console helpers for Windows exe UX."""

from __future__ import annotations

import contextlib
import os
import sys

# Processes that indicate an interactive shell already owns the console.
_SHELL_NAMES = frozenset(
    {
        "cmd.exe",
        "powershell.exe",
        "pwsh.exe",
        "bash.exe",
        "zsh.exe",
        "nu.exe",
        "fish.exe",
        "sh.exe",
    }
)

# Terminal hosts that may appear alongside the app when Explorer double-clicks
# a console exe (common on Windows 11 with Windows Terminal as default).
_CONSOLE_HOST_NAMES = frozenset(
    {
        "conhost.exe",
        "openconsole.exe",
        "windowsterminal.exe",
        "wt.exe",
    }
)


def _process_image_name(pid: int) -> str | None:
    """Return the executable basename for *pid*, or None on failure."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
        )
        if not handle:
            return None
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buf))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                path = buf.value.replace("/", "\\")
                return path.rsplit("\\", 1)[-1].lower()
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return None
    return None


def _console_process_names() -> list[str]:
    """Basenames of processes attached to this console."""
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.GetConsoleProcessList.argtypes = [
            ctypes.POINTER(wintypes.DWORD),
            wintypes.DWORD,
        ]
        kernel32.GetConsoleProcessList.restype = wintypes.DWORD

        capacity = 64
        while capacity <= 1024:
            buf = (wintypes.DWORD * capacity)()
            count = int(kernel32.GetConsoleProcessList(buf, capacity))
            if count == 0:
                return []
            if count <= capacity:
                names: list[str] = []
                for i in range(count):
                    name = _process_image_name(int(buf[i]))
                    if name:
                        names.append(name)
                return names
            capacity = max(count, capacity * 2)
    except Exception:
        return []
    return []


def _parent_image_name() -> str | None:
    """Basename of the parent process via Toolhelp snapshot."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        TH32CS_SNAPPROCESS = 0x00000002

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(wintypes.ULONG)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        kernel32 = ctypes.windll.kernel32
        pid = int(kernel32.GetCurrentProcessId())
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot in (-1, wintypes.HANDLE(-1).value):
            return None
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
                return None
            parent_pid = None
            while True:
                if int(entry.th32ProcessID) == pid:
                    parent_pid = int(entry.th32ParentProcessID)
                    break
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
            if parent_pid is None:
                return None
            return _process_image_name(parent_pid)
        finally:
            kernel32.CloseHandle(snapshot)
    except Exception:
        return None


def owns_console_alone() -> bool:
    """True when this looks like a double-click / Explorer-launched console window.

    Classic consoles often have a process list of length 1. Windows 11 with
    Windows Terminal as the default host may attach host processes too, so we
    also treat Explorer as parent, and "no shell on this console" as alone.
    """
    if sys.platform != "win32":
        return False

    parent = _parent_image_name()
    if parent == "explorer.exe":
        return True

    names = set(_console_process_names())
    if not names:
        return parent in _CONSOLE_HOST_NAMES if parent else False

    if names & _SHELL_NAMES:
        return False

    # Only console hosts (+ this app) → typical double-click into a new window/tab.
    our_name = _process_image_name(os.getpid())
    leftovers = names - _CONSOLE_HOST_NAMES
    if our_name:
        leftovers.discard(our_name)
    leftovers.discard("fabric-tools.exe")
    return len(leftovers) == 0


def pause_if_double_clicked(message: str | None = None) -> None:
    """Keep the window open after a double-click launch so the user can read output.

    Prefer ``msvcrt.getch`` / ``os.system("pause")`` over ``input()`` because
    some Windows Terminal double-click launches present stdin as already at EOF,
    which makes ``input()`` return immediately and the window flash-close.
    """
    if not owns_console_alone():
        return
    if message:
        print(message)
    print("Press any key to close...")
    try:
        import msvcrt

        msvcrt.getch()
        return
    except Exception:
        pass
    try:
        os.system("pause")
    except Exception:
        with contextlib.suppress(EOFError):
            input()

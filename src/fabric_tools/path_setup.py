"""Install fabric-tools onto the user PATH (Windows)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


INSTALL_DIR_NAME = "fabric-tools"
BIN_DIR_NAME = "bin"
EXE_NAME = "fabric-tools.exe"
CMD_NAME = "fabric-tools.cmd"


class PathSetupError(RuntimeError):
    """PATH registration failed."""


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def default_install_bin_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise PathSetupError("LOCALAPPDATA is not set; cannot choose install directory.")
    return Path(local_app_data) / INSTALL_DIR_NAME / BIN_DIR_NAME


def installed_exe_path(bin_dir: Path | None = None) -> Path:
    return (bin_dir or default_install_bin_dir()) / EXE_NAME


def installed_cmd_path(bin_dir: Path | None = None) -> Path:
    return (bin_dir or default_install_bin_dir()) / CMD_NAME


def install_to_user_path(*, bin_dir: Path | None = None) -> dict[str, str | bool]:
    """Copy/shim this tool into a stable folder and ensure that folder is on user PATH."""
    if os.name != "nt":
        raise PathSetupError("PATH registration is currently supported on Windows only.")

    target_bin = bin_dir or default_install_bin_dir()
    target_bin.mkdir(parents=True, exist_ok=True)

    if is_frozen():
        source = Path(sys.executable).resolve()
        destination = installed_exe_path(target_bin)
        shutil.copy2(source, destination)
        # Remove stale cmd shim if present from a previous Python install.
        cmd_path = installed_cmd_path(target_bin)
        if cmd_path.exists():
            cmd_path.unlink()
        launcher = str(destination)
        mode = "exe"
    else:
        destination = installed_cmd_path(target_bin)
        destination.write_text(
            "@echo off\r\n"
            f'"{sys.executable}" -m fabric_tools %*\r\n',
            encoding="utf-8",
        )
        # Prefer cmd shim for Python installs; remove stale copied exe if any.
        exe_path = installed_exe_path(target_bin)
        if exe_path.exists():
            exe_path.unlink()
        launcher = str(destination)
        mode = "cmd"

    path_added = ensure_user_path_contains(str(target_bin))
    return {
        "bin_dir": str(target_bin),
        "launcher": launcher,
        "mode": mode,
        "path_added": path_added,
        "already_on_path": not path_added and _user_path_contains(str(target_bin)),
    }


def uninstall_from_user_path(*, bin_dir: Path | None = None, delete_files: bool = True) -> dict[str, str | bool]:
    """Remove the install directory from user PATH and optionally delete installed files."""
    if os.name != "nt":
        raise PathSetupError("PATH registration is currently supported on Windows only.")

    target_bin = bin_dir or default_install_bin_dir()
    removed_from_path = remove_user_path_entry(str(target_bin))
    deleted: list[str] = []
    if delete_files and target_bin.exists():
        for path in (installed_exe_path(target_bin), installed_cmd_path(target_bin)):
            if path.exists():
                path.unlink()
                deleted.append(str(path))
        try:
            target_bin.rmdir()
            parent = target_bin.parent
            if parent.name == INSTALL_DIR_NAME:
                parent.rmdir()
        except OSError:
            pass

    return {
        "bin_dir": str(target_bin),
        "removed_from_path": removed_from_path,
        "deleted_files": ", ".join(deleted) if deleted else "",
    }


def path_status(*, bin_dir: Path | None = None) -> dict[str, str | bool]:
    target_bin = bin_dir or default_install_bin_dir()
    exe = installed_exe_path(target_bin)
    cmd = installed_cmd_path(target_bin)
    on_path = _user_path_contains(str(target_bin))
    which = shutil.which("fabric-tools")
    return {
        "bin_dir": str(target_bin),
        "exe_present": exe.is_file(),
        "cmd_present": cmd.is_file(),
        "bin_dir_on_user_path": on_path,
        "which_fabric_tools": which or "",
        "frozen": is_frozen(),
    }


def ensure_user_path_contains(directory: str) -> bool:
    """Add directory to the current user PATH if missing. Returns True if modified."""
    current = _read_user_path()
    normalized = _normalize_dir(directory)
    parts = _split_path(current)
    if any(_normalize_dir(part) == normalized for part in parts):
        return False
    updated = _join_path([*parts, directory]) if current else directory
    _write_user_path(updated)
    _broadcast_env_change()
    return True


def remove_user_path_entry(directory: str) -> bool:
    """Remove directory from the current user PATH if present. Returns True if modified."""
    current = _read_user_path()
    normalized = _normalize_dir(directory)
    parts = _split_path(current)
    kept = [part for part in parts if _normalize_dir(part) != normalized]
    if len(kept) == len(parts):
        return False
    _write_user_path(_join_path(kept))
    _broadcast_env_change()
    return True


def _user_path_contains(directory: str) -> bool:
    normalized = _normalize_dir(directory)
    return any(_normalize_dir(part) == normalized for part in _split_path(_read_user_path()))


def _read_user_path() -> str:
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Environment",
        0,
        winreg.KEY_READ,
    ) as key:
        try:
            value, _reg_type = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            return ""
    return str(value or "")


def _write_user_path(value: str) -> None:
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Environment",
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, value)


def _broadcast_env_change() -> None:
    """Best-effort notify; never block the CLI on hung window managers."""
    import threading

    def _send() -> None:
        try:
            import ctypes

            HWND_BROADCAST = 0xFFFF
            WM_SETTINGCHANGE = 0x001A
            SMTO_ABORTIFHUNG = 0x0002
            result = ctypes.c_long()
            ctypes.windll.user32.SendMessageTimeoutW(
                HWND_BROADCAST,
                WM_SETTINGCHANGE,
                0,
                "Environment",
                SMTO_ABORTIFHUNG,
                500,
                ctypes.byref(result),
            )
        except Exception:
            pass

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()
    thread.join(timeout=1.0)


def _split_path(value: str) -> list[str]:
    return [part for part in value.split(";") if part.strip()]


def _join_path(parts: list[str]) -> str:
    return ";".join(parts)


def _normalize_dir(value: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.expandvars(value.strip().rstrip("\\/"))))

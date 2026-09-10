"""Install fabric-tools onto the user PATH (Windows)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


INSTALL_DIR_NAME = "fabric-tools"
APP_DIR_NAME = "app"
LEGACY_BIN_DIR_NAME = "bin"
EXE_NAME = "fabric-tools.exe"
CMD_NAME = "fabric-tools.cmd"
INTERNAL_DIR_NAME = "_internal"


class PathSetupError(RuntimeError):
    """PATH registration failed."""


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def install_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise PathSetupError("LOCALAPPDATA is not set; cannot choose install directory.")
    return Path(local_app_data) / INSTALL_DIR_NAME


def default_install_dir() -> Path:
    """Directory containing the launcher (on PATH)."""
    return install_root() / APP_DIR_NAME


def legacy_bin_dir() -> Path:
    return install_root() / LEGACY_BIN_DIR_NAME


def installed_exe_path(install_dir: Path | None = None) -> Path:
    return (install_dir or default_install_dir()) / EXE_NAME


def installed_cmd_path(install_dir: Path | None = None) -> Path:
    return (install_dir or default_install_dir()) / CMD_NAME


def frozen_source_root() -> Path:
    """Directory that holds the running onedir exe and ``_internal``."""
    root = Path(sys.executable).resolve().parent
    internal = root / INTERNAL_DIR_NAME
    if not internal.is_dir():
        raise PathSetupError(
            "This executable is not a one-dir build (missing _internal next to the exe). "
            "Rebuild with packaging/fabric-tools.spec (via scripts/build_exe.ps1), then run "
            "setup install from dist\\fabric-tools.exe."
        )
    return root


def install_to_user_path(*, install_dir: Path | None = None) -> dict[str, str | bool]:
    """Copy/shim this tool into a stable folder and ensure that folder is on user PATH."""
    if os.name != "nt":
        raise PathSetupError("Setup registration is currently supported on Windows only.")

    target_dir = install_dir or default_install_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    if is_frozen():
        source_root = frozen_source_root()
        destination = installed_exe_path(target_dir)
        _install_frozen_tree(source_root, target_dir)
        # Remove stale cmd shim if present from a previous Python install.
        cmd_path = installed_cmd_path(target_dir)
        if cmd_path.exists():
            cmd_path.unlink()
        launcher = str(destination)
        mode = "exe"
    else:
        destination = installed_cmd_path(target_dir)
        destination.write_text(
            "@echo off\r\n"
            f'"{sys.executable}" -m fabric_tools %*\r\n',
            encoding="utf-8",
        )
        # Prefer cmd shim for Python installs; remove stale copied exe tree if any.
        _remove_frozen_tree(target_dir)
        launcher = str(destination)
        mode = "cmd"

    path_added = ensure_user_path_contains(str(target_dir))
    legacy_cleaned = _cleanup_legacy_bin_install()
    return {
        "install_dir": str(target_dir),
        "bin_dir": str(target_dir),  # backwards-compatible key for callers
        "launcher": launcher,
        "mode": mode,
        "path_added": path_added,
        "already_on_path": not path_added and _user_path_contains(str(target_dir)),
        "legacy_cleaned": legacy_cleaned,
    }


def uninstall_from_user_path(
    *,
    install_dir: Path | None = None,
    delete_files: bool = True,
) -> dict[str, str | bool]:
    """Remove the install directory from user PATH and optionally delete installed files."""
    if os.name != "nt":
        raise PathSetupError("Setup registration is currently supported on Windows only.")

    target_dir = install_dir or default_install_dir()
    removed_from_path = remove_user_path_entry(str(target_dir))
    # Also drop legacy bin PATH entry if present.
    legacy = legacy_bin_dir()
    removed_from_path = remove_user_path_entry(str(legacy)) or removed_from_path

    deleted: list[str] = []
    if delete_files:
        deleted.extend(_delete_install_tree(target_dir))
        deleted.extend(_delete_install_tree(legacy))
        _try_remove_empty_install_root()

    return {
        "install_dir": str(target_dir),
        "bin_dir": str(target_dir),
        "removed_from_path": removed_from_path,
        "deleted_files": ", ".join(deleted) if deleted else "",
    }


def path_status(*, install_dir: Path | None = None) -> dict[str, str | bool]:
    target_dir = install_dir or default_install_dir()
    exe = installed_exe_path(target_dir)
    cmd = installed_cmd_path(target_dir)
    internal = target_dir / INTERNAL_DIR_NAME
    on_path = _user_path_contains(str(target_dir))
    which = shutil.which("fabric-tools")
    return {
        "install_dir": str(target_dir),
        "bin_dir": str(target_dir),
        "exe_present": exe.is_file(),
        "cmd_present": cmd.is_file(),
        "internal_present": internal.is_dir(),
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


def _install_frozen_tree(source_root: Path, target_dir: Path) -> None:
    source_root = source_root.resolve()
    target_dir = target_dir.resolve()
    if source_root == target_dir:
        # Already running from the install location; just ensure files look complete.
        if not (target_dir / INTERNAL_DIR_NAME).is_dir():
            raise PathSetupError(
                f"Install directory is missing {INTERNAL_DIR_NAME}: {target_dir}"
            )
        return

    source_exe = source_root / EXE_NAME
    source_internal = source_root / INTERNAL_DIR_NAME
    if not source_exe.is_file() or not source_internal.is_dir():
        raise PathSetupError(
            f"Incomplete one-dir layout at {source_root} "
            f"(need {EXE_NAME} and {INTERNAL_DIR_NAME})."
        )

    target_dir.mkdir(parents=True, exist_ok=True)
    dest_internal = target_dir / INTERNAL_DIR_NAME
    if dest_internal.exists():
        shutil.rmtree(dest_internal)
    shutil.copytree(source_internal, dest_internal)
    shutil.copy2(source_exe, target_dir / EXE_NAME)


def _remove_frozen_tree(target_dir: Path) -> None:
    exe = installed_exe_path(target_dir)
    if exe.exists():
        exe.unlink()
    internal = target_dir / INTERNAL_DIR_NAME
    if internal.exists():
        shutil.rmtree(internal)


def _delete_install_tree(target_dir: Path) -> list[str]:
    deleted: list[str] = []
    if not target_dir.exists():
        return deleted
    for path in (installed_exe_path(target_dir), installed_cmd_path(target_dir)):
        if path.exists():
            path.unlink()
            deleted.append(str(path))
    internal = target_dir / INTERNAL_DIR_NAME
    if internal.exists():
        shutil.rmtree(internal)
        deleted.append(str(internal))
    try:
        target_dir.rmdir()
        deleted.append(str(target_dir))
    except OSError:
        pass
    return deleted


def _cleanup_legacy_bin_install() -> bool:
    """Remove old %LOCALAPPDATA%\\fabric-tools\\bin layout from PATH and disk."""
    legacy = legacy_bin_dir()
    changed = remove_user_path_entry(str(legacy))
    if legacy.exists():
        _delete_install_tree(legacy)
        changed = True
    _try_remove_empty_install_root()
    return changed


def _try_remove_empty_install_root() -> None:
    root = install_root()
    try:
        if root.exists() and not any(root.iterdir()):
            root.rmdir()
    except OSError:
        pass


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

"""Install fabric-tools onto the user PATH (Windows)."""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

INSTALL_DIR_NAME = "fabric-tools"
APP_DIR_NAME = "app"
LEGACY_BIN_DIR_NAME = "bin"
UPDATE_DIR_NAME = "update"
CACHE_DIR_NAME = "cache"
# Pre-cutover Nuitka onefile cache: %LOCALAPPDATA%\fabric-tools\fabric-tools\{VERSION}
LEGACY_ONEFILE_CACHE_DIR_NAME = "fabric-tools"
EXE_NAME = "fabric-tools.exe"
CMD_NAME = "fabric-tools.cmd"
INTERNAL_DIR_NAME = "_internal"
ONEDIR_BOOTLOADER_DIR = "_onedir_bootloader"
APPLY_UPDATE_HELPER_NAME = "apply-update.cmd"
CLEAR_ONEFILE_CACHE_HELPER_NAME = "clear-onefile-cache.cmd"


class PathSetupError(RuntimeError):
    """PATH registration failed."""


def _nuitka_compiled() -> Any | None:
    """Return Nuitka ``__compiled__`` from ``__main__`` or ``fabric_tools``, if present."""
    for name in ("__main__", "fabric_tools"):
        mod = sys.modules.get(name)
        if mod is None and name == "fabric_tools":
            try:
                import fabric_tools as mod
            except ImportError:
                continue
        if mod is None:
            continue
        compiled = getattr(mod, "__compiled__", None)
        if compiled is not None:
            return compiled
    return None


def is_frozen() -> bool:
    """True for PyInstaller (``sys.frozen``) or Nuitka (``__compiled__``) builds."""
    if bool(getattr(sys, "frozen", False)):
        return True
    return _nuitka_compiled() is not None


def install_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise PathSetupError(
            "LOCALAPPDATA is not set; cannot choose install directory."
        )
    return Path(local_app_data) / INSTALL_DIR_NAME


def default_install_dir() -> Path:
    """Directory containing the launcher (on PATH)."""
    return install_root() / APP_DIR_NAME


def legacy_bin_dir() -> Path:
    return install_root() / LEGACY_BIN_DIR_NAME


def onefile_cache_dir() -> Path:
    """Nuitka onefile extract cache (``--onefile-tempdir-spec`` …/cache/{VERSION})."""
    return install_root() / CACHE_DIR_NAME


def legacy_onefile_cache_dir() -> Path:
    """Old onefile cache nest ``…\\fabric-tools\\fabric-tools\\`` (pre cache\\ layout)."""
    return install_root() / LEGACY_ONEFILE_CACHE_DIR_NAME


def installed_exe_path(install_dir: Path | None = None) -> Path:
    return (install_dir or default_install_dir()) / EXE_NAME


def installed_cmd_path(install_dir: Path | None = None) -> Path:
    return (install_dir or default_install_dir()) / CMD_NAME


def meipass_dir() -> Path | None:
    """PyInstaller extract dir for a running onefile build, else ``None``."""
    raw = getattr(sys, "_MEIPASS", None)
    if not raw:
        return None
    return Path(raw)


def frozen_onedir_root() -> Path | None:
    """Parent of ``_internal`` when running an already-unpacked PyInstaller onedir build."""
    root = Path(sys.executable).resolve().parent
    if (root / INTERNAL_DIR_NAME).is_dir():
        return root
    return None


def _nuitka_payload_candidates() -> list[Path]:
    """Candidate directories for the running Nuitka payload (standalone or onefile extract)."""
    candidates: list[Path] = []

    def _add(path: Path | None) -> None:
        if path is None:
            return
        resolved = path.resolve()
        if resolved not in candidates:
            candidates.append(resolved)

    compiled = _nuitka_compiled()
    if compiled is not None:
        containing = getattr(compiled, "containing_dir", None)
        if containing:
            _add(Path(os.path.expanduser(str(containing))))

    # Onefile extract: __main__.__file__ is typically .../Temp/onefile_*/nuitka_entry.py
    main = sys.modules.get("__main__")
    main_file = getattr(main, "__file__", None) if main is not None else None
    if main_file:
        _add(Path(main_file).parent)

    try:
        import fabric_tools

        ft_file = getattr(fabric_tools, "__file__", None)
        if ft_file:
            package_dir = Path(ft_file).resolve().parent
            # .../payload/fabric_tools/__init__.py → payload root
            if package_dir.name == "fabric_tools":
                _add(package_dir.parent)
            else:
                _add(package_dir)
    except ImportError:
        pass

    _add(Path(sys.argv[0]).resolve().parent)
    return candidates


def frozen_app_root() -> Path | None:
    """Directory containing the frozen app payload (Nuitka or PyInstaller onedir).

    Nuitka ``__compiled__.containing_dir`` is unreliable (sometimes the build
    ``--output-dir``). For onefile, the real payload is the temp extract next to
    ``__main__.__file__``. Prefer any candidate that has native runtime siblings.
    """
    if _nuitka_compiled() is not None:
        candidates = _nuitka_payload_candidates()
        argv0_dir = Path(sys.argv[0]).resolve().parent

        with_runtime = [
            path for path in candidates if _has_nuitka_runtime_siblings(path)
        ]
        if with_runtime:
            # Installed / standalone: prefer the launch directory when it is complete.
            if argv0_dir in with_runtime:
                return argv0_dir
            return with_runtime[0]

        complete = [
            path
            for path in candidates
            if (path / EXE_NAME).is_file() and _has_nuitka_runtime_siblings(path)
        ]
        if complete:
            if argv0_dir in complete:
                return argv0_dir
            return complete[0]
        if candidates:
            return candidates[0]
        return None
    return frozen_onedir_root()


def _has_nuitka_runtime_siblings(directory: Path) -> bool:
    """True when a Nuitka standalone/extract folder has native runtime files beside the exe."""
    try:
        if (directory / "_ctypes.pyd").is_file():
            return True
        return any(
            child.is_file()
            and child.suffix.lower() == ".dll"
            and child.name.lower().startswith("python3")
            for child in directory.iterdir()
        )
    except OSError:
        return False


ONEFILE_TEMPDIR_SPEC = "{CACHE_DIR}/{COMPANY}/cache/{VERSION}"


def is_portable_onefile() -> bool:
    """True when running a one-file build that extracts on each launch."""
    if not is_frozen():
        return False
    if _nuitka_compiled() is not None:
        root = frozen_app_root()
        if root is None:
            return False
        argv0_dir = Path(sys.argv[0]).resolve().parent
        if argv0_dir == root:
            return False
        # Onefile: payload extract has runtime DLLs; the bootstrap exe directory does not.
        return _has_nuitka_runtime_siblings(root) and not _has_nuitka_runtime_siblings(
            argv0_dir
        )
    return meipass_dir() is not None and frozen_onedir_root() is None


def format_nuitka_orphan_exe_error() -> str | None:
    """Error when a Nuitka standalone exe was copied without its sibling DLLs.

    Onefile builds are never orphans: the bootstrap has no siblings by design; the
    payload lives in a cache/temp extract.
    """
    if _nuitka_compiled() is None:
        return None
    if is_portable_onefile():
        return None
    argv0_dir = Path(sys.argv[0]).resolve().parent
    if _has_nuitka_runtime_siblings(argv0_dir):
        return None
    root = frozen_app_root()
    if root is not None and _has_nuitka_runtime_siblings(root):
        return None
    for path in _nuitka_payload_candidates():
        if _has_nuitka_runtime_siblings(path):
            return None
    return (
        "This Nuitka fabric-tools.exe is missing its runtime payload. "
        "Use the onefile build from scripts\\build_exe.ps1 "
        "(dist\\fabric-tools.exe)."
    )


def install_to_user_path(*, install_dir: Path | None = None) -> dict[str, str | bool]:
    """Copy/shim this tool into a stable folder and ensure that folder is on user PATH.

    Frozen layouts:

    - Nuitka standalone / onefile extract: copy the full payload directory.
    - PyInstaller onefile: unpack ``sys._MEIPASS`` into ``exe`` + ``_internal`` (embedded
      onedir bootloader).
    - PyInstaller onedir / already-installed: copy ``exe`` + ``_internal``.
    """
    if os.name != "nt":
        raise PathSetupError(
            "Setup registration is currently supported on Windows only."
        )

    target_dir = install_dir or default_install_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    if is_frozen():
        destination = installed_exe_path(target_dir)
        layout = _install_frozen_app(target_dir)
        cmd_path = installed_cmd_path(target_dir)
        if cmd_path.exists():
            cmd_path.unlink()
        launcher = str(destination)
        mode = "exe"
    else:
        destination = installed_cmd_path(target_dir)
        destination.write_text(
            f'@echo off\r\n"{sys.executable}" -m fabric_tools %*\r\n',
            encoding="utf-8",
        )
        _remove_frozen_tree(target_dir)
        launcher = str(destination)
        mode = "cmd"
        layout = "python"

    path_added = ensure_user_path_contains(str(target_dir))
    legacy_cleaned = _cleanup_legacy_bin_install()
    cache_cleanup = _cleanup_onefile_caches()
    return {
        "install_dir": str(target_dir),
        "bin_dir": str(target_dir),
        "launcher": launcher,
        "mode": mode,
        "layout": layout,
        "path_added": path_added,
        "already_on_path": not path_added and _user_path_contains(str(target_dir)),
        "legacy_cleaned": legacy_cleaned,
        "cache_cleaned": cache_cleanup["cleaned"],
        "cache_cleanup_scheduled": cache_cleanup["scheduled"],
    }


def uninstall_from_user_path(
    *,
    install_dir: Path | None = None,
    delete_files: bool = True,
) -> dict[str, str | bool]:
    """Remove the install directory from user PATH and optionally delete installed files."""
    if os.name != "nt":
        raise PathSetupError(
            "Setup registration is currently supported on Windows only."
        )

    target_dir = install_dir or default_install_dir()
    removed_from_path = remove_user_path_entry(str(target_dir))
    legacy = legacy_bin_dir()
    removed_from_path = remove_user_path_entry(str(legacy)) or removed_from_path

    deleted: list[str] = []
    if delete_files:
        deleted.extend(_delete_install_tree(target_dir))
        deleted.extend(_delete_install_tree(legacy))
        deleted.extend(_delete_install_tree(onefile_cache_dir()))
        deleted.extend(_delete_install_tree(legacy_onefile_cache_dir()))
        deleted.extend(_delete_install_tree(update_staging_dir()))
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
    exe_present = exe.is_file()
    cmd_present = cmd.is_file()
    internal_present = internal.is_dir()
    runtime_present = _runtime_present(target_dir)
    return {
        "install_dir": str(target_dir),
        "bin_dir": str(target_dir),
        "exe_present": exe_present,
        "cmd_present": cmd_present,
        "internal_present": internal_present,
        "runtime_present": runtime_present,
        "bin_dir_on_user_path": on_path,
        "which_fabric_tools": which or "",
        "frozen": is_frozen(),
        "cache_present": _onefile_cache_present(),
        "install_state": _install_state(
            exe_present=exe_present,
            cmd_present=cmd_present,
            runtime_present=runtime_present,
            internal_present=internal_present,
        ),
    }


def _onefile_cache_present() -> bool:
    """True when a onefile extract cache directory exists (current or legacy)."""
    for directory in _onefile_cache_dirs():
        try:
            if directory.is_dir() and any(directory.iterdir()):
                return True
        except OSError:
            continue
    return False


def _install_state(
    *,
    exe_present: bool,
    cmd_present: bool,
    runtime_present: bool,
    internal_present: bool,
) -> str:
    """Return ``installed``, ``incomplete``, or ``not installed``."""
    if (exe_present and runtime_present) or (cmd_present and not exe_present):
        return "installed"
    if exe_present or cmd_present or runtime_present or internal_present:
        return "incomplete"
    return "not installed"


def update_staging_dir() -> Path:
    """Directory for downloaded release exe + deferred-install helper."""
    return install_root() / UPDATE_DIR_NAME


def perform_setup_update(*, silent: bool = False) -> dict[str, str | bool]:
    """Download the latest release exe and schedule install after this process exits."""
    if os.name != "nt":
        raise PathSetupError("setup update is currently supported on Windows only.")
    if not is_frozen():
        raise PathSetupError(
            "setup update requires the Windows .exe build; "
            "use: fabric-tools setup update --check"
        )

    from fabric_tools.confirm import confirm_or_abort
    from fabric_tools.status import busy
    from fabric_tools.update_check import (
        RELEASE_EXE_NAME,
        check_for_update,
        download_release_asset,
        save_update_cache,
    )

    with busy("Checking for updates..."):
        result = check_for_update()
    save_update_cache(result)

    if not result.update_available:
        return {
            "up_to_date": True,
            "current": result.current,
            "latest": result.latest,
            "scheduled": False,
            "exe_path": "",
        }

    if not result.asset_url:
        raise PathSetupError(
            f"Release {result.tag_name} has no {RELEASE_EXE_NAME} download asset."
        )

    label = result.tag_name
    if result.prerelease:
        label += " [pre-release]"
    confirm_or_abort(
        f"Download and install fabric-tools {label} (current {result.current})?",
        silent=silent,
    )

    staging = update_staging_dir()
    staging.mkdir(parents=True, exist_ok=True)
    exe_path = staging / EXE_NAME

    with busy(f"Downloading {result.tag_name}..."):
        download_release_asset(result.asset_url, exe_path)

    helper = staging / APPLY_UPDATE_HELPER_NAME
    _write_deferred_install_helper(helper)
    _spawn_deferred_install(helper, os.getpid(), exe_path)

    return {
        "up_to_date": False,
        "current": result.current,
        "latest": result.latest,
        "tag_name": result.tag_name,
        "scheduled": True,
        "exe_path": str(exe_path),
    }


def _write_deferred_install_helper(path: Path) -> None:
    """Write a cmd script that waits for a PID, then runs ``setup install``."""
    path.write_text(
        "\r\n".join(
            [
                "@echo off",
                "setlocal EnableExtensions",
                'set "PID=%~1"',
                'set "EXE=%~2"',
                ":waitloop",
                'tasklist /FI "PID eq %PID%" 2>NUL | findstr /I "%PID%" >NUL',
                "if not errorlevel 1 (",
                "  ping -n 2 127.0.0.1 >NUL",
                "  goto waitloop",
                ")",
                '"%EXE%" setup install',
                "exit /b %ERRORLEVEL%",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _spawn_deferred_install(helper: Path, pid: int, exe: Path) -> None:
    """Start the deferred install helper detached from this process."""
    creationflags = 0
    if hasattr(subprocess, "DETACHED_PROCESS"):
        creationflags |= subprocess.DETACHED_PROCESS
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags |= subprocess.CREATE_NO_WINDOW

    try:
        subprocess.Popen(  # noqa: S603
            ["cmd.exe", "/c", str(helper), str(pid), str(exe)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )
    except OSError as exc:
        raise PathSetupError(f"failed to schedule update install: {exc}") from exc


def _path_is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def _onefile_cache_dirs() -> list[Path]:
    return [onefile_cache_dir(), legacy_onefile_cache_dir()]


def _running_from_onefile_cache() -> bool:
    """True when this process's payload (or argv0) lives under a onefile cache tree."""
    candidates: list[Path] = []
    root = frozen_app_root()
    if root is not None:
        candidates.append(root)
    with contextlib.suppress(IndexError, OSError):
        candidates.append(Path(sys.argv[0]).resolve().parent)
    for cache_dir in _onefile_cache_dirs():
        if not cache_dir.exists():
            continue
        if any(_path_is_under(path, cache_dir) for path in candidates):
            return True
    return False


def _write_deferred_cache_cleanup_helper(path: Path) -> None:
    """Write a cmd script that waits for a PID, then deletes cache directories."""
    path.write_text(
        "\r\n".join(
            [
                "@echo off",
                "setlocal EnableExtensions",
                'set "PID=%~1"',
                ":waitloop",
                'tasklist /FI "PID eq %PID%" 2>NUL | findstr /I "%PID%" >NUL',
                "if not errorlevel 1 (",
                "  ping -n 2 127.0.0.1 >NUL",
                "  goto waitloop",
                ")",
                'if not "%~2"=="" if exist "%~2" rmdir /s /q "%~2"',
                'if not "%~3"=="" if exist "%~3" rmdir /s /q "%~3"',
                "exit /b 0",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _spawn_deferred_cache_cleanup(helper: Path, pid: int, *dirs: Path) -> None:
    """Start deferred onefile-cache cleanup detached from this process."""
    creationflags = 0
    if hasattr(subprocess, "DETACHED_PROCESS"):
        creationflags |= subprocess.DETACHED_PROCESS
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags |= subprocess.CREATE_NO_WINDOW

    args = ["cmd.exe", "/c", str(helper), str(pid), *(str(d) for d in dirs)]
    try:
        subprocess.Popen(  # noqa: S603
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )
    except OSError as exc:
        raise PathSetupError(f"failed to schedule onefile cache cleanup: {exc}") from exc


def _cleanup_onefile_caches() -> dict[str, bool]:
    """Remove onefile extract caches (current + legacy layout).

    When this process is still running from a cache extract (portable onefile
    ``setup install``), deletion is deferred until after exit.
    """
    targets = [d for d in _onefile_cache_dirs() if d.exists()]
    if not targets:
        return {"cleaned": False, "scheduled": False}

    if is_frozen() and _running_from_onefile_cache():
        staging = update_staging_dir()
        staging.mkdir(parents=True, exist_ok=True)
        helper = staging / CLEAR_ONEFILE_CACHE_HELPER_NAME
        _write_deferred_cache_cleanup_helper(helper)
        _spawn_deferred_cache_cleanup(helper, os.getpid(), *targets)
        return {"cleaned": False, "scheduled": True}

    cleaned = False
    for directory in targets:
        if _delete_install_tree(directory):
            cleaned = True
    _try_remove_empty_install_root()
    return {"cleaned": cleaned, "scheduled": False}


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


def _install_frozen_app(target_dir: Path) -> str:
    if _nuitka_compiled() is not None:
        root = frozen_app_root()
        if root is None:
            raise PathSetupError(
                "Nuitka build has no runnable payload directory; cannot install."
            )
        _install_nuitka_tree(root, target_dir)
        # Onefile extracts use fabric-tools.dll; standalone trees include the exe.
        return "onefile" if not (root / EXE_NAME).is_file() else "standalone"

    onedir_root = frozen_onedir_root()
    if onedir_root is not None:
        _install_frozen_tree(onedir_root, target_dir)
        return "onedir"

    meipass = meipass_dir()
    if meipass is not None:
        _install_from_onefile_meipass(meipass, target_dir)
        return "onefile"

    raise PathSetupError(
        "Frozen executable has neither a Nuitka payload directory, a sibling "
        "_internal folder, nor a PyInstaller _MEIPASS extract dir; cannot install."
    )


def _install_nuitka_tree(source_root: Path, target_dir: Path) -> None:
    """Install a Nuitka standalone tree or onefile bootstrap into ``target_dir``.

    Onefile extracts ship ``fabric-tools.dll`` (not ``fabric-tools.exe``). In that
    case we install the running onefile bootstrap; the payload is unpacked on first
    run into ``%LOCALAPPDATA%\\fabric-tools\\cache\\{VERSION}``.
    """
    source_root = source_root.resolve()
    target_dir = target_dir.resolve()
    source_exe = source_root / EXE_NAME
    has_exe = source_exe.is_file()
    has_runtime = _has_nuitka_runtime_siblings(source_root)
    if not has_exe and not has_runtime:
        raise PathSetupError(
            f"Incomplete Nuitka layout at {source_root} "
            f"(need {EXE_NAME} or runtime DLLs such as python3*.dll / _ctypes.pyd)."
        )

    if source_root == target_dir:
        return

    target_dir.mkdir(parents=True, exist_ok=True)
    _clear_directory_contents(target_dir)

    if has_exe:
        for item in source_root.iterdir():
            dest = target_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
    else:
        bootstrap = Path(sys.argv[0]).resolve()
        if not bootstrap.is_file():
            raise PathSetupError(
                "Cannot locate the Nuitka onefile bootstrap executable to install."
            )
        shutil.copy2(bootstrap, target_dir / EXE_NAME)

    if not (target_dir / EXE_NAME).is_file():
        raise PathSetupError(
            f"Nuitka install failed: missing {EXE_NAME} in {target_dir}"
        )


def _install_frozen_tree(source_root: Path, target_dir: Path) -> None:
    """Copy a PyInstaller onedir tree (exe + _internal) into the install directory."""
    source_root = source_root.resolve()
    target_dir = target_dir.resolve()
    if source_root == target_dir:
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


def _install_from_onefile_meipass(meipass: Path, target_dir: Path) -> None:
    """Unpack a running PyInstaller onefile build into an onedir install tree."""
    bootloader = meipass / ONEDIR_BOOTLOADER_DIR / EXE_NAME
    if not bootloader.is_file():
        raise PathSetupError(
            "This one-file build is missing the embedded onedir bootloader "
            f"({ONEDIR_BOOTLOADER_DIR}\\{EXE_NAME}). Rebuild with scripts\\build_exe.ps1."
        )

    target_dir = target_dir.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    dest_internal = target_dir / INTERNAL_DIR_NAME
    if dest_internal.exists():
        shutil.rmtree(dest_internal)
    dest_internal.mkdir(parents=True)

    for item in meipass.iterdir():
        if item.name == ONEDIR_BOOTLOADER_DIR:
            continue
        dest = dest_internal / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)

    shutil.copy2(bootloader, target_dir / EXE_NAME)


def _runtime_present(target_dir: Path) -> bool:
    """True when an installed frozen runtime looks complete enough to run."""
    if not installed_exe_path(target_dir).is_file():
        return False
    if (target_dir / INTERNAL_DIR_NAME).is_dir():
        return True
    # Nuitka standalone: exe plus sibling native modules / DLLs.
    try:
        return any(
            child.is_file()
            and child.name.lower() != EXE_NAME.lower()
            and child.suffix.lower() in {".dll", ".pyd", ".so"}
            for child in target_dir.iterdir()
        )
    except OSError:
        return False


def _clear_directory_contents(directory: Path) -> list[str]:
    deleted: list[str] = []
    if not directory.exists():
        return deleted
    for child in directory.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
        deleted.append(str(child))
    return deleted


def _remove_frozen_tree(target_dir: Path) -> None:
    """Remove frozen install artifacts, keeping a python ``.cmd`` shim if present."""
    if not target_dir.exists():
        return
    keep = installed_cmd_path(target_dir).resolve()
    for child in list(target_dir.iterdir()):
        if child.resolve() == keep:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _delete_install_tree(target_dir: Path) -> list[str]:
    deleted: list[str] = []
    if not target_dir.exists():
        return deleted
    deleted.extend(_clear_directory_contents(target_dir))
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
    return any(
        _normalize_dir(part) == normalized for part in _split_path(_read_user_path())
    )


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
    return os.path.normcase(
        os.path.normpath(os.path.expandvars(value.strip().rstrip("\\/")))
    )

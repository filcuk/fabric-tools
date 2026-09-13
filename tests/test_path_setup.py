"""Tests for PATH helper parsing and install helpers (no registry writes)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from fabric_tools.path_setup import (
    APPLY_UPDATE_HELPER_NAME,
    CLEAR_ONEFILE_CACHE_HELPER_NAME,
    EXE_NAME,
    INTERNAL_DIR_NAME,
    ONEDIR_BOOTLOADER_DIR,
    PathSetupError,
    _cleanup_onefile_caches,
    _has_nuitka_runtime_siblings,
    _install_from_onefile_meipass,
    _install_frozen_tree,
    _install_nuitka_tree,
    _join_path,
    _normalize_dir,
    _runtime_present,
    _split_path,
    _write_deferred_cache_cleanup_helper,
    _write_deferred_install_helper,
    ensure_user_path_contains,
    format_nuitka_orphan_exe_error,
    frozen_app_root,
    is_frozen,
    is_portable_onefile,
    legacy_onefile_cache_dir,
    onefile_cache_dir,
    path_status,
    perform_setup_update,
)
from fabric_tools.update_check import UpdateCheckResult


def test_split_join_path() -> None:
    value = r"C:\a;C:\b\;C:\c"
    parts = _split_path(value)
    assert parts == [r"C:\a", r"C:\b\\", r"C:\c"] or parts[0].endswith("a")
    assert _join_path(["C:\\a", "C:\\b"]) == "C:\\a;C:\\b"


def test_normalize_dir() -> None:
    left = _normalize_dir("C:\\Foo\\Bar\\")
    right = _normalize_dir("C:\\Foo\\Bar")
    assert left == right


def test_ensure_user_path_contains_prepends_and_moves_to_front(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"path": r"C:\Python\Scripts;C:\Windows"}

    monkeypatch.setattr(
        "fabric_tools.path_setup._read_user_path",
        lambda: state["path"],
    )
    monkeypatch.setattr(
        "fabric_tools.path_setup._write_user_path",
        lambda value: state.__setitem__("path", value),
    )
    monkeypatch.setattr(
        "fabric_tools.path_setup._broadcast_env_change",
        lambda: None,
    )

    install = r"C:\Users\me\AppData\Local\fabric-tools\app"
    assert ensure_user_path_contains(install) is True
    assert state["path"].startswith(install + ";")
    assert r"C:\Python\Scripts" in state["path"]

    assert ensure_user_path_contains(install) is False
    assert state["path"].startswith(install + ";")

    # Present but not first → move to front.
    state["path"] = rf"C:\Python\Scripts;{install};C:\Windows"
    assert ensure_user_path_contains(install) is True
    assert state["path"] == rf"{install};C:\Python\Scripts;C:\Windows"


def test_install_frozen_tree_copies_exe_and_internal(tmp_path: Path) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    source.mkdir()
    (source / EXE_NAME).write_bytes(b"exe")
    internal = source / INTERNAL_DIR_NAME
    internal.mkdir()
    (internal / "payload.dll").write_bytes(b"dll")

    _install_frozen_tree(source, dest)

    assert (dest / EXE_NAME).read_bytes() == b"exe"
    assert (dest / INTERNAL_DIR_NAME / "payload.dll").read_bytes() == b"dll"


def test_install_frozen_tree_replaces_existing_internal(tmp_path: Path) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    source.mkdir()
    dest.mkdir()
    (source / EXE_NAME).write_bytes(b"new")
    (source / INTERNAL_DIR_NAME).mkdir()
    (source / INTERNAL_DIR_NAME / "new.dll").write_bytes(b"1")
    (dest / EXE_NAME).write_bytes(b"old")
    (dest / INTERNAL_DIR_NAME).mkdir()
    (dest / INTERNAL_DIR_NAME / "old.dll").write_bytes(b"0")

    _install_frozen_tree(source, dest)

    assert (dest / EXE_NAME).read_bytes() == b"new"
    assert (dest / INTERNAL_DIR_NAME / "new.dll").is_file()
    assert not (dest / INTERNAL_DIR_NAME / "old.dll").exists()


def test_install_frozen_tree_same_path_is_noop(tmp_path: Path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    (root / EXE_NAME).write_bytes(b"exe")
    (root / INTERNAL_DIR_NAME).mkdir()
    _install_frozen_tree(root, root)
    assert (root / EXE_NAME).is_file()


def test_install_frozen_tree_rejects_incomplete_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    source.mkdir()
    (source / EXE_NAME).write_bytes(b"exe")
    with pytest.raises(PathSetupError, match="Incomplete one-dir"):
        _install_frozen_tree(source, dest)


def test_install_from_onefile_meipass(tmp_path: Path) -> None:
    meipass = tmp_path / "meipass"
    dest = tmp_path / "app"
    meipass.mkdir()
    (meipass / "payload.dll").write_bytes(b"dll")
    (meipass / "base_library.zip").write_bytes(b"zip")
    boot_dir = meipass / ONEDIR_BOOTLOADER_DIR
    boot_dir.mkdir()
    (boot_dir / EXE_NAME).write_bytes(b"boot")

    _install_from_onefile_meipass(meipass, dest)

    assert (dest / EXE_NAME).read_bytes() == b"boot"
    assert (dest / INTERNAL_DIR_NAME / "payload.dll").read_bytes() == b"dll"
    assert (dest / INTERNAL_DIR_NAME / "base_library.zip").read_bytes() == b"zip"
    assert not (dest / INTERNAL_DIR_NAME / ONEDIR_BOOTLOADER_DIR).exists()


def test_install_from_onefile_requires_bootloader(tmp_path: Path) -> None:
    meipass = tmp_path / "meipass"
    meipass.mkdir()
    (meipass / "payload.dll").write_bytes(b"dll")
    with pytest.raises(PathSetupError, match="embedded onedir bootloader"):
        _install_from_onefile_meipass(meipass, tmp_path / "app")


def test_install_nuitka_tree_onefile_payload_copies_bootstrap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    extract = tmp_path / "onefile_extract"
    bootstrap_dir = tmp_path / "download"
    dest = tmp_path / "app"
    extract.mkdir()
    bootstrap_dir.mkdir()
    (extract / "fabric-tools.dll").write_bytes(b"payload")
    (extract / "python312.dll").write_bytes(b"dll")
    (extract / "_ctypes.pyd").write_bytes(b"pyd")
    bootstrap = bootstrap_dir / EXE_NAME
    bootstrap.write_bytes(b"bootstrap")
    monkeypatch.setattr("sys.argv", [str(bootstrap)])

    _install_nuitka_tree(extract, dest)

    assert (dest / EXE_NAME).read_bytes() == b"bootstrap"
    assert list(dest.iterdir()) == [dest / EXE_NAME]

    source = tmp_path / "fabric-tools.dist"
    dest = tmp_path / "app"
    source.mkdir()
    (source / EXE_NAME).write_bytes(b"exe")
    (source / "python311.dll").write_bytes(b"dll")
    (source / "helper.pyd").write_bytes(b"pyd")
    nested = source / "certifi"
    nested.mkdir()
    (nested / "cacert.pem").write_text("pem", encoding="utf-8")

    _install_nuitka_tree(source, dest)

    assert (dest / EXE_NAME).read_bytes() == b"exe"
    assert (dest / "python311.dll").read_bytes() == b"dll"
    assert (dest / "helper.pyd").read_bytes() == b"pyd"
    assert (dest / "certifi" / "cacert.pem").read_text(encoding="utf-8") == "pem"


def test_install_nuitka_tree_replaces_previous_contents(tmp_path: Path) -> None:
    source = tmp_path / "fabric-tools.dist"
    dest = tmp_path / "app"
    source.mkdir()
    dest.mkdir()
    (source / EXE_NAME).write_bytes(b"new")
    (source / "new.dll").write_bytes(b"1")
    (dest / EXE_NAME).write_bytes(b"old")
    (dest / "old.dll").write_bytes(b"0")
    (dest / INTERNAL_DIR_NAME).mkdir()
    (dest / INTERNAL_DIR_NAME / "stale").write_bytes(b"x")

    _install_nuitka_tree(source, dest)

    assert (dest / EXE_NAME).read_bytes() == b"new"
    assert (dest / "new.dll").is_file()
    assert not (dest / "old.dll").exists()
    assert not (dest / INTERNAL_DIR_NAME).exists()


def test_install_nuitka_tree_same_path_is_noop(tmp_path: Path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    (root / EXE_NAME).write_bytes(b"exe")
    (root / "runtime.dll").write_bytes(b"dll")
    _install_nuitka_tree(root, root)
    assert (root / EXE_NAME).read_bytes() == b"exe"
    assert (root / "runtime.dll").is_file()


def test_install_nuitka_tree_rejects_missing_exe(tmp_path: Path) -> None:
    source = tmp_path / "fabric-tools.dist"
    source.mkdir()
    (source / "runtime.dll").write_bytes(b"dll")
    with pytest.raises(PathSetupError, match="Incomplete Nuitka"):
        _install_nuitka_tree(source, tmp_path / "app")


def test_runtime_present_pyinstaller_and_nuitka(tmp_path: Path) -> None:
    pyi = tmp_path / "pyi"
    pyi.mkdir()
    (pyi / EXE_NAME).write_bytes(b"exe")
    (pyi / INTERNAL_DIR_NAME).mkdir()
    assert _runtime_present(pyi) is True

    nuitka = tmp_path / "nuitka"
    nuitka.mkdir()
    (nuitka / EXE_NAME).write_bytes(b"exe")
    (nuitka / "python311.dll").write_bytes(b"dll")
    assert _runtime_present(nuitka) is True

    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / EXE_NAME).write_bytes(b"exe")
    assert _runtime_present(bare) is False


def test_path_status_reports_runtime_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fabric_tools.update_check import compact_windows_version

    pe_version = "1.2.3.0"
    expected = compact_windows_version(pe_version)
    app = tmp_path / "app"
    app.mkdir()
    (app / EXE_NAME).write_bytes(b"exe")
    (app / "python311.dll").write_bytes(b"dll")
    monkeypatch.setattr(
        "fabric_tools.path_setup._user_path_contains",
        lambda _directory: False,
    )
    monkeypatch.setattr("fabric_tools.path_setup.shutil.which", lambda _name: None)
    monkeypatch.setattr(
        "fabric_tools.path_setup._onefile_cache_present",
        lambda: False,
    )
    monkeypatch.setattr(
        "fabric_tools.path_setup.read_exe_product_version",
        lambda _path: pe_version,
    )
    status = path_status(install_dir=app)
    assert status["exe_present"] is True
    assert status["internal_present"] is False
    assert status["runtime_present"] is True
    assert status["install_state"] == "installed"
    assert status["cache_present"] is False
    assert status["installed_version"] == expected
    assert status["version"] == expected
    assert status["running_version"]


def test_resolve_status_version_prefers_pe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fabric_tools.path_setup import resolve_status_version
    from fabric_tools.update_check import compact_windows_version

    pe_version = "1.2.3.0"
    running = "9.9.9"
    expected = compact_windows_version(pe_version)
    exe = tmp_path / EXE_NAME
    exe.write_bytes(b"exe")
    monkeypatch.setattr(
        "fabric_tools.path_setup.read_exe_product_version",
        lambda _path: pe_version,
    )
    display, installed = resolve_status_version(
        exe_path=exe, exe_present=True, running_version=running
    )
    assert display == expected
    assert installed == expected


def test_resolve_status_version_falls_back_to_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fabric_tools.path_setup import resolve_status_version

    running = "9.9.9"
    exe = tmp_path / EXE_NAME
    monkeypatch.setattr(
        "fabric_tools.path_setup.read_exe_product_version",
        lambda _path: None,
    )
    display, installed = resolve_status_version(
        exe_path=exe, exe_present=True, running_version=running
    )
    assert display == running
    assert installed == ""


def test_resolve_status_version_rejects_corrupt_pe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fabric_tools.path_setup import resolve_status_version

    running = "9.9.9"
    corrupt = "1.2.3.00FileV"
    exe = tmp_path / EXE_NAME
    monkeypatch.setattr(
        "fabric_tools.path_setup.read_exe_product_version",
        lambda _path: corrupt,
    )
    display, installed = resolve_status_version(
        exe_path=exe, exe_present=True, running_version=running
    )
    assert display == running
    assert installed == ""


def test_read_exe_product_version_missing_file(tmp_path: Path) -> None:
    from fabric_tools.path_setup import read_exe_product_version

    assert read_exe_product_version(tmp_path / "missing.exe") is None


def test_install_state_incomplete_and_not_installed() -> None:
    from fabric_tools.path_setup import _install_state

    assert (
        _install_state(
            exe_present=True,
            cmd_present=False,
            runtime_present=False,
            internal_present=False,
        )
        == "incomplete"
    )
    assert (
        _install_state(
            exe_present=False,
            cmd_present=False,
            runtime_present=False,
            internal_present=False,
        )
        == "not installed"
    )
    assert (
        _install_state(
            exe_present=False,
            cmd_present=True,
            runtime_present=False,
            internal_present=False,
        )
        == "installed"
    )


def test_write_deferred_install_helper(tmp_path: Path) -> None:
    helper = tmp_path / APPLY_UPDATE_HELPER_NAME
    _write_deferred_install_helper(helper)
    text = helper.read_text(encoding="utf-8")
    assert "Get-Process" in text
    assert "setup install" in text
    assert "findstr" not in text
    assert helper.suffix == ".ps1"


def test_write_deferred_cache_cleanup_helper(tmp_path: Path) -> None:
    helper = tmp_path / CLEAR_ONEFILE_CACHE_HELPER_NAME
    _write_deferred_cache_cleanup_helper(helper)
    text = helper.read_text(encoding="utf-8")
    assert "Get-Process" in text
    assert "Remove-Item" in text
    assert "findstr" not in text
    assert helper.suffix == ".ps1"


def test_hidden_process_creationflags_avoids_detached() -> None:
    from fabric_tools.path_setup import _hidden_process_creationflags

    flags = _hidden_process_creationflags()
    assert flags & subprocess.CREATE_NO_WINDOW
    assert not (flags & subprocess.DETACHED_PROCESS)


def test_cleanup_onefile_caches_removes_current_and_legacy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "fabric-tools"
    cache = root / "cache" / "0.3.0.0"
    legacy = root / "fabric-tools" / "0.3.0.0"
    cache.mkdir(parents=True)
    legacy.mkdir(parents=True)
    (cache / "python312.dll").write_bytes(b"dll")
    (legacy / "python312.dll").write_bytes(b"dll")

    monkeypatch.setattr("fabric_tools.path_setup.install_root", lambda: root)
    monkeypatch.setattr("fabric_tools.path_setup.is_frozen", lambda: False)

    result = _cleanup_onefile_caches()
    assert result == {"cleaned": True, "scheduled": False}
    assert not onefile_cache_dir().exists()
    assert not legacy_onefile_cache_dir().exists()


def test_cleanup_onefile_caches_defers_when_running_from_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "fabric-tools"
    cache = root / "cache" / "0.3.0.0"
    cache.mkdir(parents=True)
    (cache / "python312.dll").write_bytes(b"dll")
    (cache / "_ctypes.pyd").write_bytes(b"pyd")

    spawned: list[tuple] = []

    monkeypatch.setattr("fabric_tools.path_setup.install_root", lambda: root)
    monkeypatch.setattr("fabric_tools.path_setup.is_frozen", lambda: True)
    monkeypatch.setattr(
        "fabric_tools.path_setup.frozen_app_root",
        lambda: cache,
    )
    monkeypatch.setattr(
        "fabric_tools.path_setup._spawn_deferred_cache_cleanup",
        lambda helper, pid, *dirs: spawned.append((helper, pid, dirs)),
    )

    result = _cleanup_onefile_caches()
    assert result == {"cleaned": False, "scheduled": True}
    assert cache.exists()
    assert len(spawned) == 1
    helper, _pid, dirs = spawned[0]
    assert helper.name == CLEAR_ONEFILE_CACHE_HELPER_NAME
    assert onefile_cache_dir() in dirs


def test_is_frozen_detects_nuitka_compiled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.frozen",
        False,
        raising=False,
    )
    monkeypatch.setattr(
        "fabric_tools.path_setup._nuitka_compiled",
        lambda: SimpleNamespace(containing_dir=r"C:\extract"),
    )
    assert is_frozen() is True


def test_frozen_app_root_prefers_nuitka(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    extract = tmp_path / "extract"
    extract.mkdir()
    (extract / EXE_NAME).write_bytes(b"exe")
    (extract / "python312.dll").write_bytes(b"dll")
    monkeypatch.setattr(
        "fabric_tools.path_setup._nuitka_compiled",
        lambda: SimpleNamespace(containing_dir=str(extract)),
    )
    monkeypatch.setattr(
        "fabric_tools.path_setup.frozen_onedir_root",
        lambda: tmp_path / "pyi-app",
    )
    monkeypatch.setattr("sys.argv", [str(extract / EXE_NAME)])
    assert frozen_app_root() == extract.resolve()


def test_frozen_app_root_prefers_argv0_dist_over_output_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Nuitka may set containing_dir to --output-dir; payload lives in *.dist."""
    output_dir = tmp_path / "nuitka"
    dist = output_dir / "fabric-tools.dist"
    output_dir.mkdir()
    dist.mkdir()
    (dist / EXE_NAME).write_bytes(b"exe")
    (dist / "python312.dll").write_bytes(b"dll")
    monkeypatch.setattr(
        "fabric_tools.path_setup._nuitka_compiled",
        lambda: SimpleNamespace(containing_dir=str(output_dir)),
    )
    monkeypatch.setattr("sys.argv", [str(dist / EXE_NAME)])
    assert frozen_app_root() == dist.resolve()


def test_is_portable_onefile_false_when_not_frozen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("fabric_tools.path_setup.is_frozen", lambda: False)
    assert is_portable_onefile() is False


def test_is_portable_onefile_true_for_pyinstaller_onefile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("fabric_tools.path_setup.is_frozen", lambda: True)
    monkeypatch.setattr("fabric_tools.path_setup._nuitka_compiled", lambda: None)
    monkeypatch.setattr(
        "fabric_tools.path_setup.meipass_dir", lambda: tmp_path / "_MEI123"
    )
    monkeypatch.setattr("fabric_tools.path_setup.frozen_onedir_root", lambda: None)
    assert is_portable_onefile() is True


def test_is_portable_onefile_false_for_pyinstaller_onedir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("fabric_tools.path_setup.is_frozen", lambda: True)
    monkeypatch.setattr("fabric_tools.path_setup._nuitka_compiled", lambda: None)
    monkeypatch.setattr(
        "fabric_tools.path_setup.meipass_dir", lambda: tmp_path / "_internal"
    )
    monkeypatch.setattr(
        "fabric_tools.path_setup.frozen_onedir_root", lambda: tmp_path / "app"
    )
    assert is_portable_onefile() is False


def test_is_portable_onefile_true_for_nuitka_onefile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    extract = tmp_path / "onefile_extract"
    portable = tmp_path / "download"
    extract.mkdir()
    portable.mkdir()
    (extract / "python312.dll").write_bytes(b"dll")
    (extract / "_ctypes.pyd").write_bytes(b"pyd")
    (extract / "nuitka_entry.py").write_text("# entry\n", encoding="utf-8")
    monkeypatch.setattr("fabric_tools.path_setup.is_frozen", lambda: True)
    monkeypatch.setattr(
        "fabric_tools.path_setup._nuitka_compiled",
        lambda: SimpleNamespace(containing_dir=str(tmp_path / "wrong-output-dir")),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "__main__",
        SimpleNamespace(__file__=str(extract / "nuitka_entry.py")),
    )
    monkeypatch.setattr(
        "sys.argv",
        [str(portable / EXE_NAME), "-h"],
    )
    assert frozen_app_root() == extract.resolve()
    assert is_portable_onefile() is True
    assert format_nuitka_orphan_exe_error() is None


def test_is_portable_onefile_false_for_nuitka_standalone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = tmp_path / "fabric-tools.dist"
    app.mkdir()
    (app / "python312.dll").write_bytes(b"dll")
    (app / EXE_NAME).write_bytes(b"exe")
    monkeypatch.setattr("fabric_tools.path_setup.is_frozen", lambda: True)
    monkeypatch.setattr(
        "fabric_tools.path_setup._nuitka_compiled",
        lambda: SimpleNamespace(containing_dir=str(app)),
    )
    monkeypatch.setattr(
        "sys.argv",
        [str(app / EXE_NAME), "-h"],
    )
    assert is_portable_onefile() is False


def test_format_nuitka_orphan_exe_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    orphan_dir = tmp_path / "orphan"
    orphan_dir.mkdir()
    (orphan_dir / EXE_NAME).write_bytes(b"exe")
    monkeypatch.setattr(
        "fabric_tools.path_setup._nuitka_compiled",
        lambda: SimpleNamespace(containing_dir=str(orphan_dir)),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "__main__",
        SimpleNamespace(__file__=str(orphan_dir / "nuitka_entry.py")),
    )
    monkeypatch.setattr("sys.argv", [str(orphan_dir / EXE_NAME)])
    err = format_nuitka_orphan_exe_error()
    assert err is not None
    assert "onefile" in err.lower() or "missing sibling" in err.lower()


def test_format_nuitka_orphan_exe_error_none_when_siblings_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = tmp_path / "fabric-tools.dist"
    app.mkdir()
    (app / EXE_NAME).write_bytes(b"exe")
    (app / "python312.dll").write_bytes(b"dll")
    monkeypatch.setattr(
        "fabric_tools.path_setup._nuitka_compiled",
        lambda: SimpleNamespace(containing_dir=str(app)),
    )
    monkeypatch.setattr("sys.argv", [str(app / EXE_NAME)])
    assert format_nuitka_orphan_exe_error() is None
    assert _has_nuitka_runtime_siblings(app) is True


def test_perform_setup_update_downloads_and_schedules_when_not_frozen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("fabric_tools.path_setup.os.name", "nt")
    monkeypatch.setattr("fabric_tools.path_setup.is_frozen", lambda: False)
    monkeypatch.setattr(
        "fabric_tools.path_setup.install_root",
        lambda: tmp_path / "fabric-tools",
    )
    monkeypatch.setattr(
        "fabric_tools.update_check.check_for_update",
        lambda: UpdateCheckResult(
            current="0.2.0",
            latest="0.3.0",
            update_available=True,
            release_url="https://example/release",
            tag_name="v0.3.0",
            asset_url="https://example/fabric-tools.exe",
        ),
    )
    monkeypatch.setattr(
        "fabric_tools.update_check.save_update_cache",
        lambda *args, **kwargs: None,
    )

    def fake_download(url: str, destination: Path, **kwargs: object) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"exe")
        return destination

    monkeypatch.setattr(
        "fabric_tools.update_check.download_release_asset",
        fake_download,
    )
    spawned: list[tuple[Path, int, Path]] = []

    def fake_spawn(helper: Path, pid: int, exe: Path) -> None:
        spawned.append((helper, pid, exe))

    monkeypatch.setattr(
        "fabric_tools.path_setup._spawn_deferred_install",
        fake_spawn,
    )

    result = perform_setup_update(silent=True)
    assert result["scheduled"] is True
    assert Path(str(result["exe_path"])).is_file()
    assert len(spawned) == 1


def test_perform_setup_update_up_to_date(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("fabric_tools.path_setup.os.name", "nt")
    monkeypatch.setattr("fabric_tools.path_setup.is_frozen", lambda: True)
    monkeypatch.setattr(
        "fabric_tools.update_check.check_for_update",
        lambda: UpdateCheckResult(
            current="0.2.0",
            latest="0.2.0",
            update_available=False,
            release_url=None,
            tag_name="v0.2.0",
        ),
    )
    monkeypatch.setattr(
        "fabric_tools.update_check.save_update_cache",
        lambda *args, **kwargs: None,
    )
    result = perform_setup_update(silent=True)
    assert result["up_to_date"] is True
    assert result["current"] == "0.2.0"


def test_perform_setup_update_missing_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fabric_tools.path_setup.os.name", "nt")
    monkeypatch.setattr("fabric_tools.path_setup.is_frozen", lambda: True)
    monkeypatch.setattr(
        "fabric_tools.update_check.check_for_update",
        lambda: UpdateCheckResult(
            current="0.2.0",
            latest="0.3.0",
            update_available=True,
            release_url="https://example/release",
            tag_name="v0.3.0",
            asset_url=None,
        ),
    )
    monkeypatch.setattr(
        "fabric_tools.update_check.save_update_cache",
        lambda *args, **kwargs: None,
    )
    with pytest.raises(PathSetupError, match="no fabric-tools.exe"):
        perform_setup_update(silent=True)


def test_perform_setup_update_downloads_and_schedules(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("fabric_tools.path_setup.os.name", "nt")
    monkeypatch.setattr("fabric_tools.path_setup.is_frozen", lambda: True)
    monkeypatch.setattr(
        "fabric_tools.path_setup.install_root",
        lambda: tmp_path / "fabric-tools",
    )
    monkeypatch.setattr(
        "fabric_tools.update_check.check_for_update",
        lambda: UpdateCheckResult(
            current="0.2.0",
            latest="0.3.0",
            update_available=True,
            release_url="https://example/release",
            tag_name="v0.3.0",
            asset_url="https://example/fabric-tools.exe",
        ),
    )
    monkeypatch.setattr(
        "fabric_tools.update_check.save_update_cache",
        lambda *args, **kwargs: None,
    )

    def fake_download(url: str, destination: Path, **kwargs: object) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"exe")
        return destination

    monkeypatch.setattr(
        "fabric_tools.update_check.download_release_asset",
        fake_download,
    )
    spawned: list[tuple[Path, int, Path]] = []

    def fake_spawn(helper: Path, pid: int, exe: Path) -> None:
        spawned.append((helper, pid, exe))

    monkeypatch.setattr(
        "fabric_tools.path_setup._spawn_deferred_install",
        fake_spawn,
    )

    result = perform_setup_update(silent=True)
    assert result["scheduled"] is True
    assert result["up_to_date"] is False
    exe_path = Path(str(result["exe_path"]))
    assert exe_path.is_file()
    assert exe_path.read_bytes() == b"exe"
    assert len(spawned) == 1
    helper, _pid, exe = spawned[0]
    assert helper.name == APPLY_UPDATE_HELPER_NAME
    assert helper.is_file()
    assert exe == exe_path

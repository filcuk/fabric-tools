"""Tests for PATH helper parsing and install helpers (no registry writes)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from fabric_tools.path_setup import (
    APPLY_UPDATE_HELPER_NAME,
    EXE_NAME,
    INTERNAL_DIR_NAME,
    ONEDIR_BOOTLOADER_DIR,
    PathSetupError,
    _has_nuitka_runtime_siblings,
    _install_from_onefile_meipass,
    _install_frozen_tree,
    _install_nuitka_tree,
    _join_path,
    _normalize_dir,
    _runtime_present,
    _split_path,
    _write_deferred_install_helper,
    format_install_speed_notice,
    format_nuitka_orphan_exe_error,
    frozen_app_root,
    is_frozen,
    is_portable_onefile,
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


def test_install_nuitka_tree_copies_full_dist(tmp_path: Path) -> None:
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
    app = tmp_path / "app"
    app.mkdir()
    (app / EXE_NAME).write_bytes(b"exe")
    (app / "python311.dll").write_bytes(b"dll")
    monkeypatch.setattr(
        "fabric_tools.path_setup._user_path_contains",
        lambda _directory: False,
    )
    monkeypatch.setattr("fabric_tools.path_setup.shutil.which", lambda _name: None)
    status = path_status(install_dir=app)
    assert status["exe_present"] is True
    assert status["internal_present"] is False
    assert status["runtime_present"] is True


def test_write_deferred_install_helper(tmp_path: Path) -> None:
    helper = tmp_path / APPLY_UPDATE_HELPER_NAME
    _write_deferred_install_helper(helper)
    text = helper.read_text(encoding="utf-8")
    assert "tasklist" in text
    assert "setup install" in text


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
    assert format_install_speed_notice() is None


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
    notice = format_install_speed_notice()
    assert notice is not None
    assert "20x" in notice
    assert "setup install" in notice


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
    assert format_install_speed_notice() is None


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
    assert format_install_speed_notice() is not None
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
    assert format_install_speed_notice() is None


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


def test_perform_setup_update_requires_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fabric_tools.path_setup.os.name", "nt")
    monkeypatch.setattr("fabric_tools.path_setup.is_frozen", lambda: False)
    with pytest.raises(PathSetupError, match="Windows .exe"):
        perform_setup_update(silent=True)


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

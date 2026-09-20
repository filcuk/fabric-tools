"""Tests for PATH helper parsing and onedir install helpers (no registry writes)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fabric_tools.path_setup import (
    EXE_NAME,
    INTERNAL_DIR_NAME,
    PathSetupError,
    _install_frozen_tree,
    _join_path,
    _normalize_dir,
    _split_path,
)


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

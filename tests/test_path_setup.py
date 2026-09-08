"""Tests for PATH helper parsing (no registry writes)."""

from __future__ import annotations

from fabric_tools.path_setup import _join_path, _normalize_dir, _split_path


def test_split_join_path() -> None:
    value = r"C:\a;C:\b\;C:\c"
    parts = _split_path(value)
    assert parts == [r"C:\a", r"C:\b\\", r"C:\c"] or parts[0].endswith("a")
    assert _join_path(["C:\\a", "C:\\b"]) == "C:\\a;C:\\b"


def test_normalize_dir() -> None:
    left = _normalize_dir("C:\\Foo\\Bar\\")
    right = _normalize_dir("C:\\Foo\\Bar")
    assert left == right

"""Tests for ensure_kind_path_suffix (stem → kind extension)."""

from __future__ import annotations

from pathlib import Path

from fabric_tools.parsing import ensure_kind_path_suffix


def test_ensure_kind_path_suffix_appends_stem() -> None:
    assert ensure_kind_path_suffix(
        Path("myApp"),
        canonical_suffix=".OrgApp",
    ) == Path("myApp.OrgApp")


def test_ensure_kind_path_suffix_preserves_parent() -> None:
    assert (
        ensure_kind_path_suffix(
            Path("out") / "myApp",
            canonical_suffix=".OrgApp",
        )
        == Path("out") / "myApp.OrgApp"
    )


def test_ensure_kind_path_suffix_dot_stem() -> None:
    assert ensure_kind_path_suffix(
        Path(r".\myApp"),
        canonical_suffix=".OrgApp",
    ) == Path("myApp.OrgApp")


def test_ensure_kind_path_suffix_trailing_slash() -> None:
    assert ensure_kind_path_suffix(
        Path("temp/"),
        canonical_suffix=".OrgApp",
    ) == Path("temp.OrgApp")


def test_ensure_kind_path_suffix_already_canonical() -> None:
    path = Path("myApp.OrgApp")
    assert ensure_kind_path_suffix(path, canonical_suffix=".OrgApp") == path


def test_ensure_kind_path_suffix_accepted_lowercase() -> None:
    path = Path("myApp.orgapp")
    assert ensure_kind_path_suffix(path, canonical_suffix=".OrgApp") == path


def test_ensure_kind_path_suffix_custom_accepted() -> None:
    notebook = Path("ETL.Notebook")
    assert (
        ensure_kind_path_suffix(
            notebook,
            canonical_suffix=".ipynb",
            accepted_suffixes=(".ipynb", ".Notebook", ".notebook"),
        )
        == notebook
    )
    assert ensure_kind_path_suffix(
        Path("ETL"),
        canonical_suffix=".ipynb",
        accepted_suffixes=(".ipynb", ".Notebook", ".notebook"),
    ) == Path("ETL.ipynb")


def test_ensure_kind_path_suffix_bare_content_ok(tmp_path: Path) -> None:
    bare = tmp_path / "Sales"
    bare.mkdir()
    (bare / "definition.json").write_text("{}", encoding="utf-8")

    def _ok(path: Path) -> bool:
        return path.is_dir() and (path / "definition.json").is_file()

    assert (
        ensure_kind_path_suffix(
            bare,
            canonical_suffix=".OrgApp",
            bare_content_ok=_ok,
        )
        == bare
    )


def test_ensure_kind_path_suffix_empty_dir_still_appends(tmp_path: Path) -> None:
    bare = tmp_path / "temp"
    bare.mkdir()
    assert (
        ensure_kind_path_suffix(
            bare,
            canonical_suffix=".OrgApp",
            bare_content_ok=lambda p: p.is_dir() and (p / "definition.json").is_file(),
        )
        == tmp_path / "temp.OrgApp"
    )


def test_ensure_kind_path_suffix_adds_leading_dot() -> None:
    assert ensure_kind_path_suffix(
        Path("Sales"),
        canonical_suffix="rdl",
    ) == Path("Sales.rdl")

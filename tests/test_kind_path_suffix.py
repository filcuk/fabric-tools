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


def test_ensure_notebook_path_appends_ipynb() -> None:
    from fabric_tools.notebook.definition import ensure_notebook_path

    assert ensure_notebook_path(Path("ETL")) == Path("ETL.ipynb")
    assert ensure_notebook_path(Path("ETL.ipynb")) == Path("ETL.ipynb")
    assert ensure_notebook_path(Path("ETL.Notebook")) == Path("ETL.Notebook")


def test_ensure_model_and_rdl_paths() -> None:
    from fabric_tools.dataflow_gen1.definition import ensure_model_path
    from fabric_tools.paginated_report.definition import ensure_rdl_path

    assert ensure_model_path(Path("Orders")) == Path("Orders.json")
    assert ensure_model_path(Path("Orders.json")) == Path("Orders.json")
    assert ensure_rdl_path(Path("Sales")) == Path("Sales.rdl")
    assert ensure_rdl_path(Path("Sales.rdl")) == Path("Sales.rdl")

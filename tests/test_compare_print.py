"""Tests for aligned compare summary printing."""

from __future__ import annotations

from dataclasses import dataclass, field

from fabric_tools.compare_print import (
    compare_row_cells,
    compare_status,
    format_compare_table,
)


@dataclass
class _Result:
    ok: bool
    identical: bool
    header: str = "compare"
    diff_text: str = ""
    error: str | None = None
    messages: list[str] = field(default_factory=list)
    remote_name: str = "-"
    local_name: str = "-"
    target_ref: str = "-"


def test_compare_status_tokens() -> None:
    assert (
        compare_status(_Result(ok=True, identical=True, remote_name="A")) == "identical"
    )
    assert (
        compare_status(_Result(ok=True, identical=False, remote_name="A"))
        == "differences"
    )
    assert (
        compare_status(
            _Result(ok=False, identical=False, error="boom", remote_name="A")
        )
        == "error"
    )
    assert compare_status(_Result(ok=False, identical=False)) == "error"


def test_format_compare_table_alignment() -> None:
    text = format_compare_table(
        [
            _Result(
                ok=True,
                identical=True,
                remote_name="Projects",
                local_name="Projects.Report",
                target_ref="ws:item",
            ),
            _Result(
                ok=True,
                identical=False,
                remote_name="Sales",
                local_name="Sales.Report",
                target_ref="ws:other",
                diff_text="---\n+++",
            ),
        ]
    )
    lines = text.splitlines()
    assert lines[0].startswith("REMOTE")
    assert "LOCAL" in lines[0]
    assert "STATUS" in lines[0]
    assert "TARGET" in lines[0]
    assert "Projects" in lines[1]
    assert "Projects.Report" in lines[1]
    assert "identical" in lines[1]
    assert "ws:item" in lines[1]
    assert "differences" in lines[2]
    assert "  " in lines[1]
    assert "\\" not in text
    assert "/" not in text.splitlines()[1]


def test_compare_row_cells_defaults() -> None:
    assert compare_row_cells(_Result(ok=True, identical=True)) == (
        "-",
        "-",
        "identical",
        "-",
    )

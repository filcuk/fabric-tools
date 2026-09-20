"""Tests for polymorphic --origin/--target parsing and pairing rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from fabric_tools.parsing import (
    CommandMode,
    ParseError,
    build_work_items,
    build_work_items_from_cli,
    parse_file_values,
    parse_origin_values,
    parse_target_values,
    rejoin_spaced_csv_argv,
)

WS = "11111111-1111-1111-1111-111111111111"
A = "22222222-2222-2222-2222-222222222222"
B = "33333333-3333-3333-3333-333333333333"
WS2 = "44444444-4444-4444-4444-444444444444"


def test_parse_targets_comma_and_create() -> None:
    targets = parse_target_values([f"{WS}:{A},{WS}:{B}", WS2])
    assert len(targets) == 3
    assert targets[0].item_id == A
    assert targets[2].is_create


def test_parse_targets_shorthand_inherits_workspace() -> None:
    targets = parse_target_values([f"{WS}:{A},{B}"])
    assert len(targets) == 2
    assert targets[0].workspace_id == WS
    assert targets[0].item_id == A
    assert targets[1].workspace_id == WS
    assert targets[1].item_id == B


def test_parse_targets_form2_separate_flags() -> None:
    targets = parse_target_values([f"{WS}:{A},{B}", f"{WS2}:{A},{B}"])
    assert len(targets) == 4
    assert targets[0].workspace_id == WS
    assert targets[1].workspace_id == WS
    assert targets[2].workspace_id == WS2
    assert targets[3].workspace_id == WS2
    assert [t.item_id for t in targets] == [A, B, A, B]


def test_parse_targets_rejects_multi_workspace_overwrite_in_one_flag() -> None:
    with pytest.raises(ParseError, match="one workspace"):
        parse_target_values([f"{WS}:{A},{WS2}:{B}"])
    with pytest.raises(ParseError, match="one workspace"):
        parse_target_values([f"{WS}:{A},{B},{WS2}:{A}"])


def test_parse_targets_allows_multi_workspace_create_csv() -> None:
    targets = parse_target_values([f"{WS},{WS2}"])
    assert len(targets) == 2
    assert targets[0].is_create and targets[0].workspace_id == WS
    assert targets[1].is_create and targets[1].workspace_id == WS2


def test_parse_targets_allows_spaces_after_commas() -> None:
    targets = parse_target_values([f"{WS}:{A}, {WS}:{B}"])
    assert len(targets) == 2
    assert targets[0].item_id == A
    assert targets[1].item_id == B


def test_parse_origin_shorthand_inherits_workspace() -> None:
    origins = parse_origin_values([f"{WS}:{A},{B}"])
    assert len(origins) == 2
    assert origins[0].workspace_id == WS
    assert origins[1].workspace_id == WS
    assert origins[1].item_id == B


def test_parse_origin_rejects_multi_workspace_in_one_flag() -> None:
    with pytest.raises(ParseError, match="one workspace"):
        parse_origin_values([f"{WS}:{A},{WS2}:{B}"])


def test_rejoin_spaced_csv_argv_for_targets() -> None:
    argv = [
        "notebook",
        "compare",
        "-t",
        f"{WS}:{A},",
        f"{WS}:{B},",
        f"{WS}:{A}",
        "-o",
        "notebook.ipynb",
        "-m",
        "power2-dlm",
    ]
    joined = rejoin_spaced_csv_argv(argv)
    assert joined == [
        "notebook",
        "compare",
        "-t",
        f"{WS}:{A}, {WS}:{B}, {WS}:{A}",
        "-o",
        "notebook.ipynb",
        "-m",
        "power2-dlm",
    ]
    targets = parse_target_values([joined[3]])
    assert len(targets) == 3


def test_rejoin_spaced_csv_argv_leaves_non_csv_alone() -> None:
    argv = ["notebook", "download", "-o", f"{WS}:{A}", "-t", "a.ipynb"]
    assert rejoin_spaced_csv_argv(argv) == argv


def test_rejoin_spaced_csv_argv_for_cells() -> None:
    argv = ["notebook", "deploy", "-c", "1,", "3,", "5", "-t", WS]
    assert rejoin_spaced_csv_argv(argv) == [
        "notebook",
        "deploy",
        "-c",
        "1, 3, 5",
        "-t",
        WS,
    ]


def test_download_cli_origin_remote_optional_target_path() -> None:
    items = build_work_items_from_cli(
        CommandMode.DOWNLOAD,
        origin_values=[f"{WS}:{A},{WS}:{B}"],
        target_values=["one.ipynb"],
        dry_run=False,
    )
    assert len(items) == 2
    assert items[0].file == items[1].file == Path("one.ipynb")
    assert items[0].target is not None
    assert items[0].target.item_id == A


def test_download_cli_rejects_target_remote() -> None:
    with pytest.raises(ParseError, match="local path"):
        build_work_items_from_cli(
            CommandMode.DOWNLOAD,
            origin_values=[f"{WS}:{A}"],
            target_values=[f"{WS}:{B}"],
            dry_run=False,
        )


def test_compare_rejects_broadcast() -> None:
    with pytest.raises(ParseError, match="1:1"):
        build_work_items_from_cli(
            CommandMode.COMPARE,
            origin_values=["one.ipynb"],
            target_values=[f"{WS}:{A},{WS}:{B}"],
            dry_run=False,
        )


def test_compare_accepts_download_shaped_flags() -> None:
    """Same -o remote / -t local layout as download must work for compare."""
    items = build_work_items_from_cli(
        CommandMode.COMPARE,
        origin_values=[f"{WS}:{A}"],
        target_values=["one.ipynb"],
        dry_run=False,
    )
    assert len(items) == 1
    assert items[0].file == Path("one.ipynb")
    assert items[0].origin is None
    assert items[0].target is not None
    assert items[0].target.item_id == A


def test_deploy_accepts_download_shaped_flags() -> None:
    """Same -o remote / -t local layout as download must work for deploy."""
    items = build_work_items_from_cli(
        CommandMode.DEPLOY,
        origin_values=[f"{WS}:{A}"],
        target_values=["one.ipynb"],
        dry_run=False,
    )
    assert len(items) == 1
    assert items[0].file == Path("one.ipynb")
    assert items[0].origin is None
    assert items[0].target is not None
    assert items[0].target.item_id == A


def test_deploy_create_accepts_remote_on_origin_local_on_target() -> None:
    items = build_work_items_from_cli(
        CommandMode.DEPLOY,
        origin_values=[WS],
        target_values=["one.ipynb"],
        dry_run=False,
    )
    assert len(items) == 1
    assert items[0].file == Path("one.ipynb")
    assert items[0].target is not None
    assert items[0].target.is_create
    assert items[0].target.workspace_id == WS


def test_deploy_compare_reject_local_both_sides() -> None:
    with pytest.raises(ParseError, match="both --origin and --target"):
        build_work_items_from_cli(
            CommandMode.COMPARE,
            origin_values=["a.ipynb"],
            target_values=["b.ipynb"],
            dry_run=False,
        )


def test_deploy_remote_origin_requires_artifact() -> None:
    with pytest.raises(ParseError, match="remote --origin requires workspace:artifact"):
        build_work_items_from_cli(
            CommandMode.DEPLOY,
            origin_values=[WS],
            target_values=[f"{WS2}:{B}"],
            dry_run=False,
        )


def test_dry_run_target_path_only() -> None:
    items = build_work_items_from_cli(
        CommandMode.DEPLOY,
        origin_values=None,
        target_values=["a.ipynb"],
        dry_run=True,
    )
    assert len(items) == 1
    assert items[0].target is None
    assert items[0].file == Path("a.ipynb")


def test_download_rejects_multiple_workspaces() -> None:
    with pytest.raises(ParseError, match="one workspace"):
        build_work_items_from_cli(
            CommandMode.DOWNLOAD,
            origin_values=[f"{WS}:{A}", f"{WS2}:{B}"],
            target_values=["a.ipynb", "b.ipynb"],
            dry_run=False,
        )


def test_deploy_rejects_mixed_create_and_overwrite() -> None:
    with pytest.raises(ParseError, match="cannot mix"):
        build_work_items_from_cli(
            CommandMode.DEPLOY,
            origin_values=["a.ipynb", "b.ipynb"],
            target_values=[WS, f"{WS}:{A}"],
            dry_run=False,
        )


def test_dry_run_origin_path_only() -> None:
    items = build_work_items_from_cli(
        CommandMode.DEPLOY,
        origin_values=["a.ipynb"],
        target_values=None,
        dry_run=True,
    )
    assert len(items) == 1
    assert items[0].target is None
    assert items[0].file == Path("a.ipynb")


def test_dry_run_requires_something() -> None:
    with pytest.raises(ParseError, match="at least one"):
        build_work_items_from_cli(
            CommandMode.DEPLOY,
            origin_values=None,
            target_values=None,
            dry_run=True,
        )


def test_invalid_guid() -> None:
    with pytest.raises(ParseError, match="local path"):
        parse_target_values(["not-a-guid"])


def test_malformed_guid_shaped_token_is_path() -> None:
    with pytest.raises(ParseError, match="local path"):
        parse_target_values(["11111111-1111-1111-1111-11111111111g"])


def test_path_not_treated_as_guid() -> None:
    items = build_work_items_from_cli(
        CommandMode.DEPLOY,
        origin_values=["./my-notebook.ipynb"],
        target_values=[WS],
        dry_run=False,
    )
    assert items[0].file == Path("./my-notebook.ipynb")
    assert items[0].target is not None
    assert items[0].target.is_create


def test_parse_origin_requires_artifact() -> None:
    with pytest.raises(ParseError, match="workspace:artifact"):
        parse_origin_values([WS])


def test_deploy_origin_broadcast() -> None:
    items = build_work_items_from_cli(
        CommandMode.DEPLOY,
        origin_values=[f"{WS}:{A}"],
        target_values=[f"{WS}:{A}", f"{WS2}:{B}"],
        dry_run=False,
    )
    assert len(items) == 2
    assert items[0].origin == items[1].origin
    assert items[0].file is None
    assert items[0].target is not None
    assert items[0].target.workspace_id == WS
    assert items[1].target is not None
    assert items[1].target.workspace_id == WS2


def test_compare_origin_requires_one_to_one() -> None:
    with pytest.raises(ParseError, match="1:1"):
        build_work_items_from_cli(
            CommandMode.COMPARE,
            origin_values=[f"{WS}:{A}"],
            target_values=[f"{WS}:{A}", f"{WS2}:{B}"],
            dry_run=False,
        )


def test_rejects_path_and_remote_origin_together() -> None:
    with pytest.raises(ParseError, match="mix"):
        build_work_items_from_cli(
            CommandMode.DEPLOY,
            origin_values=["a.ipynb", f"{WS}:{A}"],
            target_values=[f"{WS}:{A}"],
            dry_run=False,
        )


def test_delete_targets_only() -> None:
    items = build_work_items_from_cli(
        CommandMode.DELETE,
        origin_values=None,
        target_values=[f"{WS}:{A}", f"{WS2}:{B}"],
        dry_run=False,
    )
    assert len(items) == 2
    assert items[0].file is None
    assert items[0].target is not None
    assert items[0].target.item_id == A


def test_delete_rejects_origin() -> None:
    with pytest.raises(ParseError, match="only accepts remote --target"):
        build_work_items_from_cli(
            CommandMode.DELETE,
            origin_values=["a.ipynb"],
            target_values=[f"{WS}:{A}"],
            dry_run=False,
        )


def test_delete_requires_artifact_id() -> None:
    with pytest.raises(ParseError, match="workspace:artifact"):
        build_work_items_from_cli(
            CommandMode.DELETE,
            origin_values=None,
            target_values=[WS],
            dry_run=False,
        )


def test_delete_dry_run_targets() -> None:
    items = build_work_items_from_cli(
        CommandMode.DELETE,
        origin_values=None,
        target_values=[f"{WS}:{A}"],
        dry_run=True,
    )
    assert len(items) == 1
    assert items[0].target is not None


def test_deploy_create_only_rejects_artifact_targets() -> None:
    with pytest.raises(ParseError, match="create only"):
        build_work_items_from_cli(
            CommandMode.DEPLOY,
            origin_values=["model.json"],
            target_values=[f"{WS}:{A}"],
            dry_run=False,
            deploy_create_only=True,
        )


def test_internal_build_work_items_still_pairs() -> None:
    targets = parse_target_values([f"{WS}:{A},{WS}:{B}"])
    files = parse_file_values(["one.ipynb"])
    items = build_work_items(CommandMode.DOWNLOAD, targets, files, dry_run=False)
    assert len(items) == 2
    assert items[0].file == Path("one.ipynb")

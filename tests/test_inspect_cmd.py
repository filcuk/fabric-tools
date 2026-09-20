"""Tests for inspect filters, formatters, and --target shape validation."""

from __future__ import annotations

import pytest

from fabric_tools.inspect_cmd import (
    InspectError,
    apply_filters,
    filter_by_name,
    filter_by_type,
    format_item_detail,
    format_item_table,
    format_workspace_detail,
    format_workspace_table,
    parse_item_get_target,
    parse_item_list_target,
    parse_workspace_get_target,
)

WS = "11111111-1111-1111-1111-111111111111"
ITEM = "22222222-2222-2222-2222-222222222222"


def test_filter_by_name_case_insensitive() -> None:
    rows = [
        {"displayName": "Sales ETL", "type": "Workspace"},
        {"displayName": "Marketing", "type": "Workspace"},
        {"displayName": "sales archive", "type": "Personal"},
    ]
    matched = filter_by_name(rows, "SALES")
    assert [r["displayName"] for r in matched] == ["Sales ETL", "sales archive"]


def test_filter_by_name_empty_returns_copy() -> None:
    rows = [{"displayName": "A"}]
    assert filter_by_name(rows, None) == rows
    assert filter_by_name(rows, "") == rows
    assert filter_by_name(rows, None) is not rows


def test_filter_by_type_exact() -> None:
    rows = [
        {"displayName": "Mine", "type": "Personal"},
        {"displayName": "Team", "type": "Workspace"},
    ]
    assert filter_by_type(rows, "Personal") == [rows[0]]
    assert filter_by_type(rows, "personal") == []


def test_apply_filters_name_then_type() -> None:
    rows = [
        {"displayName": "Dev Notebooks", "type": "Notebook"},
        {"displayName": "Dev Pipeline", "type": "DataPipeline"},
        {"displayName": "Prod Notebooks", "type": "Notebook"},
    ]
    matched = apply_filters(rows, name_filter="dev", type_filter="Notebook")
    assert matched == [rows[0]]


def test_format_workspace_table() -> None:
    table = format_workspace_table(
        [
            {
                "displayName": "Finance",
                "id": WS,
                "type": "Workspace",
                "capacityId": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "domainId": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            }
        ]
    )
    lines = table.splitlines()
    assert lines[0].startswith("NAME")
    assert "ID" in lines[0]
    assert "TYPE" in lines[0]
    assert "CAPACITY" in lines[0]
    assert "DOMAIN" in lines[0]
    assert "Finance" in lines[1]
    assert WS in lines[1]
    assert "Workspace" in lines[1]
    assert "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" in lines[1]
    assert "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb" in lines[1]


def test_format_workspace_table_missing_optional() -> None:
    table = format_workspace_table(
        [{"displayName": "My workspace", "id": WS, "type": "Personal"}]
    )
    body = table.splitlines()[1]
    assert "My workspace" in body
    assert "Personal" in body
    # Trailing capacity and domain placeholders.
    assert body.rstrip().endswith("-")
    cells = body.split()
    assert cells[-2:] == ["-", "-"]


def test_format_item_table_includes_target() -> None:
    table = format_item_table(
        [
            {
                "displayName": "ETL",
                "id": ITEM,
                "type": "Notebook",
                "workspaceId": WS,
            }
        ]
    )
    lines = table.splitlines()
    assert lines[0].startswith("NAME")
    assert "TARGET" in lines[0]
    assert "TYPE" in lines[0]
    assert "ETL" in lines[1]
    assert f"{WS}:{ITEM}" in lines[1]
    assert "Notebook" in lines[1]
    # Item id appears once (inside TARGET), not as a separate column.
    assert lines[1].count(ITEM) == 1


def test_format_tables_align_columns() -> None:
    table = format_item_table(
        [
            {
                "displayName": "A",
                "id": ITEM,
                "type": "Notebook",
                "workspaceId": WS,
            },
            {
                "displayName": "Longer name",
                "id": ITEM,
                "type": "Report",
                "workspaceId": WS,
            },
        ]
    )
    lines = table.splitlines()
    # Invisible columns: same character positions for TARGET start.
    target_col = lines[0].index("TARGET")
    assert lines[1][target_col : target_col + len(f"{WS}:{ITEM}")] == f"{WS}:{ITEM}"
    assert lines[2][target_col : target_col + len(f"{WS}:{ITEM}")] == f"{WS}:{ITEM}"


def test_format_workspace_detail_skips_empty() -> None:
    detail = format_workspace_detail(
        {
            "id": WS,
            "displayName": "Finance",
            "description": "",
            "type": "Workspace",
            "capacityId": None,
        }
    )
    key_w = len("displayName")
    assert detail == (
        f"{'id':>{key_w}}  {WS}\n"
        f"{'displayName':>{key_w}}  Finance\n"
        f"{'type':>{key_w}}  Workspace"
    )


def test_format_item_detail() -> None:
    detail = format_item_detail(
        {
            "id": ITEM,
            "displayName": "ETL",
            "type": "Notebook",
            "workspaceId": WS,
        }
    )
    key_w = len("displayName")
    assert detail == (
        f"{'id':>{key_w}}  {ITEM}\n"
        f"{'displayName':>{key_w}}  ETL\n"
        f"{'type':>{key_w}}  Notebook\n"
        f"{'workspaceId':>{key_w}}  {WS}"
    )


def test_parse_workspace_get_target_ok() -> None:
    target = parse_workspace_get_target(WS)
    assert target.workspace_id == WS
    assert target.item_id is None


def test_parse_workspace_get_target_rejects_item() -> None:
    with pytest.raises(InspectError, match="workspace get"):
        parse_workspace_get_target(f"{WS}:{ITEM}")


def test_parse_item_list_target_ok() -> None:
    target = parse_item_list_target(WS)
    assert target.workspace_id == WS
    assert target.item_id is None


def test_parse_item_list_target_rejects_item() -> None:
    with pytest.raises(InspectError, match="item list"):
        parse_item_list_target(f"{WS}:{ITEM}")


def test_parse_item_get_target_ok() -> None:
    target = parse_item_get_target(f"{WS}:{ITEM}")
    assert target.workspace_id == WS
    assert target.item_id == ITEM


def test_parse_item_get_target_rejects_workspace_only() -> None:
    with pytest.raises(InspectError, match="item get"):
        parse_item_get_target(WS)


def test_parse_target_rejects_invalid_guid() -> None:
    with pytest.raises(InspectError, match="invalid workspace"):
        parse_workspace_get_target("not-a-guid")


def test_parse_target_rejects_csv_multi() -> None:
    with pytest.raises(InspectError, match="single workspace"):
        parse_workspace_get_target(f"{WS},{WS}")

"""Tests for inspect filters, formatters, and --target shape validation."""

from __future__ import annotations

import pytest

from fabric_tools.inspect_cmd import (
    InspectError,
    apply_filters,
    filter_by_name,
    filter_by_type,
    format_item_detail,
    format_item_line,
    format_workspace_detail,
    format_workspace_line,
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


def test_format_workspace_line() -> None:
    line = format_workspace_line(
        {
            "displayName": "Finance",
            "id": WS,
            "type": "Workspace",
            "capacityId": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "domainId": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        }
    )
    assert line.startswith("Finance  id=")
    assert f"id={WS}" in line
    assert "type=Workspace" in line
    assert "capacityId=aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" in line
    assert "domainId=bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb" in line


def test_format_workspace_line_missing_optional() -> None:
    line = format_workspace_line(
        {"displayName": "My workspace", "id": WS, "type": "Personal"}
    )
    assert "capacityId=-" in line
    assert "domainId=-" in line


def test_format_item_line_includes_target() -> None:
    line = format_item_line(
        {
            "displayName": "ETL",
            "id": ITEM,
            "type": "Notebook",
            "workspaceId": WS,
        }
    )
    assert f"target={WS}:{ITEM}" in line
    assert "type=Notebook" in line


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
    assert detail == f"id: {WS}\ndisplayName: Finance\ntype: Workspace"


def test_format_item_detail() -> None:
    detail = format_item_detail(
        {
            "id": ITEM,
            "displayName": "ETL",
            "type": "Notebook",
            "workspaceId": WS,
        }
    )
    assert f"id: {ITEM}" in detail
    assert "type: Notebook" in detail
    assert f"workspaceId: {WS}" in detail


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

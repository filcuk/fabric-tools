"""Tests for workspace:* parsing and expansion."""

from __future__ import annotations

import pytest

from fabric_tools.parsing import (
    CommandMode,
    ParseError,
    Target,
    build_work_items_from_cli,
    classify_cli_endpoints,
    parse_origin_values,
    parse_target_values,
)
from fabric_tools.remote_expand import (
    ExpandError,
    classified_has_wildcard,
    expand_classified,
    expand_targets,
    validate_filter_usage,
)

WS = "11111111-1111-1111-1111-111111111111"
A = "22222222-2222-2222-2222-222222222222"
B = "33333333-3333-3333-3333-333333333333"


def test_parse_wildcard_target() -> None:
    targets = parse_target_values([f"{WS}:*"])
    assert len(targets) == 1
    assert targets[0].wildcard
    assert targets[0].item_id is None
    assert not targets[0].is_create
    assert targets[0].label() == f"{WS}:*"


def test_parse_wildcard_origin() -> None:
    origins = parse_origin_values([f"{WS}:*"])
    assert origins[0].wildcard


def test_wildcard_mixed_with_concrete() -> None:
    targets = parse_target_values([f"{WS}:*,{WS}:{A}"])
    assert targets[0].wildcard
    assert targets[1].item_id == A


def test_filter_requires_wildcard() -> None:
    with pytest.raises(ParseError, match="only valid with workspaceId:\\*"):
        validate_filter_usage("etl", has_wildcard=False)


def test_filter_allowed_with_wildcard() -> None:
    validate_filter_usage("etl", has_wildcard=True)


def test_expand_targets_filters_and_maps() -> None:
    rows = [
        {"id": A, "displayName": "Sales ETL"},
        {"id": B, "displayName": "Other"},
    ]

    def list_items(workspace_id: str) -> list:
        assert workspace_id == WS
        return rows

    expanded = expand_targets(
        [Target(WS, wildcard=True)],
        list_items=list_items,
        name_filter="etl",
        kind_label="Notebook",
    )
    assert len(expanded) == 1
    assert expanded[0].item_id == A
    assert not expanded[0].wildcard


def test_expand_zero_matches_errors() -> None:
    with pytest.raises(ExpandError, match="no Notebook items"):
        expand_targets(
            [Target(WS, wildcard=True)],
            list_items=lambda _ws: [{"id": A, "displayName": "Other"}],
            name_filter="missing",
            kind_label="Notebook",
        )


def test_expand_powerbi_name_field() -> None:
    expanded = expand_targets(
        [Target(WS, wildcard=True)],
        list_items=lambda _ws: [{"objectId": A, "name": "Gen1 Flow"}],
        name_filter="gen1",
        kind_label="dataflow-gen1",
    )
    assert expanded[0].item_id == A


def test_classified_has_wildcard() -> None:
    classified = classify_cli_endpoints(
        origin_values=[f"{WS}:*"],
        target_values=None,
        mode=CommandMode.DOWNLOAD,
    )
    assert classified_has_wildcard(classified)
    expanded = expand_classified(
        classified,
        list_items=lambda _ws: [{"id": A, "displayName": "N"}],
        name_filter=None,
        kind_label="Notebook",
    )
    items = build_work_items_from_cli(
        CommandMode.DOWNLOAD,
        origin_values=[expanded.origin_remotes[0].label()],
        target_values=None,
        dry_run=False,
    )
    # After expand, concrete label works; also expand in place:
    from fabric_tools.parsing import build_work_items_from_classified

    items = build_work_items_from_classified(
        CommandMode.DOWNLOAD, expanded, dry_run=False
    )
    assert len(items) == 1
    assert items[0].target is not None
    assert items[0].target.item_id == A


def test_unexpanded_wildcard_rejected_by_build() -> None:
    with pytest.raises(ParseError, match="unexpanded"):
        build_work_items_from_cli(
            CommandMode.DELETE,
            origin_values=None,
            target_values=[f"{WS}:*"],
            dry_run=False,
        )

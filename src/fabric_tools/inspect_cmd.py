"""Fabric workspace/item inspect helpers (filters, formatting, target shapes)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from fabric_tools.colours import STYLE_DIM, STYLE_HEADER
from fabric_tools.parsing import ParseError, Target, parse_target_values

if TYPE_CHECKING:
    from fabric_tools.client import FabricClient

_COL_GAP = "  "
_WORKSPACE_DETAIL_KEYS = (
    "id",
    "displayName",
    "description",
    "type",
    "capacityId",
    "capacityRegion",
    "capacityAssignmentProgress",
    "domainId",
)
_ITEM_DETAIL_KEYS = (
    "id",
    "displayName",
    "description",
    "type",
    "workspaceId",
    "folderId",
)


class InspectError(ValueError):
    """Invalid inspect arguments or unexpected Fabric payload."""


def filter_by_name(
    rows: list[dict[str, Any]],
    filter_text: str | None,
) -> list[dict[str, Any]]:
    """Keep rows whose ``displayName`` contains *filter_text* (case-insensitive)."""
    if filter_text is None or filter_text == "":
        return list(rows)
    needle = filter_text.casefold()
    return [
        row for row in rows if needle in str(row.get("displayName") or "").casefold()
    ]


def filter_by_type(
    rows: list[dict[str, Any]],
    type_name: str | None,
) -> list[dict[str, Any]]:
    """Keep rows whose Fabric ``type`` equals *type_name* (exact match)."""
    if type_name is None or type_name == "":
        return list(rows)
    return [row for row in rows if row.get("type") == type_name]


def apply_filters(
    rows: list[dict[str, Any]],
    *,
    name_filter: str | None = None,
    type_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Apply name then type filters."""
    return filter_by_type(filter_by_name(rows, name_filter), type_filter)


def workspace_table_cells(workspace: dict[str, Any]) -> tuple[str, str, str, str, str]:
    """Column values for one workspace list row."""
    return (
        _field(workspace, "displayName"),
        _field(workspace, "id"),
        _field(workspace, "type"),
        _field(workspace, "capacityId"),
        _field(workspace, "domainId"),
    )


def item_table_cells(item: dict[str, Any]) -> tuple[str, str, str]:
    """Column values for one item list row (NAME, TARGET, TYPE)."""
    name = _field(item, "displayName")
    item_id = _field(item, "id")
    item_type = _field(item, "type")
    workspace_id = _field(item, "workspaceId")
    if workspace_id != "-" and item_id != "-":
        target = f"{workspace_id}:{item_id}"
    else:
        target = "-"
    return (name, target, item_type)


def format_workspace_table(rows: Sequence[dict[str, Any]]) -> str:
    """Plain aligned workspace table (header + rows) for tests."""
    return _format_plain_table(
        ("NAME", "ID", "TYPE", "CAPACITY", "DOMAIN"),
        [workspace_table_cells(row) for row in rows],
    )


def format_item_table(rows: Sequence[dict[str, Any]]) -> str:
    """Plain aligned item table (header + rows) for tests."""
    return _format_plain_table(
        ("NAME", "TARGET", "TYPE"),
        [item_table_cells(row) for row in rows],
    )


def print_workspace_table(rows: Sequence[dict[str, Any]]) -> None:
    """Print aligned workspace list with dim id/type/capacity/domain."""
    _print_table(
        ("NAME", "ID", "TYPE", "CAPACITY", "DOMAIN"),
        [workspace_table_cells(row) for row in rows],
    )


def print_item_table(rows: Sequence[dict[str, Any]]) -> None:
    """Print aligned item list with dim target/type."""
    _print_table(
        ("NAME", "TARGET", "TYPE"),
        [item_table_cells(row) for row in rows],
    )


def format_workspace_detail(workspace: dict[str, Any]) -> str:
    """Aligned key/value workspace detail for ``inspect workspace get``."""
    return _format_detail(workspace, _WORKSPACE_DETAIL_KEYS)


def format_item_detail(item: dict[str, Any]) -> str:
    """Aligned key/value item detail for ``inspect item get``."""
    return _format_detail(item, _ITEM_DETAIL_KEYS)


def print_workspace_detail(workspace: dict[str, Any]) -> None:
    """Print aligned workspace detail (dim keys, default values)."""
    _print_detail(workspace, _WORKSPACE_DETAIL_KEYS)


def print_item_detail(item: dict[str, Any]) -> None:
    """Print aligned item detail (dim keys, default values)."""
    _print_detail(item, _ITEM_DETAIL_KEYS)


def parse_workspace_get_target(raw: str) -> Target:
    """Parse ``--target`` for workspace get (workspace GUID only)."""
    target = _parse_single_target(raw)
    if target.item_id is not None:
        raise InspectError(
            "inspect workspace get requires --target <workspaceId> (no artifact id)"
        )
    return target


def parse_item_list_target(raw: str) -> Target:
    """Parse ``--target`` for item list (workspace GUID only)."""
    target = _parse_single_target(raw)
    if target.item_id is not None:
        raise InspectError(
            "inspect item list requires --target <workspaceId> (no artifact id)"
        )
    return target


def parse_item_get_target(raw: str) -> Target:
    """Parse ``--target`` for item get (``workspaceId:itemId``)."""
    target = _parse_single_target(raw)
    if target.item_id is None:
        raise InspectError("inspect item get requires --target <workspaceId>:<itemId>")
    return target


def list_workspaces(
    client: FabricClient,
    *,
    name_filter: str | None = None,
    type_filter: str | None = None,
) -> list[dict[str, Any]]:
    """List accessible workspaces (filtered dict rows)."""
    return apply_filters(
        client.list_workspaces(),
        name_filter=name_filter,
        type_filter=type_filter,
    )


def get_workspace_detail(client: FabricClient, target: Target) -> dict[str, Any]:
    """Return the Fabric payload for one workspace."""
    return client.get_workspace(target.workspace_id)


def list_items(
    client: FabricClient,
    target: Target,
    *,
    name_filter: str | None = None,
    type_filter: str | None = None,
) -> list[dict[str, Any]]:
    """List items in a workspace (filtered dict rows).

    When *type_filter* is set, it is passed to the Fabric list API as ``type``
    and also applied client-side for consistency.
    """
    rows = client.list_items(target.workspace_id, type=type_filter)
    # List payloads may omit workspaceId; copy rows so we do not mutate API data.
    normalized: list[dict[str, Any]] = []
    for row in rows:
        entry = dict(row)
        entry.setdefault("workspaceId", target.workspace_id)
        normalized.append(entry)
    return apply_filters(normalized, name_filter=name_filter, type_filter=type_filter)


def get_item_detail(client: FabricClient, target: Target) -> dict[str, Any]:
    """Return the Fabric payload for one item."""
    if target.item_id is None:
        raise InspectError("inspect item get requires --target <workspaceId>:<itemId>")
    return client.get_item(target.workspace_id, target.item_id)


def _parse_single_target(raw: str) -> Target:
    """Parse one inspect ``--target`` (always a remote; never a local path)."""
    text = raw.strip()
    if not text:
        raise InspectError(
            "inspect --target expects a single workspace or workspace:item value"
        )
    try:
        targets = parse_target_values([text])
    except ParseError as exc:
        message = str(exc)
        # Polymorphic CLI treats bare non-GUIDs as paths; inspect never accepts paths.
        if "local path" in message:
            raise InspectError(f"invalid workspace id: '{text}'") from exc
        raise InspectError(message) from exc
    if len(targets) != 1:
        raise InspectError(
            f"inspect --target expects a single workspace or "
            f"workspace:item value; got {len(targets)}"
        )
    return targets[0]


def _field(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if value is None or value == "":
        return "-"
    return str(value)


def _detail_pairs(row: dict[str, Any], keys: tuple[str, ...]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for key in keys:
        if key not in row:
            continue
        value = row.get(key)
        if value is None or value == "":
            continue
        pairs.append((key, str(value)))
    return pairs


def _format_detail(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    pairs = _detail_pairs(row, keys)
    if not pairs:
        return "(no fields)"
    key_w = max(len(key) for key, _ in pairs)
    return "\n".join(f"{key:>{key_w}}{_COL_GAP}{value}" for key, value in pairs)


def _print_detail(row: dict[str, Any], keys: tuple[str, ...]) -> None:
    from rich.console import Console
    from rich.text import Text

    pairs = _detail_pairs(row, keys)
    if not pairs:
        Console().print("(no fields)")
        return
    key_w = max(len(key) for key, _ in pairs)
    console = Console()
    for key, value in pairs:
        line = Text()
        line.append(f"{key:>{key_w}}", style=STYLE_DIM)
        line.append(_COL_GAP)
        line.append(value)
        console.print(line)


def _column_widths(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
) -> list[int]:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    return widths


def _pad_row(cells: Sequence[str], widths: Sequence[int]) -> list[str]:
    return [f"{cell:<{widths[i]}}" for i, cell in enumerate(cells)]


def _format_plain_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
) -> str:
    widths = _column_widths(headers, rows)
    lines = [_COL_GAP.join(_pad_row(headers, widths))]
    for row in rows:
        lines.append(_COL_GAP.join(_pad_row(row, widths)))
    return "\n".join(lines)


def _print_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
) -> None:
    from rich.console import Console
    from rich.text import Text

    widths = _column_widths(headers, rows)
    console = Console()

    header_line = Text()
    for i, cell in enumerate(_pad_row(headers, widths)):
        if i:
            header_line.append(_COL_GAP)
        header_line.append(cell, style=STYLE_HEADER)
    console.print(header_line)

    for row in rows:
        line = Text()
        padded = _pad_row(row, widths)
        for i, cell in enumerate(padded):
            if i:
                line.append(_COL_GAP)
            # Column 0 (NAME) default; remaining columns dim (id/target/type/…).
            line.append(cell, style=STYLE_DIM if i > 0 else None)
        console.print(line)

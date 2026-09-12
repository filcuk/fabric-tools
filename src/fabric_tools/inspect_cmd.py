"""Fabric workspace/item inspect helpers (filters, formatting, target shapes)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fabric_tools.parsing import ParseError, Target, parse_target_values

if TYPE_CHECKING:
    from fabric_tools.client import FabricClient


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


def format_workspace_line(workspace: dict[str, Any]) -> str:
    """One-line workspace summary for ``inspect workspace list``."""
    name = _field(workspace, "displayName")
    workspace_id = _field(workspace, "id")
    workspace_type = _field(workspace, "type")
    capacity_id = _field(workspace, "capacityId")
    domain_id = _field(workspace, "domainId")
    return (
        f"{name}  id={workspace_id}  type={workspace_type}  "
        f"capacityId={capacity_id}  domainId={domain_id}"
    )


def format_item_line(item: dict[str, Any]) -> str:
    """One-line item summary for ``inspect item list``."""
    name = _field(item, "displayName")
    item_id = _field(item, "id")
    item_type = _field(item, "type")
    workspace_id = _field(item, "workspaceId")
    if workspace_id != "-" and item_id != "-":
        target = f"{workspace_id}:{item_id}"
    else:
        target = "-"
    return (
        f"{name}  id={item_id}  type={item_type}  "
        f"workspaceId={workspace_id}  target={target}"
    )


def format_workspace_detail(workspace: dict[str, Any]) -> str:
    """Multi-line workspace detail for ``inspect workspace get``."""
    return _format_detail(
        workspace,
        (
            "id",
            "displayName",
            "description",
            "type",
            "capacityId",
            "capacityRegion",
            "capacityAssignmentProgress",
            "domainId",
        ),
    )


def format_item_detail(item: dict[str, Any]) -> str:
    """Multi-line item detail for ``inspect item get``."""
    return _format_detail(
        item,
        (
            "id",
            "displayName",
            "description",
            "type",
            "workspaceId",
            "folderId",
        ),
    )


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


def list_workspace_lines(
    client: FabricClient,
    *,
    name_filter: str | None = None,
    type_filter: str | None = None,
) -> list[str]:
    """List accessible workspaces as one-line summaries."""
    rows = apply_filters(
        client.list_workspaces(),
        name_filter=name_filter,
        type_filter=type_filter,
    )
    return [format_workspace_line(row) for row in rows]


def get_workspace_detail(client: FabricClient, target: Target) -> str:
    """Return multi-line detail for one workspace."""
    return format_workspace_detail(client.get_workspace(target.workspace_id))


def list_item_lines(
    client: FabricClient,
    target: Target,
    *,
    name_filter: str | None = None,
    type_filter: str | None = None,
) -> list[str]:
    """List items in a workspace as one-line summaries.

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
    normalized = apply_filters(
        normalized, name_filter=name_filter, type_filter=type_filter
    )
    return [format_item_line(row) for row in normalized]


def get_item_detail(client: FabricClient, target: Target) -> str:
    """Return multi-line detail for one item."""
    if target.item_id is None:
        raise InspectError("inspect item get requires --target <workspaceId>:<itemId>")
    return format_item_detail(client.get_item(target.workspace_id, target.item_id))


def _parse_single_target(raw: str) -> Target:
    try:
        targets = parse_target_values([raw])
    except ParseError as exc:
        raise InspectError(str(exc)) from exc
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


def _format_detail(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    lines: list[str] = []
    for key in keys:
        if key not in row:
            continue
        value = row.get(key)
        if value is None or value == "":
            continue
        lines.append(f"{key}: {value}")
    if not lines:
        return "(no fields)"
    return "\n".join(lines)

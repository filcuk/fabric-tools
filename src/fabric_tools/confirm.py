"""User confirmation prompts for overwrite and create actions."""

from __future__ import annotations

from pathlib import Path

import typer

from fabric_tools.client import FabricApiError, FabricClient
from fabric_tools.parsing import Target, WorkItem


class ConfirmationAborted(Exception):
    """Raised when the user declines a confirmation prompt."""


def confirm_or_abort(message: str, *, silent: bool) -> None:
    """Prompt unless ``silent``; abort on decline."""
    if silent:
        return
    if not typer.confirm(message, default=False):
        raise ConfirmationAborted("Aborted by user.")


def resolve_workspace_name(client: FabricClient, workspace_id: str) -> str:
    try:
        data = client.get_workspace(workspace_id)
    except FabricApiError as exc:
        return f"{workspace_id} (unavailable: {exc})"
    name = data.get("displayName") or data.get("name") or workspace_id
    return f"{name} ({workspace_id})"


def resolve_item_name(client: FabricClient, target: Target) -> str:
    if target.item_id is None:
        return "(new notebook)"
    try:
        data = client.get_item(target.workspace_id, target.item_id)
    except FabricApiError as exc:
        return f"{target.item_id} (unavailable: {exc})"
    name = data.get("displayName") or data.get("name") or target.item_id
    item_type = data.get("type")
    suffix = f", type={item_type}" if item_type else ""
    return f"{name} ({target.item_id}{suffix})"


def confirm_download_overwrites(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm before overwriting existing local paths."""
    if silent:
        return
    existing = [
        item
        for item in items
        if item.target is not None and item.file is not None and _path_exists(item.file)
    ]
    if not existing:
        return

    lines = ["About to overwrite local path(s):"]
    for item in existing:
        assert item.target is not None and item.file is not None
        remote = resolve_item_name(client, item.target)
        workspace = resolve_workspace_name(client, item.target.workspace_id)
        lines.append(f"  - local `{item.file}` <- remote {remote} in {workspace}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_upload_actions(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
    display_names: list[str] | None = None,
    cell_indices: list[int] | None = None,
) -> None:
    """Confirm create or remote overwrite before upload."""
    if silent or not items:
        return

    first = items[0].target
    if first is None:
        return

    if first.is_create:
        lines = ["About to create notebook(s):"]
        for index, item in enumerate(items):
            assert item.target is not None
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            name = (
                display_names[index]
                if display_names and index < len(display_names)
                else (item.file.name if item.file else "(unnamed)")
            )
            local = f" from `{item.file}`" if item.file else ""
            lines.append(f"  - '{name}' in {workspace}{local}")
        lines.append("Are you sure?")
        confirm_or_abort("\n".join(lines), silent=False)
        return

    if cell_indices is not None:
        cells_label = ", ".join(str(index) for index in cell_indices)
        lines = [f"About to overwrite cell(s) [{cells_label}] in remote notebook:"]
    else:
        lines = ["About to overwrite remote notebook(s):"]
    for item in items:
        assert item.target is not None
        workspace = resolve_workspace_name(client, item.target.workspace_id)
        remote = resolve_item_name(client, item.target)
        local = f" with `{item.file}`" if item.file else ""
        lines.append(f"  - {remote} in {workspace}{local}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def _path_exists(path: Path) -> bool:
    return path.exists()

"""User confirmation prompts for overwrite, create, and delete actions."""

from __future__ import annotations

from pathlib import Path

import typer

from fabric_tools.client import FabricApiError, FabricClient
from fabric_tools.parsing import Target, WorkItem
from fabric_tools.powerbi_client import PowerBiApiError, PowerBiClient
from fabric_tools.status import busy


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


def resolve_powerbi_group_name(client: PowerBiClient, group_id: str) -> str:
    try:
        data = client.get_group(group_id)
    except PowerBiApiError as exc:
        return f"{group_id} (unavailable: {exc})"
    name = data.get("name") or data.get("displayName") or group_id
    return f"{name} ({group_id})"


def resolve_powerbi_dataflow_name(client: PowerBiClient, target: Target) -> str:
    if target.item_id is None:
        return "(new dataflow-gen1)"
    try:
        data = client.get_dataflow(target.workspace_id, target.item_id)
    except PowerBiApiError as exc:
        return f"{target.item_id} (unavailable: {exc})"
    name = data.get("name") or target.item_id
    return f"{name} ({target.item_id})"


def confirm_download_overwrites(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm before overwriting existing local paths (Fabric notebooks)."""
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
    with busy("Resolving targets..."):
        for item in existing:
            assert item.target is not None and item.file is not None
            remote = resolve_item_name(client, item.target)
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            lines.append(f"  - local `{item.file}` <- remote {remote} in {workspace}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_download_overwrites_dataflow_gen1(
    client: PowerBiClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm before overwriting existing local model.json paths."""
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
    with busy("Resolving targets..."):
        for item in existing:
            assert item.target is not None and item.file is not None
            remote = resolve_powerbi_dataflow_name(client, item.target)
            workspace = resolve_powerbi_group_name(client, item.target.workspace_id)
            lines.append(f"  - local `{item.file}` <- remote {remote} in {workspace}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_deploy_actions(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
    display_names: list[str] | None = None,
    cell_indices: list[int] | None = None,
) -> None:
    """Confirm create or remote overwrite before notebook deploy."""
    if silent or not items:
        return

    first = items[0].target
    if first is None:
        return

    if first.is_create:
        lines = ["About to create notebook(s):"]
        with busy("Resolving targets..."):
            for index, item in enumerate(items):
                assert item.target is not None
                workspace = resolve_workspace_name(client, item.target.workspace_id)
                name: str | None = None
                if display_names and index < len(display_names) and display_names[index]:
                    name = display_names[index]
                if not name:
                    if item.file is not None:
                        name = item.file.name
                    elif item.origin is not None:
                        name = resolve_item_name(client, item.origin)
                    else:
                        name = "(unnamed)"
                source = _source_phrase_fabric(client, item)
                lines.append(f"  - '{name}' in {workspace}{source}")
        lines.append("Are you sure?")
        confirm_or_abort("\n".join(lines), silent=False)
        return

    if cell_indices is not None:
        cells_label = ", ".join(str(index) for index in cell_indices)
        lines = [f"About to overwrite cell(s) [{cells_label}] in remote notebook:"]
    else:
        lines = ["About to overwrite remote notebook(s):"]
    with busy("Resolving targets..."):
        for item in items:
            assert item.target is not None
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            remote = resolve_item_name(client, item.target)
            source = _source_phrase_fabric(client, item, prefix=" with")
            lines.append(f"  - {remote} in {workspace}{source}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_deploy_create_dataflow_gen1(
    client: PowerBiClient,
    items: list[WorkItem],
    *,
    silent: bool,
    display_names: list[str] | None = None,
) -> None:
    """Confirm Gen1 dataflow create (no overwrite)."""
    if silent or not items:
        return

    lines = ["About to create dataflow-gen1 item(s):"]
    with busy("Resolving targets..."):
        for index, item in enumerate(items):
            assert item.target is not None
            workspace = resolve_powerbi_group_name(client, item.target.workspace_id)
            name: str | None = None
            if display_names and index < len(display_names) and display_names[index]:
                name = display_names[index]
            if not name:
                if item.file is not None:
                    name = item.file.name
                elif item.origin is not None:
                    name = resolve_powerbi_dataflow_name(client, item.origin)
                else:
                    name = "(unnamed)"
            source = _source_phrase_powerbi(client, item)
            lines.append(f"  - '{name}' in {workspace}{source}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_delete_actions(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm soft-delete of remote Fabric notebooks."""
    if silent or not items:
        return

    lines = ["About to delete remote notebook(s):"]
    with busy("Resolving targets..."):
        for item in items:
            assert item.target is not None
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            remote = resolve_item_name(client, item.target)
            lines.append(f"  - {remote} in {workspace}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_delete_dataflow_gen1(
    client: PowerBiClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm delete of remote Dataflow Gen1 items."""
    if silent or not items:
        return

    lines = ["About to delete remote dataflow-gen1 item(s):"]
    with busy("Resolving targets..."):
        for item in items:
            assert item.target is not None
            workspace = resolve_powerbi_group_name(client, item.target.workspace_id)
            remote = resolve_powerbi_dataflow_name(client, item.target)
            lines.append(f"  - {remote} in {workspace}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def _source_phrase_fabric(
    client: FabricClient,
    item: WorkItem,
    *,
    prefix: str = " from",
) -> str:
    if item.file is not None:
        return f"{prefix} `{item.file}`"
    if item.origin is not None:
        origin_name = resolve_item_name(client, item.origin)
        origin_ws = resolve_workspace_name(client, item.origin.workspace_id)
        return f"{prefix} origin {origin_name} in {origin_ws}"
    return ""


def _source_phrase_powerbi(
    client: PowerBiClient,
    item: WorkItem,
    *,
    prefix: str = " from",
) -> str:
    if item.file is not None:
        return f"{prefix} `{item.file}`"
    if item.origin is not None:
        origin_name = resolve_powerbi_dataflow_name(client, item.origin)
        origin_ws = resolve_powerbi_group_name(client, item.origin.workspace_id)
        return f"{prefix} origin {origin_name} in {origin_ws}"
    return ""


def _path_exists(path: Path) -> bool:
    return path.exists()

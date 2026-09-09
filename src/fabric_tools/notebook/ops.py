"""Notebook download / create / overwrite operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fabric_tools.client import FabricApiError, FabricClient
from fabric_tools.notebook.cells import (
    CellSelectionError,
    format_cell_indices,
    merge_notebook_cells,
)
from fabric_tools.notebook.definition import (
    DefinitionError,
    NotebookFormat,
    definition_has_platform,
    detect_format,
    format_for_api,
    ipynb_from_definition,
    merge_remote_dependencies,
    pack_definition,
    pack_ipynb_dict,
    read_ipynb,
    unpack_definition,
)
from fabric_tools.parsing import WorkItem


@dataclass
class OpResult:
    ok: bool
    message: str
    workspace_id: str | None = None
    item_id: str | None = None


def download_notebook(
    client: FabricClient,
    item: WorkItem,
) -> OpResult:
    """Download one remote notebook definition to a local path."""
    if item.target is None or item.target.item_id is None:
        return OpResult(False, "download requires workspace:artifact target")
    if item.file is None:
        return OpResult(False, "download requires a local --file path")

    target = item.target
    dest = item.file
    try:
        fmt = detect_format(dest)
    except DefinitionError as exc:
        return OpResult(False, str(exc), target.workspace_id, target.item_id)

    try:
        definition = get_notebook_definition(
            client,
            target.workspace_id,
            target.item_id,
            format=fmt,
        )
        written = unpack_definition(definition, dest, format_hint=fmt)
    except (FabricApiError, DefinitionError) as exc:
        return OpResult(
            False,
            f"download failed {target.label()} -> {dest}: {exc}",
            target.workspace_id,
            target.item_id,
        )

    return OpResult(
        True,
        f"downloaded {target.label()} -> {written}",
        target.workspace_id,
        target.item_id,
    )


def upload_notebook(
    client: FabricClient,
    item: WorkItem,
    *,
    display_name: str | None = None,
    cell_indices: list[int] | None = None,
) -> OpResult:
    """Create or overwrite one notebook from a local path."""
    if item.target is None:
        return OpResult(False, "upload requires a --target")
    if item.file is None:
        return OpResult(False, "upload requires a local --file path")

    target = item.target
    path = item.file

    if cell_indices is not None:
        return _upload_selective_cells(client, item, cell_indices=cell_indices)

    try:
        definition = pack_definition(path)
    except DefinitionError as exc:
        return OpResult(False, f"upload pack failed {path}: {exc}", target.workspace_id)

    if target.is_create:
        name = display_name or path.name
        try:
            created = create_notebook(
                client,
                target.workspace_id,
                display_name=name,
                definition=definition,
            )
        except FabricApiError as exc:
            return OpResult(
                False,
                f"create failed in {target.workspace_id} from {path}: {exc}",
                target.workspace_id,
            )
        item_id = str(created.get("id") or "")
        return OpResult(
            True,
            f"created {target.workspace_id}:{item_id} from {path} (name='{name}')",
            target.workspace_id,
            item_id or None,
        )

    assert target.item_id is not None
    preserved_keys: list[str] = []
    try:
        if detect_format(path) is NotebookFormat.IPYNB:
            local_nb = read_ipynb(path)
            remote_definition = get_notebook_definition(
                client,
                target.workspace_id,
                target.item_id,
                format=NotebookFormat.IPYNB,
            )
            remote_nb = ipynb_from_definition(remote_definition)
            merged_nb, preserved_keys = merge_remote_dependencies(local_nb, remote_nb)
            if preserved_keys:
                definition = pack_ipynb_dict(merged_nb)
        update_notebook_definition(
            client,
            target.workspace_id,
            target.item_id,
            definition=definition,
            update_metadata=definition_has_platform(definition),
        )
    except (FabricApiError, DefinitionError) as exc:
        return OpResult(
            False,
            f"overwrite failed {target.label()} from {path}: {exc}",
            target.workspace_id,
            target.item_id,
        )
    suffix = ""
    if preserved_keys:
        suffix = f" (preserved remote {', '.join(preserved_keys)})"
    return OpResult(
        True,
        f"updated {target.label()} from {path}{suffix}",
        target.workspace_id,
        target.item_id,
    )


def _upload_selective_cells(
    client: FabricClient,
    item: WorkItem,
    *,
    cell_indices: list[int],
) -> OpResult:
    """Fetch remote notebook, replace selected cells from local, then update."""
    assert item.target is not None and item.file is not None
    target = item.target
    path = item.file
    assert target.item_id is not None
    cells_label = format_cell_indices(cell_indices)

    try:
        local_nb = read_ipynb(path)
        remote_definition = get_notebook_definition(
            client,
            target.workspace_id,
            target.item_id,
            format=NotebookFormat.IPYNB,
        )
        remote_nb = ipynb_from_definition(remote_definition)
        merged = merge_notebook_cells(remote_nb, local_nb, cell_indices)
        definition = pack_ipynb_dict(merged)
    except (DefinitionError, CellSelectionError) as exc:
        return OpResult(
            False,
            f"cell update failed {target.label()} from {path}: {exc}",
            target.workspace_id,
            target.item_id,
        )
    except FabricApiError as exc:
        return OpResult(
            False,
            f"cell update failed {target.label()} from {path}: {exc}",
            target.workspace_id,
            target.item_id,
        )

    try:
        update_notebook_definition(
            client,
            target.workspace_id,
            target.item_id,
            definition=definition,
            update_metadata=False,
        )
    except FabricApiError as exc:
        return OpResult(
            False,
            f"cell update failed {target.label()} from {path}: {exc}",
            target.workspace_id,
            target.item_id,
        )
    return OpResult(
        True,
        f"updated cells [{cells_label}] in {target.label()} from {path}",
        target.workspace_id,
        target.item_id,
    )


def get_notebook_definition(
    client: FabricClient,
    workspace_id: str,
    notebook_id: str,
    *,
    format: NotebookFormat,
) -> dict[str, Any]:
    """POST getDefinition and return the definition object (parts/format)."""
    result = client.request(
        "POST",
        f"/workspaces/{workspace_id}/notebooks/{notebook_id}/getDefinition",
        params={"format": format_for_api(format)},
    )
    definition = _extract_definition(result)
    if definition.get("format") is None:
        definition = {**definition, "format": format_for_api(format)}
    return definition


def create_notebook(
    client: FabricClient,
    workspace_id: str,
    *,
    display_name: str,
    definition: dict[str, Any],
) -> dict[str, Any]:
    """POST /items to create a Notebook with definition."""
    payload = {
        "displayName": display_name,
        "type": "Notebook",
        "definition": definition,
    }
    result = client.request(
        "POST",
        f"/workspaces/{workspace_id}/items",
        json=payload,
    )
    if not isinstance(result, dict):
        raise FabricApiError("Create notebook returned an empty response")
    return result


def update_notebook_definition(
    client: FabricClient,
    workspace_id: str,
    notebook_id: str,
    *,
    definition: dict[str, Any],
    update_metadata: bool = False,
) -> Any:
    """POST updateDefinition for an existing notebook."""
    params = {"updateMetadata": "true"} if update_metadata else None
    return client.request(
        "POST",
        f"/workspaces/{workspace_id}/notebooks/{notebook_id}/updateDefinition",
        params=params,
        json={"definition": definition},
    )


def run_download_batch(client: FabricClient, items: list[WorkItem]) -> list[OpResult]:
    return [download_notebook(client, item) for item in items]


def run_upload_batch(
    client: FabricClient,
    items: list[WorkItem],
    *,
    display_names: list[str] | None = None,
    cell_indices: list[int] | None = None,
) -> list[OpResult]:
    results: list[OpResult] = []
    for index, item in enumerate(items):
        name = None
        if display_names and index < len(display_names):
            name = display_names[index]
        results.append(
            upload_notebook(
                client,
                item,
                display_name=name,
                cell_indices=cell_indices,
            )
        )
    return results


def _extract_definition(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise FabricApiError("Notebook definition response was empty")
    if "definition" in result and isinstance(result["definition"], dict):
        return result["definition"]
    if "parts" in result:
        return result
    raise FabricApiError(
        "Notebook definition response missing 'definition'",
        details=result,
    )

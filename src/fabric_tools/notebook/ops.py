"""Notebook download / create / overwrite (deploy) operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fabric_tools.client import FabricApiError, FabricClient
from fabric_tools.guid_map import GuidMapError, apply_guid_map_to_definition
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
    strip_preserved_dependencies,
    unpack_definition,
)
from fabric_tools.parsing import WorkItem
from fabric_tools.status import BatchProgress, short_guid, status_detail


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
        return OpResult(False, "download requires a local --target path")

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


def deploy_notebook(
    client: FabricClient,
    item: WorkItem,
    *,
    display_name: str | None = None,
    cell_indices: list[int] | None = None,
    origin_definition_cache: dict[str, dict[str, Any]] | None = None,
    guid_map: dict[str, str] | None = None,
) -> OpResult:
    """Create or overwrite one notebook from a local path or Fabric origin.

    When *guid_map* is set, source→target GUID tokens in definition text parts
    are rewritten in memory before create/update (local files are not edited).
    On overwrite, target lakehouse/environment preserve still runs after remap.
    """
    if item.target is None:
        return OpResult(False, "deploy requires a --target")
    if item.file is None and item.origin is None:
        return OpResult(False, "deploy requires a local path or remote --origin")
    if item.file is not None and item.origin is not None:
        return OpResult(False, "deploy cannot mix a local path and a remote --origin")

    target = item.target

    if cell_indices is not None:
        return _deploy_selective_cells(
            client, item, cell_indices=cell_indices, guid_map=guid_map
        )

    try:
        definition, source_label = _resolve_source_definition(
            client,
            item,
            origin_definition_cache=origin_definition_cache,
        )
        remap_suffix = ""
        if guid_map:
            definition, n_replaced = apply_guid_map_to_definition(definition, guid_map)
            remap_suffix = f" (remapped {n_replaced} GUID(s))"
    except (FabricApiError, DefinitionError, GuidMapError) as exc:
        return OpResult(
            False,
            f"deploy source failed: {exc}",
            target.workspace_id,
            target.item_id,
        )

    if target.is_create:
        name = display_name
        if not name:
            if item.file is not None:
                name = item.file.name
            else:
                assert item.origin is not None and item.origin.item_id is not None
                try:
                    meta = client.get_item(
                        item.origin.workspace_id, item.origin.item_id
                    )
                    name = str(
                        meta.get("displayName") or meta.get("name") or "Notebook"
                    )
                except FabricApiError:
                    name = "Notebook"
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
                f"create failed in {target.workspace_id} from {source_label}: {exc}",
                target.workspace_id,
            )
        item_id = str(created.get("id") or "")
        return OpResult(
            True,
            f"created {target.workspace_id}:{item_id} from {source_label} "
            f"(name='{name}'){remap_suffix}",
            target.workspace_id,
            item_id or None,
        )

    assert target.item_id is not None
    preserved_keys: list[str] = []
    try:
        if item.origin is not None:
            origin_nb = ipynb_from_definition(definition)
            stripped = strip_preserved_dependencies(origin_nb)
            remote_definition = get_notebook_definition(
                client,
                target.workspace_id,
                target.item_id,
                format=NotebookFormat.IPYNB,
            )
            remote_nb = ipynb_from_definition(remote_definition)
            merged_nb, preserved_keys = merge_remote_dependencies(stripped, remote_nb)
            definition = pack_ipynb_dict(merged_nb)
        elif detect_format(item.file) is NotebookFormat.IPYNB:  # type: ignore[arg-type]
            assert item.file is not None
            local_nb = ipynb_from_definition(definition)
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
            f"overwrite failed {target.label()} from {source_label}: {exc}",
            target.workspace_id,
            target.item_id,
        )
    suffix = ""
    if preserved_keys:
        suffix = f" (preserved remote {', '.join(preserved_keys)})"
    return OpResult(
        True,
        f"updated {target.label()} from {source_label}{suffix}{remap_suffix}",
        target.workspace_id,
        target.item_id,
    )


def _resolve_source_definition(
    client: FabricClient,
    item: WorkItem,
    *,
    origin_definition_cache: dict[str, dict[str, Any]] | None,
) -> tuple[dict[str, Any], str]:
    if item.file is not None:
        return pack_definition(item.file), str(item.file)

    assert item.origin is not None and item.origin.item_id is not None
    origin = item.origin
    label = f"origin {origin.label()}"
    cache_key = origin.label()
    if origin_definition_cache is not None and cache_key in origin_definition_cache:
        return origin_definition_cache[cache_key], label

    definition = get_notebook_definition(
        client,
        origin.workspace_id,
        origin.item_id,
        format=NotebookFormat.IPYNB,
    )
    if origin_definition_cache is not None:
        origin_definition_cache[cache_key] = definition
    return definition, label


def _deploy_selective_cells(
    client: FabricClient,
    item: WorkItem,
    *,
    cell_indices: list[int],
    guid_map: dict[str, str] | None = None,
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
        remap_suffix = ""
        if guid_map:
            definition, n_replaced = apply_guid_map_to_definition(definition, guid_map)
            remap_suffix = f" (remapped {n_replaced} GUID(s))"
    except (DefinitionError, CellSelectionError, GuidMapError) as exc:
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
        f"updated cells [{cells_label}] in {target.label()} from {path}{remap_suffix}",
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


def delete_notebook(client: FabricClient, item: WorkItem) -> OpResult:
    """Soft-delete one remote notebook."""
    if item.target is None or item.target.item_id is None:
        return OpResult(False, "delete requires workspace:artifact target")

    target = item.target
    try:
        client.request(
            "DELETE",
            f"/workspaces/{target.workspace_id}/notebooks/{target.item_id}",
        )
    except FabricApiError as exc:
        return OpResult(
            False,
            f"delete failed {target.label()}: {exc}",
            target.workspace_id,
            target.item_id,
        )
    return OpResult(
        True,
        f"deleted {target.label()}",
        target.workspace_id,
        target.item_id,
    )


def run_download_batch(client: FabricClient, items: list[WorkItem]) -> list[OpResult]:
    progress = BatchProgress(total=len(items))
    results: list[OpResult] = []
    for item in items:
        target = item.target
        item_id = target.item_id if target is not None else None
        progress.advance(status_detail("notebook", "downloading", item_id))
        results.append(download_notebook(client, item))
    return results


def run_deploy_batch(
    client: FabricClient,
    items: list[WorkItem],
    *,
    display_names: list[str] | None = None,
    cell_indices: list[int] | None = None,
    guid_maps: list[dict[str, str] | None] | None = None,
) -> list[OpResult]:
    progress = BatchProgress(total=len(items))
    results: list[OpResult] = []
    origin_cache: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items):
        name = None
        if display_names and index < len(display_names):
            name = display_names[index]
        guid_map = None
        if guid_maps and index < len(guid_maps):
            guid_map = guid_maps[index]
        target = item.target
        if target is not None and target.is_create:
            progress.advance(status_detail("notebook", "creating"))
        elif target is not None and cell_indices is not None:
            cells_label = format_cell_indices(cell_indices)
            item_id = target.item_id
            detail = f"Updating cells [{cells_label}]"
            if item_id:
                detail = f"{detail} ({short_guid(item_id)})"
            progress.advance(f"{detail}…")
        elif target is not None:
            progress.advance(status_detail("notebook", "deploying", target.item_id))
        else:
            progress.advance(status_detail("notebook", "deploying"))
        results.append(
            deploy_notebook(
                client,
                item,
                display_name=name,
                cell_indices=cell_indices,
                origin_definition_cache=origin_cache,
                guid_map=guid_map,
            )
        )
    return results


def run_delete_batch(client: FabricClient, items: list[WorkItem]) -> list[OpResult]:
    progress = BatchProgress(total=len(items))
    results: list[OpResult] = []
    for item in items:
        target = item.target
        item_id = target.item_id if target is not None else None
        progress.advance(status_detail("notebook", "deleting", item_id))
        results.append(delete_notebook(client, item))
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

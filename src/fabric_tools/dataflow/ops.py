"""Dataflow Gen2 download / create / overwrite / delete operations (Fabric API)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fabric_tools.client import FabricApiError, FabricClient
from fabric_tools.dataflow.definition import (
    DefinitionError,
    definition_has_platform,
    detect_dataflow_path,
    display_name_from_path,
    pack_definition,
    unpack_definition,
)
from fabric_tools.parsing import WorkItem
from fabric_tools.status import update as update_status

ITEM_TYPE = "Dataflow"


@dataclass
class OpResult:
    ok: bool
    message: str
    workspace_id: str | None = None
    item_id: str | None = None


def download_dataflow(client: FabricClient, item: WorkItem) -> OpResult:
    """Download one remote Dataflow Gen2 definition to a local folder."""
    if item.target is None or item.target.item_id is None:
        return OpResult(False, "download requires workspace:artifact target")
    if item.file is None:
        return OpResult(False, "download requires a local --file path")

    target = item.target
    dest = item.file
    try:
        detect_dataflow_path(dest)
        definition = get_dataflow_definition(
            client, target.workspace_id, target.item_id
        )
        written = unpack_definition(definition, dest)
    except (FabricApiError, DefinitionError, OSError) as exc:
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


def deploy_dataflow(
    client: FabricClient,
    item: WorkItem,
    *,
    display_name: str | None = None,
    origin_definition_cache: dict[str, dict[str, Any]] | None = None,
) -> OpResult:
    """Create or overwrite one Dataflow Gen2 from a local folder or Fabric origin."""
    if item.target is None:
        return OpResult(False, "deploy requires a --target")
    if item.file is None and item.origin is None:
        return OpResult(False, "deploy requires a local --file or --origin")
    if item.file is not None and item.origin is not None:
        return OpResult(False, "deploy cannot use both --file and --origin")

    target = item.target

    try:
        definition, source_label = _resolve_source_definition(
            client,
            item,
            origin_definition_cache=origin_definition_cache,
        )
    except (FabricApiError, DefinitionError) as exc:
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
                name = display_name_from_path(item.file)
            else:
                assert item.origin is not None and item.origin.item_id is not None
                try:
                    meta = client.get_item(
                        item.origin.workspace_id, item.origin.item_id
                    )
                    name = str(
                        meta.get("displayName") or meta.get("name") or "Dataflow"
                    )
                except FabricApiError:
                    name = "Dataflow"
        try:
            created = create_dataflow(
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
            f"created {target.workspace_id}:{item_id} from {source_label} (name='{name}')",
            target.workspace_id,
            item_id or None,
        )

    assert target.item_id is not None
    try:
        update_dataflow_definition(
            client,
            target.workspace_id,
            target.item_id,
            definition=definition,
            update_metadata=definition_has_platform(definition),
        )
    except FabricApiError as exc:
        return OpResult(
            False,
            f"overwrite failed {target.label()} from {source_label}: {exc}",
            target.workspace_id,
            target.item_id,
        )
    return OpResult(
        True,
        f"updated {target.label()} from {source_label}",
        target.workspace_id,
        target.item_id,
    )


def delete_dataflow(client: FabricClient, item: WorkItem) -> OpResult:
    """Soft-delete one remote Dataflow Gen2."""
    if item.target is None or item.target.item_id is None:
        return OpResult(False, "delete requires workspace:artifact target")

    target = item.target
    try:
        client.request(
            "DELETE",
            f"/workspaces/{target.workspace_id}/dataflows/{target.item_id}",
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


def get_dataflow_definition(
    client: FabricClient,
    workspace_id: str,
    dataflow_id: str,
) -> dict[str, Any]:
    """POST getDefinition and return the definition object (parts)."""
    result = client.request(
        "POST",
        f"/workspaces/{workspace_id}/dataflows/{dataflow_id}/getDefinition",
    )
    return _extract_definition(result)


def create_dataflow(
    client: FabricClient,
    workspace_id: str,
    *,
    display_name: str,
    definition: dict[str, Any],
) -> dict[str, Any]:
    """POST /items to create a Dataflow with definition."""
    payload = {
        "displayName": display_name,
        "type": ITEM_TYPE,
        "definition": definition,
    }
    result = client.request(
        "POST",
        f"/workspaces/{workspace_id}/items",
        json=payload,
    )
    if not isinstance(result, dict):
        raise FabricApiError("Create dataflow returned an empty response")
    return result


def update_dataflow_definition(
    client: FabricClient,
    workspace_id: str,
    dataflow_id: str,
    *,
    definition: dict[str, Any],
    update_metadata: bool = False,
) -> Any:
    """POST updateDefinition for an existing dataflow."""
    params = {"updateMetadata": "true"} if update_metadata else None
    return client.request(
        "POST",
        f"/workspaces/{workspace_id}/dataflows/{dataflow_id}/updateDefinition",
        params=params,
        json={"definition": definition},
    )


def run_download_batch(client: FabricClient, items: list[WorkItem]) -> list[OpResult]:
    results: list[OpResult] = []
    for item in items:
        target = item.target
        dest = item.file
        if target is not None and dest is not None:
            update_status(f"Downloading {target.label()} -> {dest}...")
        else:
            update_status("Downloading dataflow...")
        results.append(download_dataflow(client, item))
    return results


def run_deploy_batch(
    client: FabricClient,
    items: list[WorkItem],
    *,
    display_names: list[str] | None = None,
) -> list[OpResult]:
    results: list[OpResult] = []
    origin_cache: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items):
        name = None
        if display_names and index < len(display_names):
            name = display_names[index]
        target = item.target
        if target is not None and target.is_create:
            label = name or (
                display_name_from_path(item.file)
                if item.file is not None
                else "dataflow"
            )
            update_status(f"Creating '{label}' in {target.workspace_id}...")
        elif target is not None:
            update_status(f"Deploying to {target.label()}...")
        else:
            update_status("Deploying dataflow...")
        results.append(
            deploy_dataflow(
                client,
                item,
                display_name=name,
                origin_definition_cache=origin_cache,
            )
        )
    return results


def run_delete_batch(client: FabricClient, items: list[WorkItem]) -> list[OpResult]:
    results: list[OpResult] = []
    for item in items:
        target = item.target
        if target is not None:
            update_status(f"Deleting {target.label()}...")
        else:
            update_status("Deleting dataflow...")
        results.append(delete_dataflow(client, item))
    return results


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

    definition = get_dataflow_definition(client, origin.workspace_id, origin.item_id)
    if origin_definition_cache is not None:
        origin_definition_cache[cache_key] = definition
    return definition, label


def _extract_definition(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise FabricApiError("Dataflow definition response was empty")
    if "definition" in result and isinstance(result["definition"], dict):
        return result["definition"]
    if "parts" in result:
        return result
    raise FabricApiError(
        "Dataflow definition response missing 'definition'",
        details=result,
    )

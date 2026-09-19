"""Microsoft Fabric Org App download, deploy, and delete operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fabric_tools.client import FabricApiError, FabricClient
from fabric_tools.org_app.definition import (
    DefinitionError,
    definition_has_platform,
    detect_org_app_path,
    display_name_from_path,
    pack_definition,
    unpack_definition,
)
from fabric_tools.parsing import WorkItem
from fabric_tools.status import BatchProgress, status_detail

ITEM_TYPE = "OrgApp"


@dataclass
class OpResult:
    ok: bool
    message: str
    workspace_id: str | None = None
    item_id: str | None = None


def download_org_app(client: FabricClient, item: WorkItem) -> OpResult:
    """Download one remote Org App definition to a local folder."""
    if item.target is None or item.target.item_id is None:
        return OpResult(False, "download requires workspace:artifact target")
    if item.file is None:
        return OpResult(False, "download requires a local --target path")

    target = item.target
    destination = item.file
    try:
        detect_org_app_path(destination)
        definition = get_org_app_definition(client, target.workspace_id, target.item_id)
        written = unpack_definition(definition, destination)
    except (FabricApiError, DefinitionError, OSError) as exc:
        return OpResult(
            False,
            f"download failed {target.label()} -> {destination}: {exc}",
            target.workspace_id,
            target.item_id,
        )
    return OpResult(
        True,
        f"downloaded {target.label()} -> {written}",
        target.workspace_id,
        target.item_id,
    )


def deploy_org_app(
    client: FabricClient,
    item: WorkItem,
    *,
    display_name: str | None = None,
    origin_definition_cache: dict[str, dict[str, Any]] | None = None,
) -> OpResult:
    """Create or overwrite one Org App from a local folder or Fabric origin."""
    if item.target is None:
        return OpResult(False, "deploy requires a --target")
    if item.file is None and item.origin is None:
        return OpResult(False, "deploy requires a local path or remote --origin")
    if item.file is not None and item.origin is not None:
        return OpResult(False, "deploy cannot mix a local path and a remote --origin")

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
                    metadata = client.get_item(
                        item.origin.workspace_id, item.origin.item_id
                    )
                    name = str(
                        metadata.get("displayName") or metadata.get("name") or "Org App"
                    )
                except FabricApiError:
                    name = "Org App"
        try:
            created = create_org_app(
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
            f"(name='{name}')",
            target.workspace_id,
            item_id or None,
        )

    assert target.item_id is not None
    try:
        update_org_app_definition(
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


def delete_org_app(client: FabricClient, item: WorkItem) -> OpResult:
    """Soft-delete one remote Org App."""
    if item.target is None or item.target.item_id is None:
        return OpResult(False, "delete requires workspace:artifact target")
    target = item.target
    try:
        client.request(
            "DELETE",
            f"/workspaces/{target.workspace_id}/orgApps/{target.item_id}",
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


def get_org_app_definition(
    client: FabricClient,
    workspace_id: str,
    org_app_id: str,
) -> dict[str, Any]:
    """Fetch and extract an Org App definition."""
    result = client.request(
        "POST",
        f"/workspaces/{workspace_id}/orgApps/{org_app_id}/getDefinition",
    )
    return _extract_definition(result)


def create_org_app(
    client: FabricClient,
    workspace_id: str,
    *,
    display_name: str,
    definition: dict[str, Any],
) -> dict[str, Any]:
    """Create an Org App through the generic Fabric items endpoint."""
    result = client.request(
        "POST",
        f"/workspaces/{workspace_id}/items",
        json={
            "displayName": display_name,
            "type": ITEM_TYPE,
            "definition": definition,
        },
    )
    if not isinstance(result, dict):
        raise FabricApiError("Create Org App returned an empty response")
    return result


def update_org_app_definition(
    client: FabricClient,
    workspace_id: str,
    org_app_id: str,
    *,
    definition: dict[str, Any],
    update_metadata: bool = False,
) -> Any:
    """Update an existing Org App definition."""
    params = {"updateMetadata": "true"} if update_metadata else None
    return client.request(
        "POST",
        f"/workspaces/{workspace_id}/orgApps/{org_app_id}/updateDefinition",
        params=params,
        json={"definition": definition},
    )


def run_download_batch(client: FabricClient, items: list[WorkItem]) -> list[OpResult]:
    progress = BatchProgress(total=len(items))
    results: list[OpResult] = []
    for item in items:
        target = item.target
        item_id = target.item_id if target is not None else None
        progress.advance(status_detail("Downloading", "Org App", item_id))
        results.append(download_org_app(client, item))
    return results


def run_deploy_batch(
    client: FabricClient,
    items: list[WorkItem],
    *,
    display_names: list[str] | None = None,
) -> list[OpResult]:
    progress = BatchProgress(total=len(items))
    results: list[OpResult] = []
    origin_cache: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items):
        name = (
            display_names[index]
            if display_names and index < len(display_names)
            else None
        )
        target = item.target
        action = "Creating" if target is not None and target.is_create else "Deploying"
        item_id = (
            target.item_id if target is not None and not target.is_create else None
        )
        progress.advance(status_detail(action, "Org App", item_id))
        results.append(
            deploy_org_app(
                client,
                item,
                display_name=name,
                origin_definition_cache=origin_cache,
            )
        )
    return results


def run_delete_batch(client: FabricClient, items: list[WorkItem]) -> list[OpResult]:
    progress = BatchProgress(total=len(items))
    results: list[OpResult] = []
    for item in items:
        target = item.target
        item_id = target.item_id if target is not None else None
        progress.advance(status_detail("Deleting", "Org App", item_id))
        results.append(delete_org_app(client, item))
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
    definition = get_org_app_definition(client, origin.workspace_id, origin.item_id)
    if origin_definition_cache is not None:
        origin_definition_cache[cache_key] = definition
    return definition, label


def _extract_definition(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise FabricApiError("Org App definition response was empty")
    if "definition" in result and isinstance(result["definition"], dict):
        return result["definition"]
    if "parts" in result:
        return result
    raise FabricApiError(
        "Org App definition response missing 'definition'",
        details=result,
    )

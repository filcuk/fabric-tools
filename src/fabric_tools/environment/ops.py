"""Microsoft Fabric Environment download, deploy, and delete operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fabric_tools.client import FabricApiError, FabricClient
from fabric_tools.environment.definition import (
    DefinitionError,
    definition_has_platform,
    detect_environment_path,
    display_name_from_path,
    pack_definition,
    unpack_definition,
)
from fabric_tools.parsing import WorkItem
from fabric_tools.status import BatchProgress, status_detail

ITEM_TYPE = "Environment"


@dataclass
class OpResult:
    ok: bool
    message: str
    workspace_id: str | None = None
    item_id: str | None = None


def download_environment(client: FabricClient, item: WorkItem) -> OpResult:
    """Download one remote Environment definition to a local folder."""
    if item.target is None or item.target.item_id is None:
        return OpResult(False, "download requires workspace:artifact target")
    if item.file is None:
        return OpResult(False, "download requires a local --target path")
    target = item.target
    try:
        detect_environment_path(item.file)
        definition = get_environment_definition(
            client, target.workspace_id, target.item_id
        )
        written = unpack_definition(definition, item.file)
    except (FabricApiError, DefinitionError, OSError) as exc:
        return OpResult(
            False,
            f"download failed {target.label()} -> {item.file}: {exc}",
            target.workspace_id,
            target.item_id,
        )
    return OpResult(
        True,
        f"downloaded {target.label()} -> {written}",
        target.workspace_id,
        target.item_id,
    )


def deploy_environment(
    client: FabricClient,
    item: WorkItem,
    *,
    display_name: str | None = None,
    origin_definition_cache: dict[str, dict[str, Any]] | None = None,
) -> OpResult:
    """Create or overwrite one Environment from a local folder or origin."""
    if item.target is None:
        return OpResult(False, "deploy requires a --target")
    if item.file is None and item.origin is None:
        return OpResult(False, "deploy requires a local path or remote --origin")
    if item.file is not None and item.origin is not None:
        return OpResult(False, "deploy cannot mix a local path and a remote --origin")
    target = item.target
    try:
        definition, source_label = _resolve_source_definition(
            client, item, origin_definition_cache=origin_definition_cache
        )
    except (FabricApiError, DefinitionError) as exc:
        return OpResult(
            False, f"deploy source failed: {exc}", target.workspace_id, target.item_id
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
                        metadata.get("displayName")
                        or metadata.get("name")
                        or "Environment"
                    )
                except FabricApiError:
                    name = "Environment"
        try:
            created = create_environment(
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
        update_environment_definition(
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


def delete_environment(client: FabricClient, item: WorkItem) -> OpResult:
    """Soft-delete one remote Environment."""
    if item.target is None or item.target.item_id is None:
        return OpResult(False, "delete requires workspace:artifact target")
    target = item.target
    try:
        client.request(
            "DELETE",
            f"/workspaces/{target.workspace_id}/environments/{target.item_id}",
        )
    except FabricApiError as exc:
        return OpResult(
            False,
            f"delete failed {target.label()}: {exc}",
            target.workspace_id,
            target.item_id,
        )
    return OpResult(
        True, f"deleted {target.label()}", target.workspace_id, target.item_id
    )


def get_environment_definition(
    client: FabricClient, workspace_id: str, environment_id: str
) -> dict[str, Any]:
    """Fetch and extract an Environment definition."""
    result = client.request(
        "POST",
        f"/workspaces/{workspace_id}/environments/{environment_id}/getDefinition",
    )
    return _extract_definition(result)


def create_environment(
    client: FabricClient,
    workspace_id: str,
    *,
    display_name: str,
    definition: dict[str, Any],
) -> dict[str, Any]:
    """Create an Environment through the generic Fabric items endpoint."""
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
        raise FabricApiError("Create Environment returned an empty response")
    return result


def update_environment_definition(
    client: FabricClient,
    workspace_id: str,
    environment_id: str,
    *,
    definition: dict[str, Any],
    update_metadata: bool = False,
) -> Any:
    """Update an existing Environment definition."""
    params = {"updateMetadata": "true"} if update_metadata else None
    return client.request(
        "POST",
        f"/workspaces/{workspace_id}/environments/{environment_id}/updateDefinition",
        params=params,
        json={"definition": definition},
    )


def run_download_batch(client: FabricClient, items: list[WorkItem]) -> list[OpResult]:
    progress = BatchProgress(total=len(items))
    results: list[OpResult] = []
    for item in items:
        target = item.target
        progress.advance(
            status_detail(
                "environment",
                "downloading",
                target.item_id if target is not None else None,
            )
        )
        results.append(download_environment(client, item))
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
        action = "creating" if target is not None and target.is_create else "deploying"
        item_id = (
            target.item_id if target is not None and not target.is_create else None
        )
        progress.advance(status_detail("environment", action, item_id))
        results.append(
            deploy_environment(
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
        progress.advance(
            status_detail(
                "environment",
                "deleting",
                target.item_id if target is not None else None,
            )
        )
        results.append(delete_environment(client, item))
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
    label = f"origin {item.origin.label()}"
    cache_key = item.origin.label()
    if origin_definition_cache is not None and cache_key in origin_definition_cache:
        return origin_definition_cache[cache_key], label
    definition = get_environment_definition(
        client, item.origin.workspace_id, item.origin.item_id
    )
    if origin_definition_cache is not None:
        origin_definition_cache[cache_key] = definition
    return definition, label


def _extract_definition(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise FabricApiError("Environment definition response was empty")
    if "definition" in result and isinstance(result["definition"], dict):
        return result["definition"]
    if "parts" in result:
        return result
    raise FabricApiError(
        "Environment definition response missing 'definition'", details=result
    )

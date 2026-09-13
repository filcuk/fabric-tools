"""DataPipeline download / create / overwrite / delete operations (Fabric API)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fabric_tools.client import FabricApiError, FabricClient
from fabric_tools.guid_map import GuidMapError, apply_guid_map_to_definition
from fabric_tools.parsing import WorkItem
from fabric_tools.pipeline.definition import (
    DefinitionError,
    definition_has_platform,
    definition_with_remote_schedules,
    definition_without_schedules,
    detect_pipeline_path,
    display_name_from_path,
    pack_definition,
    unpack_definition,
)
from fabric_tools.status import BatchProgress, status_detail

ITEM_TYPE = "DataPipeline"


@dataclass
class OpResult:
    ok: bool
    message: str
    workspace_id: str | None = None
    item_id: str | None = None


def download_pipeline(
    client: FabricClient,
    item: WorkItem,
    *,
    include_schedules: bool = False,
) -> OpResult:
    """Download one remote DataPipeline definition to a local folder."""
    if item.target is None or item.target.item_id is None:
        return OpResult(False, "download requires workspace:artifact target")
    if item.file is None:
        return OpResult(False, "download requires a local --file path")

    target = item.target
    dest = item.file
    try:
        detect_pipeline_path(dest)
        definition = get_pipeline_definition(
            client, target.workspace_id, target.item_id
        )
        written = unpack_definition(
            definition, dest, include_schedules=include_schedules
        )
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


def deploy_pipeline(
    client: FabricClient,
    item: WorkItem,
    *,
    display_name: str | None = None,
    origin_definition_cache: dict[str, dict[str, Any]] | None = None,
    include_schedules: bool = False,
    guid_map: dict[str, str] | None = None,
) -> OpResult:
    """Create or overwrite one DataPipeline from a local folder or Fabric origin.

    By default omits source ``.schedules``. On overwrite, reattaches the target's
    existing ``.schedules`` so remote schedules stay untouched. Pass
    ``include_schedules=True`` to sync schedules from the source instead.

    When *guid_map* is set, source→target GUID tokens in definition text parts
    are rewritten in memory before create/update (local folders are not edited).
    """
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
            include_schedules=include_schedules,
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
                name = display_name_from_path(item.file)
            else:
                assert item.origin is not None and item.origin.item_id is not None
                try:
                    meta = client.get_item(
                        item.origin.workspace_id, item.origin.item_id
                    )
                    name = str(
                        meta.get("displayName") or meta.get("name") or "DataPipeline"
                    )
                except FabricApiError:
                    name = "DataPipeline"
        try:
            created = create_pipeline(
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
    preserved = False
    try:
        if not include_schedules:
            remote_definition = get_pipeline_definition(
                client, target.workspace_id, target.item_id
            )
            definition, preserved = definition_with_remote_schedules(
                definition, remote_definition
            )
        update_pipeline_definition(
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
    suffix = " (preserved remote schedules)" if preserved else ""
    return OpResult(
        True,
        f"updated {target.label()} from {source_label}{suffix}{remap_suffix}",
        target.workspace_id,
        target.item_id,
    )


def delete_pipeline(client: FabricClient, item: WorkItem) -> OpResult:
    """Soft-delete one remote DataPipeline."""
    if item.target is None or item.target.item_id is None:
        return OpResult(False, "delete requires workspace:artifact target")

    target = item.target
    try:
        client.request(
            "DELETE",
            f"/workspaces/{target.workspace_id}/dataPipelines/{target.item_id}",
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


def get_pipeline_definition(
    client: FabricClient,
    workspace_id: str,
    pipeline_id: str,
) -> dict[str, Any]:
    """POST getDefinition and return the definition object (parts)."""
    result = client.request(
        "POST",
        f"/workspaces/{workspace_id}/dataPipelines/{pipeline_id}/getDefinition",
    )
    return _extract_definition(result)


def create_pipeline(
    client: FabricClient,
    workspace_id: str,
    *,
    display_name: str,
    definition: dict[str, Any],
) -> dict[str, Any]:
    """POST /items to create a DataPipeline with definition."""
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
        raise FabricApiError("Create pipeline returned an empty response")
    return result


def update_pipeline_definition(
    client: FabricClient,
    workspace_id: str,
    pipeline_id: str,
    *,
    definition: dict[str, Any],
    update_metadata: bool = False,
) -> Any:
    """POST updateDefinition for an existing DataPipeline."""
    params = {"updateMetadata": "true"} if update_metadata else None
    return client.request(
        "POST",
        f"/workspaces/{workspace_id}/dataPipelines/{pipeline_id}/updateDefinition",
        params=params,
        json={"definition": definition},
    )


def run_download_batch(
    client: FabricClient,
    items: list[WorkItem],
    *,
    include_schedules: bool = False,
) -> list[OpResult]:
    progress = BatchProgress(total=len(items))
    results: list[OpResult] = []
    for item in items:
        target = item.target
        item_id = target.item_id if target is not None else None
        progress.advance(status_detail("Downloading", "pipeline", item_id))
        results.append(
            download_pipeline(client, item, include_schedules=include_schedules)
        )
    return results


def run_deploy_batch(
    client: FabricClient,
    items: list[WorkItem],
    *,
    display_names: list[str] | None = None,
    include_schedules: bool = False,
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
            progress.advance(status_detail("Creating", "pipeline"))
        elif target is not None:
            progress.advance(status_detail("Deploying", "pipeline", target.item_id))
        else:
            progress.advance(status_detail("Deploying", "pipeline"))
        results.append(
            deploy_pipeline(
                client,
                item,
                display_name=name,
                origin_definition_cache=origin_cache,
                include_schedules=include_schedules,
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
        progress.advance(status_detail("Deleting", "pipeline", item_id))
        results.append(delete_pipeline(client, item))
    return results


def _resolve_source_definition(
    client: FabricClient,
    item: WorkItem,
    *,
    origin_definition_cache: dict[str, dict[str, Any]] | None,
    include_schedules: bool = False,
) -> tuple[dict[str, Any], str]:
    if item.file is not None:
        return (
            pack_definition(item.file, include_schedules=include_schedules),
            str(item.file),
        )

    assert item.origin is not None and item.origin.item_id is not None
    origin = item.origin
    label = f"origin {origin.label()}"
    cache_key = origin.label()
    if origin_definition_cache is not None and cache_key in origin_definition_cache:
        definition = origin_definition_cache[cache_key]
    else:
        definition = get_pipeline_definition(
            client, origin.workspace_id, origin.item_id
        )
        if origin_definition_cache is not None:
            origin_definition_cache[cache_key] = definition
    if not include_schedules:
        definition = definition_without_schedules(definition)
    return definition, label


def _extract_definition(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise FabricApiError("Pipeline definition response was empty")
    if "definition" in result and isinstance(result["definition"], dict):
        return result["definition"]
    if "parts" in result:
        return result
    raise FabricApiError(
        "Pipeline definition response missing 'definition'",
        details=result,
    )

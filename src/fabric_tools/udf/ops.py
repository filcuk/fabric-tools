"""User Data Function download / create / overwrite (deploy) / delete operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fabric_tools.auth import service_principal_configured
from fabric_tools.client import FabricApiError, FabricClient
from fabric_tools.guid_map import GuidMapError, apply_guid_map_to_definition
from fabric_tools.parsing import WorkItem
from fabric_tools.status import BatchProgress, status_detail
from fabric_tools.udf.definition import (
    DefinitionError,
    definition_has_platform,
    definition_json_from_definition,
    detect_udf_folder,
    display_name_from_path,
    merge_remote_connections,
    pack_definition,
    replace_definition_json_part,
    strip_connected_data_sources,
    unpack_definition,
)


class UdfAuthError(RuntimeError):
    """Raised when service-principal auth is configured for UDF APIs."""


def check_udf_user_auth() -> None:
    """Fail fast: Fabric User Data Function APIs do not support service principals."""
    if service_principal_configured():
        raise UdfAuthError(
            "User Data Function APIs require interactive user authentication; "
            "service principal (AZURE_TENANT_ID / AZURE_CLIENT_ID / "
            "AZURE_CLIENT_SECRET) is not supported. Unset those variables and retry."
        )


@dataclass
class OpResult:
    ok: bool
    message: str
    workspace_id: str | None = None
    item_id: str | None = None


def download_udf(client: FabricClient, item: WorkItem) -> OpResult:
    """Download one remote User Data Function definition to a local folder."""
    if item.target is None or item.target.item_id is None:
        return OpResult(False, "download requires workspace:artifact target")
    if item.file is None:
        return OpResult(False, "download requires a local --target path")

    target = item.target
    dest = item.file
    try:
        detect_udf_folder(dest)
    except DefinitionError as exc:
        return OpResult(False, str(exc), target.workspace_id, target.item_id)

    try:
        definition = get_udf_definition(client, target.workspace_id, target.item_id)
        written = unpack_definition(definition, dest)
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


def deploy_udf(
    client: FabricClient,
    item: WorkItem,
    *,
    display_name: str | None = None,
    origin_definition_cache: dict[str, dict[str, Any]] | None = None,
    guid_map: dict[str, str] | None = None,
) -> OpResult:
    """Create or overwrite one User Data Function from a local path or Fabric origin.

    When *guid_map* is set, source→target GUID tokens in definition text parts
    are rewritten in memory before create/update. On overwrite,
    ``connectedDataSources`` preserve still runs after remap.
    """
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
                    meta = get_udf_item(
                        client, item.origin.workspace_id, item.origin.item_id
                    )
                    name = str(
                        meta.get("displayName")
                        or meta.get("name")
                        or "UserDataFunction"
                    )
                except FabricApiError:
                    name = "UserDataFunction"
        try:
            created = create_udf(
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
        if item.origin is not None:
            origin_json = definition_json_from_definition(definition)
            stripped = strip_connected_data_sources(origin_json)
            remote_definition = get_udf_definition(
                client, target.workspace_id, target.item_id
            )
            remote_json = definition_json_from_definition(remote_definition)
            merged_json, preserved = merge_remote_connections(stripped, remote_json)
            definition = replace_definition_json_part(definition, merged_json)
        else:
            source_json = definition_json_from_definition(definition)
            remote_definition = get_udf_definition(
                client, target.workspace_id, target.item_id
            )
            remote_json = definition_json_from_definition(remote_definition)
            merged_json, preserved = merge_remote_connections(source_json, remote_json)
            if preserved:
                definition = replace_definition_json_part(definition, merged_json)

        update_udf_definition(
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
    suffix = " (preserved remote connectedDataSources)" if preserved else ""
    return OpResult(
        True,
        f"updated {target.label()} from {source_label}{suffix}{remap_suffix}",
        target.workspace_id,
        target.item_id,
    )


def delete_udf(client: FabricClient, item: WorkItem) -> OpResult:
    """Soft-delete one remote User Data Function."""
    if item.target is None or item.target.item_id is None:
        return OpResult(False, "delete requires workspace:artifact target")

    target = item.target
    try:
        client.request(
            "DELETE",
            f"/workspaces/{target.workspace_id}/userDataFunctions/{target.item_id}",
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


def get_udf_definition(
    client: FabricClient,
    workspace_id: str,
    udf_id: str,
) -> dict[str, Any]:
    """POST getDefinition and return the definition object (parts)."""
    result = client.request(
        "POST",
        f"/workspaces/{workspace_id}/userDataFunctions/{udf_id}/getDefinition",
    )
    return _extract_definition(result)


def get_udf_item(
    client: FabricClient,
    workspace_id: str,
    udf_id: str,
) -> dict[str, Any]:
    """GET properties for a User Data Function item."""
    result = client.request(
        "GET",
        f"/workspaces/{workspace_id}/userDataFunctions/{udf_id}",
    )
    if not isinstance(result, dict):
        raise FabricApiError("Get User Data Function returned an empty response")
    return result


def create_udf(
    client: FabricClient,
    workspace_id: str,
    *,
    display_name: str,
    definition: dict[str, Any],
) -> dict[str, Any]:
    """POST /userDataFunctions to create an item with definition."""
    payload = {
        "displayName": display_name,
        "definition": definition,
    }
    result = client.request(
        "POST",
        f"/workspaces/{workspace_id}/userDataFunctions",
        json=payload,
    )
    if not isinstance(result, dict):
        raise FabricApiError("Create User Data Function returned an empty response")
    return result


def update_udf_definition(
    client: FabricClient,
    workspace_id: str,
    udf_id: str,
    *,
    definition: dict[str, Any],
    update_metadata: bool = False,
) -> Any:
    """POST updateDefinition for an existing User Data Function."""
    params = {"updateMetadata": "true"} if update_metadata else None
    return client.request(
        "POST",
        f"/workspaces/{workspace_id}/userDataFunctions/{udf_id}/updateDefinition",
        params=params,
        json={"definition": definition},
    )


def run_download_batch(client: FabricClient, items: list[WorkItem]) -> list[OpResult]:
    progress = BatchProgress(total=len(items))
    results: list[OpResult] = []
    for item in items:
        target = item.target
        item_id = target.item_id if target is not None else None
        progress.advance(status_detail("udf", "downloading", item_id))
        results.append(download_udf(client, item))
    return results


def run_deploy_batch(
    client: FabricClient,
    items: list[WorkItem],
    *,
    display_names: list[str] | None = None,
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
            progress.advance(status_detail("udf", "creating"))
        elif target is not None:
            progress.advance(
                status_detail("udf", "deploying", target.item_id)
            )
        else:
            progress.advance(status_detail("udf", "deploying"))
        results.append(
            deploy_udf(
                client,
                item,
                display_name=name,
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
        progress.advance(status_detail("udf", "deleting", item_id))
        results.append(delete_udf(client, item))
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

    definition = get_udf_definition(client, origin.workspace_id, origin.item_id)
    if origin_definition_cache is not None:
        origin_definition_cache[cache_key] = definition
    return definition, label


def _extract_definition(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise FabricApiError("User Data Function definition response was empty")
    if "definition" in result and isinstance(result["definition"], dict):
        return result["definition"]
    if "parts" in result:
        return result
    raise FabricApiError(
        "User Data Function definition response missing 'definition'",
        details=result,
    )

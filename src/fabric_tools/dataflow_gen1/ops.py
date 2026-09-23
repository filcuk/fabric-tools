"""Dataflow Gen1 download / create / delete operations (Power BI API)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fabric_tools.confirm import status_gen1_label
from fabric_tools.dataflow_gen1.definition import (
    DefinitionError,
    display_name_from_model,
    load_model,
    model_to_bytes,
    prepare_model_for_import,
    validate_model_dict,
    write_model,
)
from fabric_tools.display import format_guid, format_item_ref, format_local_path
from fabric_tools.parsing import WorkItem
from fabric_tools.powerbi_client import (
    PowerBiApiError,
    PowerBiClient,
    dataflow_id_from_import,
)
from fabric_tools.status import BatchProgress, status_detail


@dataclass
class OpResult:
    ok: bool
    message: str
    workspace_id: str | None = None
    item_id: str | None = None


def download_dataflow(client: PowerBiClient, item: WorkItem) -> OpResult:
    """Download one remote Gen1 dataflow model.json to a local path."""
    if item.target is None or item.target.item_id is None:
        return OpResult(False, "download requires workspace:artifact target")
    if item.file is None:
        return OpResult(False, "download requires a local --target path")

    target = item.target
    dest = item.file
    ref = format_item_ref(None, target.item_id)
    try:
        model = client.get_dataflow_definition(target.workspace_id, target.item_id)
        model = validate_model_dict(model, label=ref)
        ref = format_item_ref(display_name_from_model(model), target.item_id)
        written = write_model(model, dest)
    except (PowerBiApiError, DefinitionError, OSError) as exc:
        return OpResult(
            False,
            f"download failed {ref} -> {format_local_path(dest)}: {exc}",
            target.workspace_id,
            target.item_id,
        )

    return OpResult(
        True,
        f"downloaded {ref} -> {format_local_path(written)}",
        target.workspace_id,
        target.item_id,
    )


def deploy_dataflow(
    client: PowerBiClient,
    item: WorkItem,
    *,
    display_name: str | None = None,
    origin_model_cache: dict[str, dict[str, Any]] | None = None,
) -> OpResult:
    """Create one Gen1 dataflow from a local model.json or Power BI origin.

    Overwrite (``workspaceId:artifactId`` targets) is not supported.
    """
    if item.target is None:
        return OpResult(False, "deploy requires a --target")
    if item.file is None and item.origin is None:
        return OpResult(False, "deploy requires a local path or remote --origin")
    if item.file is not None and item.origin is not None:
        return OpResult(False, "deploy cannot mix a local path and a remote --origin")

    target = item.target
    if not target.is_create:
        return OpResult(
            False,
            "dataflow-gen1 deploy supports create only "
            f"(got artifact target {format_item_ref(None, target.item_id)}; "
            "use delete + create, "
            "or fabric-tools dataflow for Gen2 overwrite)",
            target.workspace_id,
            target.item_id,
        )

    try:
        model, source_label = _resolve_source_model(
            client,
            item,
            origin_model_cache=origin_model_cache,
        )
        prepared = prepare_model_for_import(model, display_name=display_name)
        name = display_name_from_model(prepared)
        import_payload = client.create_dataflow_from_model(
            target.workspace_id,
            model_to_bytes(prepared),
            name_conflict="Abort",
        )
    except (PowerBiApiError, DefinitionError) as exc:
        return OpResult(
            False,
            f"create failed in workspace {format_guid(target.workspace_id)}: {exc}",
            target.workspace_id,
        )

    item_id = dataflow_id_from_import(import_payload)
    if item_id is None:
        item_id = _resolve_created_id_by_name(client, target.workspace_id, name)

    if not item_id:
        return OpResult(
            True,
            f"created {name} in workspace {format_guid(target.workspace_id)} "
            f"from {source_label} (id unknown — check workspace)",
            target.workspace_id,
            None,
        )

    return OpResult(
        True,
        f"created {format_item_ref(name, item_id)} from {source_label}",
        target.workspace_id,
        item_id,
    )


def delete_dataflow(
    client: PowerBiClient, item: WorkItem, *, name: str | None = None
) -> OpResult:
    """Delete one remote Gen1 dataflow."""
    if item.target is None or item.target.item_id is None:
        return OpResult(False, "delete requires workspace:artifact target")

    target = item.target
    ref = format_item_ref(name, target.item_id)
    try:
        client.delete_dataflow(target.workspace_id, target.item_id)
    except PowerBiApiError as exc:
        return OpResult(
            False,
            f"delete failed {ref}: {exc}",
            target.workspace_id,
            target.item_id,
        )
    return OpResult(
        True,
        f"deleted {ref}",
        target.workspace_id,
        target.item_id,
    )


def run_download_batch(client: PowerBiClient, items: list[WorkItem]) -> list[OpResult]:
    progress = BatchProgress(total=len(items))
    results: list[OpResult] = []
    for item in items:
        progress.advance(
            status_detail(
                "dataflow-gen1",
                "downloading",
                status_gen1_label(client, item.target),
            )
        )
        results.append(download_dataflow(client, item))
    return results


def run_deploy_batch(
    client: PowerBiClient,
    items: list[WorkItem],
    *,
    display_names: list[str] | None = None,
) -> list[OpResult]:
    progress = BatchProgress(total=len(items))
    results: list[OpResult] = []
    origin_cache: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items):
        name = None
        if display_names and index < len(display_names):
            name = display_names[index]
        progress.advance(
            status_detail(
                "dataflow-gen1",
                "creating",
                status_gen1_label(client, item.target, fallback=name),
            )
        )
        results.append(
            deploy_dataflow(
                client,
                item,
                display_name=name,
                origin_model_cache=origin_cache,
            )
        )
    return results


def run_delete_batch(client: PowerBiClient, items: list[WorkItem]) -> list[OpResult]:
    progress = BatchProgress(total=len(items))
    results: list[OpResult] = []
    for item in items:
        label = status_gen1_label(client, item.target)
        progress.advance(status_detail("dataflow-gen1", "deleting", label))
        results.append(delete_dataflow(client, item, name=label))
    return results


def _resolve_source_model(
    client: PowerBiClient,
    item: WorkItem,
    *,
    origin_model_cache: dict[str, dict[str, Any]] | None,
) -> tuple[dict[str, Any], str]:
    if item.file is not None:
        return load_model(item.file), format_local_path(item.file)

    assert item.origin is not None and item.origin.item_id is not None
    origin = item.origin
    cache_key = origin.label()
    if origin_model_cache is not None and cache_key in origin_model_cache:
        model = origin_model_cache[cache_key]
    else:
        model = client.get_dataflow_definition(origin.workspace_id, origin.item_id)
        model = validate_model_dict(
            model, label=f"origin {format_item_ref(None, origin.item_id)}"
        )
        if origin_model_cache is not None:
            origin_model_cache[cache_key] = model
    label = f"origin {format_item_ref(display_name_from_model(model), origin.item_id)}"
    return model, label


def _resolve_created_id_by_name(
    client: PowerBiClient,
    workspace_id: str,
    name: str,
) -> str | None:
    try:
        matches = [
            item
            for item in client.list_dataflows(workspace_id)
            if item.get("name") == name
        ]
    except PowerBiApiError:
        return None
    if len(matches) != 1:
        return None
    object_id = matches[0].get("objectId") or matches[0].get("id")
    return str(object_id) if object_id else None

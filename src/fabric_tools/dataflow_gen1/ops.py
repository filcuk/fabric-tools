"""Dataflow Gen1 download / create / delete operations (Power BI API)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fabric_tools.dataflow_gen1.definition import (
    DefinitionError,
    display_name_from_model,
    load_model,
    model_to_bytes,
    prepare_model_for_import,
    validate_model_dict,
    write_model,
)
from fabric_tools.parsing import WorkItem
from fabric_tools.powerbi_client import (
    PowerBiApiError,
    PowerBiClient,
    dataflow_id_from_import,
)
from fabric_tools.status import BatchProgress, status_detail
from fabric_tools.status import update as update_status


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
    try:
        model = client.get_dataflow_definition(target.workspace_id, target.item_id)
        model = validate_model_dict(model, label=target.label())
        written = write_model(model, dest)
    except (PowerBiApiError, DefinitionError, OSError) as exc:
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
            f"(got artifact target {target.label()}; use delete + create, "
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
            f"create failed in {target.workspace_id}: {exc}",
            target.workspace_id,
        )

    item_id = dataflow_id_from_import(import_payload)
    if item_id is None:
        item_id = _resolve_created_id_by_name(client, target.workspace_id, name)

    if not item_id:
        return OpResult(
            True,
            f"created dataflow in {target.workspace_id} from {source_label} "
            f"(name='{name}'; id unknown — check workspace)",
            target.workspace_id,
            None,
        )

    return OpResult(
        True,
        f"created {target.workspace_id}:{item_id} from {source_label} (name='{name}')",
        target.workspace_id,
        item_id,
    )


def delete_dataflow(client: PowerBiClient, item: WorkItem) -> OpResult:
    """Delete one remote Gen1 dataflow."""
    if item.target is None or item.target.item_id is None:
        return OpResult(False, "delete requires workspace:artifact target")

    target = item.target
    try:
        client.delete_dataflow(target.workspace_id, target.item_id)
    except PowerBiApiError as exc:
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


def run_download_batch(client: PowerBiClient, items: list[WorkItem]) -> list[OpResult]:
    results: list[OpResult] = []
    for item in items:
        target = item.target
        dest = item.file
        if target is not None and dest is not None:
            update_status(f"Downloading {target.label()} -> {dest}...")
        else:
            update_status("Downloading dataflow-gen1...")
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
        progress.advance(status_detail("Creating", "dataflow-gen1"))
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
        target = item.target
        item_id = target.item_id if target is not None else None
        progress.advance(status_detail("Deleting", "dataflow-gen1", item_id))
        results.append(delete_dataflow(client, item))
    return results


def _resolve_source_model(
    client: PowerBiClient,
    item: WorkItem,
    *,
    origin_model_cache: dict[str, dict[str, Any]] | None,
) -> tuple[dict[str, Any], str]:
    if item.file is not None:
        return load_model(item.file), str(item.file)

    assert item.origin is not None and item.origin.item_id is not None
    origin = item.origin
    label = f"origin {origin.label()}"
    cache_key = origin.label()
    if origin_model_cache is not None and cache_key in origin_model_cache:
        return origin_model_cache[cache_key], label

    model = client.get_dataflow_definition(origin.workspace_id, origin.item_id)
    model = validate_model_dict(model, label=label)
    if origin_model_cache is not None:
        origin_model_cache[cache_key] = model
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

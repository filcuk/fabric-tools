"""Paginated report download / create / overwrite / delete (Power BI API)."""

from __future__ import annotations

from dataclasses import dataclass

from fabric_tools.confirm import status_paginated_label
from fabric_tools.display import format_guid, format_item_ref, format_local_path
from fabric_tools.paginated_report.definition import (
    DefinitionError,
    display_name_from_path,
    display_name_from_report,
    ensure_paginated_report,
    load_rdl,
    validate_rdl_bytes,
    write_rdl,
)
from fabric_tools.parsing import WorkItem
from fabric_tools.powerbi_client import (
    PowerBiApiError,
    PowerBiClient,
    report_id_from_import,
)
from fabric_tools.status import BatchProgress, status_detail


@dataclass
class OpResult:
    ok: bool
    message: str
    workspace_id: str | None = None
    item_id: str | None = None


def download_paginated_report(client: PowerBiClient, item: WorkItem) -> OpResult:
    """Download one remote paginated report RDL to a local path."""
    if item.target is None or item.target.item_id is None:
        return OpResult(False, "download requires workspace:artifact target")
    if item.file is None:
        return OpResult(False, "download requires a local --target path")

    target = item.target
    dest = item.file
    ref = format_item_ref(None, target.item_id)
    try:
        meta = client.get_report(target.workspace_id, target.item_id)
        ensure_paginated_report(meta, label=ref)
        ref = format_item_ref(display_name_from_report(meta), target.item_id)
        rdl = client.export_report_definition(target.workspace_id, target.item_id)
        rdl = validate_rdl_bytes(rdl, label=ref)
        written = write_rdl(rdl, dest)
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


def deploy_paginated_report(
    client: PowerBiClient,
    item: WorkItem,
    *,
    display_name: str | None = None,
    origin_rdl_cache: dict[str, bytes] | None = None,
) -> OpResult:
    """Create or overwrite one paginated report from a local ``.rdl`` or origin."""
    if item.target is None:
        return OpResult(False, "deploy requires a --target")
    if item.file is None and item.origin is None:
        return OpResult(False, "deploy requires a local path or remote --origin")
    if item.file is not None and item.origin is not None:
        return OpResult(False, "deploy cannot mix a local path and a remote --origin")

    target = item.target
    try:
        rdl, source_label = _resolve_source_rdl(
            client,
            item,
            origin_rdl_cache=origin_rdl_cache,
        )
        if target.is_create:
            return _deploy_create(
                client,
                item,
                rdl=rdl,
                source_label=source_label,
                display_name=display_name,
            )
        return _deploy_overwrite(
            client,
            item,
            rdl=rdl,
            source_label=source_label,
            display_name=display_name,
        )
    except (PowerBiApiError, DefinitionError) as exc:
        return OpResult(
            False,
            f"deploy failed {format_item_ref(None, target.item_id)}: {exc}",
            target.workspace_id,
            target.item_id,
        )


def delete_paginated_report(client: PowerBiClient, item: WorkItem) -> OpResult:
    """Delete one remote paginated report."""
    if item.target is None or item.target.item_id is None:
        return OpResult(False, "delete requires workspace:artifact target")

    target = item.target
    ref = format_item_ref(None, target.item_id)
    try:
        meta = client.get_report(target.workspace_id, target.item_id)
        ensure_paginated_report(meta, label=ref)
        ref = format_item_ref(display_name_from_report(meta), target.item_id)
        client.delete_report(target.workspace_id, target.item_id)
    except (PowerBiApiError, DefinitionError) as exc:
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
                "paginated-report",
                "downloading",
                status_paginated_label(client, item.target),
            )
        )
        results.append(download_paginated_report(client, item))
    return results


def run_deploy_batch(
    client: PowerBiClient,
    items: list[WorkItem],
    *,
    display_names: list[str] | None = None,
) -> list[OpResult]:
    progress = BatchProgress(total=len(items))
    results: list[OpResult] = []
    origin_cache: dict[str, bytes] = {}
    for index, item in enumerate(items):
        name = None
        if display_names and index < len(display_names):
            name = display_names[index]
        target = item.target
        label = status_paginated_label(client, target, fallback=name)
        if target is not None and target.is_create:
            progress.advance(status_detail("paginated-report", "creating", label))
        elif target is not None:
            progress.advance(status_detail("paginated-report", "overwriting", label))
        else:
            progress.advance(status_detail("paginated-report", "deploying", label))
        results.append(
            deploy_paginated_report(
                client,
                item,
                display_name=name,
                origin_rdl_cache=origin_cache,
            )
        )
    return results


def run_delete_batch(client: PowerBiClient, items: list[WorkItem]) -> list[OpResult]:
    progress = BatchProgress(total=len(items))
    results: list[OpResult] = []
    for item in items:
        progress.advance(
            status_detail(
                "paginated-report",
                "deleting",
                status_paginated_label(client, item.target),
            )
        )
        results.append(delete_paginated_report(client, item))
    return results


def _deploy_create(
    client: PowerBiClient,
    item: WorkItem,
    *,
    rdl: bytes,
    source_label: str,
    display_name: str | None,
) -> OpResult:
    assert item.target is not None and item.target.is_create
    target = item.target

    name = display_name.strip() if display_name else None
    if name == "":
        return OpResult(
            False,
            "display name must be non-empty",
            target.workspace_id,
        )
    if not name:
        if item.file is not None:
            name = display_name_from_path(item.file)
        elif item.origin is not None and item.origin.item_id is not None:
            meta = client.get_report(item.origin.workspace_id, item.origin.item_id)
            ensure_paginated_report(
                meta, label=format_item_ref(None, item.origin.item_id)
            )
            name = display_name_from_report(meta)
        else:
            name = "PaginatedReport"

    import_payload = client.import_paginated_report(
        target.workspace_id,
        rdl,
        display_name=name,
        name_conflict="Abort",
    )
    item_id = report_id_from_import(import_payload)
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


def _deploy_overwrite(
    client: PowerBiClient,
    item: WorkItem,
    *,
    rdl: bytes,
    source_label: str,
    display_name: str | None,
) -> OpResult:
    assert item.target is not None and item.target.item_id is not None
    target = item.target

    if display_name:
        return OpResult(
            False,
            "paginated-report overwrite uses the existing remote report name; "
            "do not pass --name",
            target.workspace_id,
            target.item_id,
        )

    meta = client.get_report(target.workspace_id, target.item_id)
    ensure_paginated_report(meta, label=format_item_ref(None, target.item_id))
    name = display_name_from_report(meta)

    import_payload = client.import_paginated_report(
        target.workspace_id,
        rdl,
        display_name=name,
        name_conflict="Overwrite",
    )
    item_id = report_id_from_import(import_payload) or target.item_id

    return OpResult(
        True,
        f"overwrote {format_item_ref(name, item_id)} from {source_label}",
        target.workspace_id,
        item_id,
    )


def _resolve_source_rdl(
    client: PowerBiClient,
    item: WorkItem,
    *,
    origin_rdl_cache: dict[str, bytes] | None,
) -> tuple[bytes, str]:
    if item.file is not None:
        return load_rdl(item.file), format_local_path(item.file)

    assert item.origin is not None and item.origin.item_id is not None
    origin = item.origin
    cache_key = origin.label()
    meta = client.get_report(origin.workspace_id, origin.item_id)
    label = f"origin {format_item_ref(display_name_from_report(meta), origin.item_id)}"
    if origin_rdl_cache is not None and cache_key in origin_rdl_cache:
        return origin_rdl_cache[cache_key], label

    ensure_paginated_report(meta, label=label)
    rdl = client.export_report_definition(origin.workspace_id, origin.item_id)
    rdl = validate_rdl_bytes(rdl, label=label)
    if origin_rdl_cache is not None:
        origin_rdl_cache[cache_key] = rdl
    return rdl, label


def _resolve_created_id_by_name(
    client: PowerBiClient,
    workspace_id: str,
    name: str,
) -> str | None:
    try:
        matches = [
            item
            for item in client.list_reports(workspace_id)
            if item.get("name") == name and item.get("reportType") == "PaginatedReport"
        ]
    except PowerBiApiError:
        return None
    if len(matches) != 1:
        return None
    object_id = matches[0].get("id")
    return str(object_id) if object_id else None

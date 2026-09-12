"""Compare remote paginated reports to local ``.rdl`` files or other remotes."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from fabric_tools.paginated_report.definition import (
    DefinitionError,
    ensure_paginated_report,
    load_rdl,
    rdl_to_diff_text,
    validate_rdl_bytes,
)
from fabric_tools.parsing import Target, WorkItem
from fabric_tools.powerbi_client import PowerBiApiError, PowerBiClient
from fabric_tools.status import update as update_status


@dataclass
class CompareResult:
    ok: bool
    identical: bool
    header: str
    diff_text: str = ""
    error: str | None = None
    messages: list[str] = field(default_factory=list)


def compare_paginated_report(client: PowerBiClient, item: WorkItem) -> CompareResult:
    """Diff target paginated report against a local ``.rdl`` or another remote."""
    if item.target is None or item.target.item_id is None:
        return CompareResult(
            ok=False,
            identical=False,
            header="compare",
            error="compare requires workspace:artifact target",
        )
    if item.file is None and item.origin is None:
        return CompareResult(
            ok=False,
            identical=False,
            header="compare",
            error="compare requires a local --file or --origin",
        )
    if item.file is not None and item.origin is not None:
        return CompareResult(
            ok=False,
            identical=False,
            header="compare",
            error="compare cannot use both --file and --origin",
        )

    if item.origin is not None:
        return _compare_origin_to_target(client, item)
    return _compare_file_to_target(client, item)


def run_compare_batch(
    client: PowerBiClient,
    items: list[WorkItem],
) -> list[CompareResult]:
    results: list[CompareResult] = []
    for item in items:
        if item.target is not None and item.file is not None:
            update_status(f"Comparing {item.target.label()} <-> {item.file}...")
        elif item.target is not None and item.origin is not None:
            update_status(
                f"Comparing {item.target.label()} <-> origin {item.origin.label()}..."
            )
        else:
            update_status("Comparing paginated-report...")
        results.append(compare_paginated_report(client, item))
    return results


def _compare_file_to_target(client: PowerBiClient, item: WorkItem) -> CompareResult:
    assert item.target is not None and item.target.item_id is not None
    assert item.file is not None
    target = item.target
    local_path = item.file

    try:
        local_rdl = load_rdl(local_path)
    except DefinitionError as exc:
        return CompareResult(
            ok=False,
            identical=False,
            header=str(local_path),
            error=str(exc),
        )

    remote_label = _resolve_report_name(client, target)
    workspace_label = _resolve_group_name(client, target.workspace_id)
    header = f"remote {remote_label} in {workspace_label}  vs  local `{local_path}`"

    try:
        remote_rdl = _fetch_paginated_rdl(client, target)
    except (PowerBiApiError, DefinitionError) as exc:
        return CompareResult(
            ok=False,
            identical=False,
            header=header,
            error=f"failed to fetch remote definition: {exc}",
        )

    return _diff_rdl(
        header,
        left_rdl=remote_rdl,
        right_rdl=local_rdl,
        left_label=f"remote:{target.label()}",
        right_label=f"local:{local_path}",
    )


def _compare_origin_to_target(client: PowerBiClient, item: WorkItem) -> CompareResult:
    assert item.target is not None and item.target.item_id is not None
    assert item.origin is not None and item.origin.item_id is not None
    target = item.target
    origin = item.origin

    origin_label = _resolve_report_name(client, origin)
    origin_ws = _resolve_group_name(client, origin.workspace_id)
    target_label = _resolve_report_name(client, target)
    target_ws = _resolve_group_name(client, target.workspace_id)
    header = (
        f"origin {origin_label} in {origin_ws}  vs  "
        f"target {target_label} in {target_ws}"
    )

    try:
        origin_rdl = _fetch_paginated_rdl(client, origin)
        target_rdl = _fetch_paginated_rdl(client, target)
    except (PowerBiApiError, DefinitionError) as exc:
        return CompareResult(
            ok=False,
            identical=False,
            header=header,
            error=f"failed to fetch remote definition: {exc}",
        )

    return _diff_rdl(
        header,
        left_rdl=target_rdl,
        right_rdl=origin_rdl,
        left_label=f"target:{target.label()}",
        right_label=f"origin:{origin.label()}",
    )


def _fetch_paginated_rdl(client: PowerBiClient, target: Target) -> bytes:
    assert target.item_id is not None
    meta = client.get_report(target.workspace_id, target.item_id)
    ensure_paginated_report(meta, label=target.label())
    rdl = client.export_report_definition(target.workspace_id, target.item_id)
    return validate_rdl_bytes(rdl, label=target.label())


def _diff_rdl(
    header: str,
    *,
    left_rdl: bytes,
    right_rdl: bytes,
    left_label: str,
    right_label: str,
) -> CompareResult:
    left_text = rdl_to_diff_text(left_rdl)
    right_text = rdl_to_diff_text(right_rdl)
    if left_text == right_text:
        return CompareResult(ok=True, identical=True, header=header, diff_text="")

    diff = list(
        difflib.unified_diff(
            left_text.splitlines(keepends=True),
            right_text.splitlines(keepends=True),
            fromfile=left_label,
            tofile=right_label,
        )
    )
    return CompareResult(
        ok=True,
        identical=False,
        header=header,
        diff_text="".join(diff),
    )


def _resolve_group_name(client: PowerBiClient, group_id: str) -> str:
    try:
        data = client.get_group(group_id)
    except PowerBiApiError:
        return group_id
    return str(data.get("name") or data.get("displayName") or group_id)


def _resolve_report_name(client: PowerBiClient, target: Target) -> str:
    assert target.item_id is not None
    try:
        data = client.get_report(target.workspace_id, target.item_id)
    except PowerBiApiError:
        return target.item_id
    return str(data.get("name") or target.item_id)

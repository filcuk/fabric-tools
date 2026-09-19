"""Compare remote Dataflow Gen1 models to local files or other remotes."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any

from fabric_tools.dataflow_gen1.definition import (
    DefinitionError,
    load_model,
    model_to_diff_text,
    validate_model_dict,
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
    remote_name: str = "-"
    local_name: str = "-"
    target_ref: str = "-"


def compare_dataflow(client: PowerBiClient, item: WorkItem) -> CompareResult:
    """Diff target Gen1 dataflow against a local model.json or another remote."""
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
            error="compare requires a local path or remote --origin",
            target_ref=item.target.label(),
        )
    if item.file is not None and item.origin is not None:
        return CompareResult(
            ok=False,
            identical=False,
            header="compare",
            error="compare cannot mix a local path and a remote --origin",
            local_name=item.file.name,
            target_ref=item.target.label(),
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
            update_status("Comparing dataflow-gen1...")
        results.append(compare_dataflow(client, item))
    return results


def _compare_file_to_target(client: PowerBiClient, item: WorkItem) -> CompareResult:
    assert item.target is not None and item.target.item_id is not None
    assert item.file is not None
    target = item.target
    local_path = item.file
    local_name = local_path.name
    target_ref = target.label()

    try:
        local_model = load_model(local_path)
    except DefinitionError as exc:
        return CompareResult(
            ok=False,
            identical=False,
            header=str(local_path),
            error=str(exc),
            local_name=local_name,
            target_ref=target_ref,
        )

    remote_name = _resolve_dataflow_name(client, target)
    workspace_label = _resolve_group_name(client, target.workspace_id)
    header = f"remote {remote_name} in {workspace_label}  vs  local `{local_path}`"

    try:
        remote_model = client.get_dataflow_definition(
            target.workspace_id, target.item_id
        )
        remote_model = validate_model_dict(remote_model, label=target.label())
    except (PowerBiApiError, DefinitionError) as exc:
        return CompareResult(
            ok=False,
            identical=False,
            header=header,
            error=f"failed to fetch remote definition: {exc}",
            remote_name=remote_name,
            local_name=local_name,
            target_ref=target_ref,
        )

    return _diff_models(
        header,
        left_model=remote_model,
        right_model=local_model,
        left_label=f"remote:{target.label()}",
        right_label=f"local:{local_path}",
        remote_name=remote_name,
        local_name=local_name,
        target_ref=target_ref,
    )


def _compare_origin_to_target(client: PowerBiClient, item: WorkItem) -> CompareResult:
    assert item.target is not None and item.target.item_id is not None
    assert item.origin is not None and item.origin.item_id is not None
    target = item.target
    origin = item.origin
    remote_name = _resolve_dataflow_name(client, target)
    local_name = _resolve_dataflow_name(client, origin)
    target_ref = target.label()

    origin_ws = _resolve_group_name(client, origin.workspace_id)
    target_ws = _resolve_group_name(client, target.workspace_id)
    header = (
        f"origin {local_name} in {origin_ws}  vs  "
        f"target {remote_name} in {target_ws}"
    )

    try:
        origin_model = client.get_dataflow_definition(
            origin.workspace_id, origin.item_id
        )
        target_model = client.get_dataflow_definition(
            target.workspace_id, target.item_id
        )
        origin_model = validate_model_dict(origin_model, label=origin.label())
        target_model = validate_model_dict(target_model, label=target.label())
    except (PowerBiApiError, DefinitionError) as exc:
        return CompareResult(
            ok=False,
            identical=False,
            header=header,
            error=f"failed to fetch remote definition: {exc}",
            remote_name=remote_name,
            local_name=local_name,
            target_ref=target_ref,
        )

    return _diff_models(
        header,
        left_model=target_model,
        right_model=origin_model,
        left_label=f"target:{target.label()}",
        right_label=f"origin:{origin.label()}",
        remote_name=remote_name,
        local_name=local_name,
        target_ref=target_ref,
    )


def _diff_models(
    header: str,
    *,
    left_model: dict[str, Any],
    right_model: dict[str, Any],
    left_label: str,
    right_label: str,
    remote_name: str = "-",
    local_name: str = "-",
    target_ref: str = "-",
) -> CompareResult:
    left_text = model_to_diff_text(left_model)
    right_text = model_to_diff_text(right_model)
    if left_text == right_text:
        return CompareResult(
            ok=True,
            identical=True,
            header=header,
            diff_text="",
            remote_name=remote_name,
            local_name=local_name,
            target_ref=target_ref,
        )

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
        remote_name=remote_name,
        local_name=local_name,
        target_ref=target_ref,
    )


def _resolve_group_name(client: PowerBiClient, group_id: str) -> str:
    try:
        data = client.get_group(group_id)
    except PowerBiApiError:
        return group_id
    return str(data.get("name") or data.get("displayName") or group_id)


def _resolve_dataflow_name(client: PowerBiClient, target: Target) -> str:
    assert target.item_id is not None
    try:
        data = client.get_dataflow(target.workspace_id, target.item_id)
    except PowerBiApiError:
        return target.item_id
    return str(data.get("name") or target.item_id)

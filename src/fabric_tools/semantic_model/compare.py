"""Compare remote semantic model definitions to local folders or other remotes."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from fabric_tools.client import FabricApiError, FabricClient
from fabric_tools.confirm import item_display_name, resolve_workspace_name
from fabric_tools.parsing import WorkItem
from fabric_tools.semantic_model.definition import (
    DefinitionError,
    definition_to_diff_text,
    folder_to_diff_text,
    validate_local_semantic_model,
)
from fabric_tools.semantic_model.ops import get_semantic_model_definition
from fabric_tools.status import BatchProgress, status_detail


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


def compare_semantic_model(client: FabricClient, item: WorkItem) -> CompareResult:
    """Diff target semantic model against a local folder or another remote."""
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
            target_ref=item.target.label(),
        )
    if item.file is not None and item.origin is not None:
        return CompareResult(
            ok=False,
            identical=False,
            header="compare",
            error="compare cannot use both --file and --origin",
            target_ref=item.target.label(),
        )

    if item.origin is not None:
        return _compare_origin_to_target(client, item)
    return _compare_file_to_target(client, item)


def run_compare_batch(
    client: FabricClient,
    items: list[WorkItem],
) -> list[CompareResult]:
    progress = BatchProgress(total=len(items))
    results: list[CompareResult] = []
    for item in items:
        label = None
        if item.target is not None and item.target.item_id is not None:
            label = item_display_name(client, item.target)
        progress.advance(status_detail("Comparing", "semantic model", label))
        results.append(compare_semantic_model(client, item))
    return results


def _compare_file_to_target(client: FabricClient, item: WorkItem) -> CompareResult:
    assert item.target is not None and item.target.item_id is not None
    assert item.file is not None
    target = item.target
    local_path = item.file
    local_name = local_path.name
    target_ref = target.label()

    try:
        validate_local_semantic_model(local_path)
        local_text = folder_to_diff_text(local_path)
    except DefinitionError as exc:
        return CompareResult(
            ok=False,
            identical=False,
            header=str(local_path),
            error=str(exc),
            local_name=local_name,
            target_ref=target_ref,
        )

    remote_name = item_display_name(client, target)
    workspace_label = resolve_workspace_name(client, target.workspace_id)
    header = f"remote {remote_name} in {workspace_label}  vs  local `{local_path}`"

    try:
        remote_definition = get_semantic_model_definition(
            client, target.workspace_id, target.item_id
        )
        remote_text = definition_to_diff_text(remote_definition)
    except (FabricApiError, DefinitionError) as exc:
        return CompareResult(
            ok=False,
            identical=False,
            header=header,
            error=f"failed to fetch remote definition: {exc}",
            remote_name=remote_name,
            local_name=local_name,
            target_ref=target_ref,
        )

    return _diff_texts(
        header,
        left_text=remote_text,
        right_text=local_text,
        left_label=f"remote:{target.label()}",
        right_label=f"local:{local_path}",
        remote_name=remote_name,
        local_name=local_name,
        target_ref=target_ref,
    )


def _compare_origin_to_target(client: FabricClient, item: WorkItem) -> CompareResult:
    assert item.target is not None and item.target.item_id is not None
    assert item.origin is not None and item.origin.item_id is not None
    target = item.target
    origin = item.origin
    remote_name = item_display_name(client, target)
    local_name = item_display_name(client, origin)
    target_ref = target.label()

    origin_ws = resolve_workspace_name(client, origin.workspace_id)
    target_ws = resolve_workspace_name(client, target.workspace_id)
    header = (
        f"origin {local_name} in {origin_ws}  vs  target {remote_name} in {target_ws}"
    )

    try:
        origin_definition = get_semantic_model_definition(
            client, origin.workspace_id, origin.item_id
        )
        target_definition = get_semantic_model_definition(
            client, target.workspace_id, target.item_id
        )
        origin_text = definition_to_diff_text(origin_definition)
        target_text = definition_to_diff_text(target_definition)
    except (FabricApiError, DefinitionError) as exc:
        return CompareResult(
            ok=False,
            identical=False,
            header=header,
            error=f"failed to fetch remote definition: {exc}",
            remote_name=remote_name,
            local_name=local_name,
            target_ref=target_ref,
        )

    return _diff_texts(
        header,
        left_text=target_text,
        right_text=origin_text,
        left_label=f"target:{target.label()}",
        right_label=f"origin:{origin.label()}",
        remote_name=remote_name,
        local_name=local_name,
        target_ref=target_ref,
    )


def _diff_texts(
    header: str,
    *,
    left_text: str,
    right_text: str,
    left_label: str,
    right_label: str,
    remote_name: str = "-",
    local_name: str = "-",
    target_ref: str = "-",
) -> CompareResult:
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

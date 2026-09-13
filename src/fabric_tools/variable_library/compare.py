"""Compare Microsoft Fabric Variable Library definitions."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from fabric_tools.client import FabricApiError, FabricClient
from fabric_tools.confirm import item_display_name, resolve_workspace_name
from fabric_tools.parsing import WorkItem
from fabric_tools.status import BatchProgress, status_detail
from fabric_tools.variable_library.definition import (
    DefinitionError,
    definition_to_diff_text,
    folder_to_diff_text,
    validate_local_variable_library,
)
from fabric_tools.variable_library.ops import get_variable_library_definition


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


def compare_variable_library(client: FabricClient, item: WorkItem) -> CompareResult:
    """Diff a target Variable Library against a folder or another remote."""
    if item.target is None or item.target.item_id is None:
        return CompareResult(
            False, False, "compare", error="compare requires workspace:artifact target"
        )
    if item.file is None and item.origin is None:
        return CompareResult(
            False,
            False,
            "compare",
            error="compare requires a local --file or --origin",
            target_ref=item.target.label(),
        )
    if item.file is not None and item.origin is not None:
        return CompareResult(
            False,
            False,
            "compare",
            error="compare cannot use both --file and --origin",
            target_ref=item.target.label(),
        )
    if item.origin is not None:
        return _compare_origin_to_target(client, item)
    return _compare_file_to_target(client, item)


def run_compare_batch(
    client: FabricClient, items: list[WorkItem]
) -> list[CompareResult]:
    progress = BatchProgress(total=len(items))
    results: list[CompareResult] = []
    for item in items:
        label = None
        if item.target is not None and item.target.item_id is not None:
            label = item_display_name(client, item.target)
        progress.advance(status_detail("Comparing", "Variable Library", label))
        results.append(compare_variable_library(client, item))
    return results


def _compare_file_to_target(client: FabricClient, item: WorkItem) -> CompareResult:
    assert item.target is not None and item.target.item_id is not None
    assert item.file is not None
    target = item.target
    try:
        validate_local_variable_library(item.file)
        local_text = folder_to_diff_text(item.file)
    except DefinitionError as exc:
        return CompareResult(
            False,
            False,
            str(item.file),
            error=str(exc),
            local_name=item.file.name,
            target_ref=target.label(),
        )
    remote_name = item_display_name(client, target)
    header = (
        f"remote {remote_name} in "
        f"{resolve_workspace_name(client, target.workspace_id)}  vs  "
        f"local `{item.file}`"
    )
    try:
        remote_text = definition_to_diff_text(
            get_variable_library_definition(client, target.workspace_id, target.item_id)
        )
    except (FabricApiError, DefinitionError) as exc:
        return CompareResult(
            False,
            False,
            header,
            error=f"failed to fetch remote definition: {exc}",
            remote_name=remote_name,
            local_name=item.file.name,
            target_ref=target.label(),
        )
    return _diff_texts(
        header,
        left_text=remote_text,
        right_text=local_text,
        left_label=f"remote:{target.label()}",
        right_label=f"local:{item.file}",
        remote_name=remote_name,
        local_name=item.file.name,
        target_ref=target.label(),
    )


def _compare_origin_to_target(client: FabricClient, item: WorkItem) -> CompareResult:
    assert item.target is not None and item.target.item_id is not None
    assert item.origin is not None and item.origin.item_id is not None
    target = item.target
    origin = item.origin
    remote_name = item_display_name(client, target)
    local_name = item_display_name(client, origin)
    header = (
        f"origin {local_name} in {resolve_workspace_name(client, origin.workspace_id)}"
        f"  vs  target {remote_name} in "
        f"{resolve_workspace_name(client, target.workspace_id)}"
    )
    try:
        origin_text = definition_to_diff_text(
            get_variable_library_definition(client, origin.workspace_id, origin.item_id)
        )
        target_text = definition_to_diff_text(
            get_variable_library_definition(client, target.workspace_id, target.item_id)
        )
    except (FabricApiError, DefinitionError) as exc:
        return CompareResult(
            False,
            False,
            header,
            error=f"failed to fetch remote definition: {exc}",
            remote_name=remote_name,
            local_name=local_name,
            target_ref=target.label(),
        )
    return _diff_texts(
        header,
        left_text=target_text,
        right_text=origin_text,
        left_label=f"target:{target.label()}",
        right_label=f"origin:{origin.label()}",
        remote_name=remote_name,
        local_name=local_name,
        target_ref=target.label(),
    )


def _diff_texts(
    header: str,
    *,
    left_text: str,
    right_text: str,
    left_label: str,
    right_label: str,
    remote_name: str,
    local_name: str,
    target_ref: str,
) -> CompareResult:
    if left_text == right_text:
        return CompareResult(
            True,
            True,
            header,
            remote_name=remote_name,
            local_name=local_name,
            target_ref=target_ref,
        )
    diff = difflib.unified_diff(
        left_text.splitlines(keepends=True),
        right_text.splitlines(keepends=True),
        fromfile=left_label,
        tofile=right_label,
    )
    return CompareResult(
        True,
        False,
        header,
        diff_text="".join(diff),
        remote_name=remote_name,
        local_name=local_name,
        target_ref=target_ref,
    )

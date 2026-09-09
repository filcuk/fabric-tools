"""Dry-run validation for notebook CLI commands."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fabric_tools.client import FabricApiError, FabricClient
from fabric_tools.notebook.cells import (
    CellSelectionError,
    format_cell_indices,
    validate_cell_indices,
)
from fabric_tools.notebook.definition import (
    DefinitionError,
    NotebookFormat,
    ipynb_from_definition,
    read_ipynb,
    validate_local_notebook,
)
from fabric_tools.notebook.ops import get_notebook_definition
from fabric_tools.parsing import CommandMode, Target, WorkItem


@dataclass
class CheckResult:
    ok: bool
    message: str


def run_dry_run(
    mode: CommandMode,
    items: list[WorkItem],
    *,
    client: FabricClient | None,
    has_targets: bool,
    has_files: bool,
    cell_indices: list[int] | None = None,
) -> list[CheckResult]:
    """Validate remote and/or local sides without mutating anything."""
    results: list[CheckResult] = []

    if has_files:
        seen_files: set[Path] = set()
        for item in items:
            if item.file is None:
                continue
            file_key = item.file.resolve()
            if file_key in seen_files:
                continue
            seen_files.add(file_key)
            try:
                fmt = validate_local_notebook(item.file)
                results.append(
                    CheckResult(True, f"local ok: {item.file} ({fmt.value})")
                )
            except DefinitionError as exc:
                results.append(CheckResult(False, f"local fail: {item.file} — {exc}"))
                continue
            if cell_indices is not None and fmt is NotebookFormat.IPYNB:
                results.append(_check_local_cells(item, cell_indices))

    if has_targets:
        if client is None:
            results.append(CheckResult(False, "remote fail: Fabric client is required"))
            return results
        seen_workspaces: set[str] = set()
        for item in items:
            target = item.target
            if target is None:
                continue
            if target.workspace_id not in seen_workspaces:
                seen_workspaces.add(target.workspace_id)
                results.append(_check_workspace(client, target.workspace_id))
            if target.item_id is not None:
                item_check = _check_item(client, target, mode=mode)
                results.append(item_check)
                if (
                    cell_indices is not None
                    and item.file is not None
                    and item_check.ok
                ):
                    results.append(_check_remote_cells(client, item, cell_indices))

    return results


def _check_local_cells(item: WorkItem, cell_indices: list[int]) -> CheckResult:
    assert item.file is not None
    try:
        notebook = read_ipynb(item.file)
        validate_cell_indices(notebook, cell_indices, side="local")
    except (DefinitionError, CellSelectionError) as exc:
        return CheckResult(False, f"cells fail: {item.file} — {exc}")
    return CheckResult(
        True,
        f"cells ok (local): [{format_cell_indices(cell_indices)}] in {item.file}",
    )


def _check_remote_cells(
    client: FabricClient,
    item: WorkItem,
    cell_indices: list[int],
) -> CheckResult:
    assert item.target is not None and item.target.item_id is not None
    label = item.target.label()
    try:
        definition = get_notebook_definition(
            client,
            item.target.workspace_id,
            item.target.item_id,
            format=NotebookFormat.IPYNB,
        )
        notebook = ipynb_from_definition(definition)
        validate_cell_indices(notebook, cell_indices, side="remote")
    except (FabricApiError, DefinitionError, CellSelectionError) as exc:
        return CheckResult(False, f"cells fail: remote {label} — {exc}")
    return CheckResult(
        True,
        f"cells ok (remote): [{format_cell_indices(cell_indices)}] in {label}",
    )


def _check_workspace(client: FabricClient, workspace_id: str) -> CheckResult:
    try:
        data = client.get_workspace(workspace_id)
    except FabricApiError as exc:
        return CheckResult(False, f"remote fail: workspace {workspace_id} — {exc}")
    name = data.get("displayName") or data.get("name") or workspace_id
    return CheckResult(True, f"remote ok: workspace '{name}' ({workspace_id})")


def _check_item(client: FabricClient, target: Target, *, mode: CommandMode) -> CheckResult:
    assert target.item_id is not None
    try:
        data = client.get_item(target.workspace_id, target.item_id)
    except FabricApiError as exc:
        return CheckResult(
            False,
            f"remote fail: item {target.workspace_id}:{target.item_id} — {exc}",
        )
    name = data.get("displayName") or data.get("name") or target.item_id
    item_type = data.get("type")
    if item_type and item_type != "Notebook":
        return CheckResult(
            False,
            f"remote fail: item '{name}' ({target.item_id}) is type {item_type}, expected Notebook",
        )
    return CheckResult(
        True,
        f"remote ok: notebook '{name}' ({target.item_id}) [{mode.value}]",
    )

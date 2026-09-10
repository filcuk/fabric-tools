"""Dry-run validation for notebook, dataflow, and dataflow-gen1 CLI commands."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fabric_tools.client import FabricApiError, FabricClient
from fabric_tools.dataflow.definition import (
    DefinitionError as DataflowGen2DefinitionError,
)
from fabric_tools.dataflow.definition import validate_local_dataflow
from fabric_tools.dataflow_gen1.definition import (
    DefinitionError as DataflowDefinitionError,
)
from fabric_tools.dataflow_gen1.definition import validate_local_model
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
from fabric_tools.powerbi_client import PowerBiApiError, PowerBiClient


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
    has_origins: bool = False,
    cell_indices: list[int] | None = None,
) -> list[CheckResult]:
    """Validate remote and/or local sides for notebooks without mutating anything."""
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

    needs_remote = has_targets or has_origins
    if needs_remote:
        if client is None:
            results.append(CheckResult(False, "remote fail: Fabric client is required"))
            return results
        seen_workspaces: set[str] = set()
        seen_items: set[str] = set()

        if has_origins:
            for item in items:
                origin = item.origin
                if origin is None or origin.item_id is None:
                    continue
                if origin.workspace_id not in seen_workspaces:
                    seen_workspaces.add(origin.workspace_id)
                    results.append(_check_workspace(client, origin.workspace_id))
                key = origin.label()
                if key not in seen_items:
                    seen_items.add(key)
                    results.append(
                        _check_item(
                            client,
                            origin,
                            mode=mode,
                            role="origin",
                            expected_type="Notebook",
                            kind_label="notebook",
                        )
                    )

        if has_targets:
            for item in items:
                target = item.target
                if target is None:
                    continue
                if target.workspace_id not in seen_workspaces:
                    seen_workspaces.add(target.workspace_id)
                    results.append(_check_workspace(client, target.workspace_id))
                if target.item_id is not None:
                    key = target.label()
                    if key not in seen_items:
                        seen_items.add(key)
                        item_check = _check_item(
                            client,
                            target,
                            mode=mode,
                            role="target",
                            expected_type="Notebook",
                            kind_label="notebook",
                        )
                        results.append(item_check)
                        if (
                            cell_indices is not None
                            and item.file is not None
                            and item_check.ok
                            and mode is not CommandMode.DELETE
                        ):
                            results.append(
                                _check_remote_cells(client, item, cell_indices)
                            )

    return results


def run_dry_run_dataflow(
    mode: CommandMode,
    items: list[WorkItem],
    *,
    client: FabricClient | None,
    has_targets: bool,
    has_files: bool,
    has_origins: bool = False,
) -> list[CheckResult]:
    """Validate Gen2 local folders and/or Fabric remotes without mutating."""
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
                validate_local_dataflow(item.file)
                results.append(
                    CheckResult(True, f"local ok: {item.file} (Dataflow folder)")
                )
            except DataflowGen2DefinitionError as exc:
                results.append(CheckResult(False, f"local fail: {item.file} — {exc}"))

    needs_remote = has_targets or has_origins
    if needs_remote:
        if client is None:
            results.append(CheckResult(False, "remote fail: Fabric client is required"))
            return results
        seen_workspaces: set[str] = set()
        seen_items: set[str] = set()

        if has_origins:
            for item in items:
                origin = item.origin
                if origin is None or origin.item_id is None:
                    continue
                if origin.workspace_id not in seen_workspaces:
                    seen_workspaces.add(origin.workspace_id)
                    results.append(_check_workspace(client, origin.workspace_id))
                key = origin.label()
                if key not in seen_items:
                    seen_items.add(key)
                    results.append(
                        _check_item(
                            client,
                            origin,
                            mode=mode,
                            role="origin",
                            expected_type="Dataflow",
                            kind_label="dataflow",
                        )
                    )

        if has_targets:
            for item in items:
                target = item.target
                if target is None:
                    continue
                if target.workspace_id not in seen_workspaces:
                    seen_workspaces.add(target.workspace_id)
                    results.append(_check_workspace(client, target.workspace_id))
                if target.item_id is not None:
                    key = target.label()
                    if key not in seen_items:
                        seen_items.add(key)
                        results.append(
                            _check_item(
                                client,
                                target,
                                mode=mode,
                                role="target",
                                expected_type="Dataflow",
                                kind_label="dataflow",
                            )
                        )

    return results


def run_dry_run_dataflow_gen1(
    mode: CommandMode,
    items: list[WorkItem],
    *,
    client: PowerBiClient | None,
    has_targets: bool,
    has_files: bool,
    has_origins: bool = False,
) -> list[CheckResult]:
    """Validate Gen1 local model.json and/or Power BI remotes without mutating."""
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
                validate_local_model(item.file)
                results.append(CheckResult(True, f"local ok: {item.file} (model.json)"))
            except DataflowDefinitionError as exc:
                results.append(CheckResult(False, f"local fail: {item.file} — {exc}"))

    needs_remote = has_targets or has_origins
    if needs_remote:
        if client is None:
            results.append(
                CheckResult(False, "remote fail: Power BI client is required")
            )
            return results
        seen_groups: set[str] = set()
        seen_items: set[str] = set()

        if has_origins:
            for item in items:
                origin = item.origin
                if origin is None or origin.item_id is None:
                    continue
                if origin.workspace_id not in seen_groups:
                    seen_groups.add(origin.workspace_id)
                    results.append(_check_powerbi_group(client, origin.workspace_id))
                key = origin.label()
                if key not in seen_items:
                    seen_items.add(key)
                    results.append(
                        _check_powerbi_dataflow(
                            client, origin, mode=mode, role="origin"
                        )
                    )

        if has_targets:
            for item in items:
                target = item.target
                if target is None:
                    continue
                if target.workspace_id not in seen_groups:
                    seen_groups.add(target.workspace_id)
                    results.append(_check_powerbi_group(client, target.workspace_id))
                if target.item_id is not None:
                    key = target.label()
                    if key not in seen_items:
                        seen_items.add(key)
                        results.append(
                            _check_powerbi_dataflow(
                                client, target, mode=mode, role="target"
                            )
                        )

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


def _check_item(
    client: FabricClient,
    target: Target,
    *,
    mode: CommandMode,
    role: str = "target",
    expected_type: str = "Notebook",
    kind_label: str = "notebook",
) -> CheckResult:
    assert target.item_id is not None
    try:
        data = client.get_item(target.workspace_id, target.item_id)
    except FabricApiError as exc:
        return CheckResult(
            False,
            f"remote fail: {role} {target.workspace_id}:{target.item_id} — {exc}",
        )
    name = data.get("displayName") or data.get("name") or target.item_id
    item_type = data.get("type")
    if item_type and item_type != expected_type:
        return CheckResult(
            False,
            f"remote fail: {role} '{name}' ({target.item_id}) is type {item_type}, "
            f"expected {expected_type}",
        )
    return CheckResult(
        True,
        f"remote ok: {role} {kind_label} '{name}' ({target.item_id}) [{mode.value}]",
    )


def _check_powerbi_group(client: PowerBiClient, group_id: str) -> CheckResult:
    try:
        data = client.get_group(group_id)
    except PowerBiApiError as exc:
        return CheckResult(False, f"remote fail: workspace {group_id} — {exc}")
    name = data.get("name") or data.get("displayName") or group_id
    return CheckResult(True, f"remote ok: workspace '{name}' ({group_id})")


def _check_powerbi_dataflow(
    client: PowerBiClient,
    target: Target,
    *,
    mode: CommandMode,
    role: str = "target",
) -> CheckResult:
    assert target.item_id is not None
    try:
        data = client.get_dataflow(target.workspace_id, target.item_id)
    except PowerBiApiError as exc:
        return CheckResult(
            False,
            f"remote fail: {role} {target.workspace_id}:{target.item_id} — {exc}",
        )
    name = data.get("name") or target.item_id
    return CheckResult(
        True,
        f"remote ok: {role} dataflow-gen1 '{name}' ({target.item_id}) [{mode.value}]",
    )

"""Dry-run validation for notebook CLI commands."""

from __future__ import annotations

from dataclasses import dataclass

from fabric_tools.client import FabricApiError, FabricClient
from fabric_tools.notebook.definition import DefinitionError, validate_local_notebook
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
) -> list[CheckResult]:
    """Validate remote and/or local sides without mutating anything."""
    results: list[CheckResult] = []

    if has_files:
        for item in items:
            if item.file is None:
                continue
            try:
                fmt = validate_local_notebook(item.file)
                results.append(
                    CheckResult(True, f"local ok: {item.file} ({fmt.value})")
                )
            except DefinitionError as exc:
                results.append(CheckResult(False, f"local fail: {item.file} — {exc}"))

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
                results.append(_check_item(client, target, mode=mode))

    return results


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

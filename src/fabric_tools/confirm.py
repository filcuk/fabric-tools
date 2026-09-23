"""User confirmation prompts for overwrite, create, and delete actions."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import typer

from fabric_tools.client import FabricApiError, FabricClient
from fabric_tools.dataflow.definition import (
    detect_dataflow_path,
    display_name_from_path,
)
from fabric_tools.dataflow_gen1.definition import ensure_model_path
from fabric_tools.environment.definition import (
    detect_environment_path,
)
from fabric_tools.environment.definition import (
    display_name_from_path as environment_name_from_path,
)
from fabric_tools.notebook.definition import ensure_notebook_path
from fabric_tools.org_app.definition import (
    detect_org_app_path,
)
from fabric_tools.org_app.definition import (
    display_name_from_path as org_app_name_from_path,
)
from fabric_tools.paginated_report.definition import ensure_rdl_path
from fabric_tools.parsing import Target, WorkItem, default_download_paths
from fabric_tools.pipeline.definition import detect_pipeline_path
from fabric_tools.powerbi_client import PowerBiApiError, PowerBiClient
from fabric_tools.report.definition import detect_report_path, is_pbix_path
from fabric_tools.semantic_model.definition import detect_semantic_model_path
from fabric_tools.status import busy, status_detail
from fabric_tools.udf.definition import detect_udf_folder
from fabric_tools.variable_library.definition import (
    detect_variable_library_path,
)
from fabric_tools.variable_library.definition import (
    display_name_from_path as variable_library_name_from_path,
)

# Shared copy for decline, Ctrl+C/EOF on prompts, and empty warn-panel fallback.
CONFIRM_ABORT_MESSAGE = "Aborted by user."


class ConfirmationAborted(Exception):
    """Raised when the user declines or interrupts a confirmation prompt."""


def finish_prompt_line(*, err: bool = False) -> None:
    """Advance past a mid-line prompt after Ctrl+C / EOF.

    ``typer.confirm`` writes the prompt without a trailing newline; an interrupt
    leaves the cursor on that line. Following stderr panels must not glue to
    ``[y/N]:``.
    """
    stream = sys.stderr if err else sys.stdout
    try:
        stream.write("\n")
        stream.flush()
    except OSError:
        pass


def abort_interrupt_message(*, err: bool = False) -> str:
    """Finish a mid-line prompt after ``typer.Abort``; return shared abort text."""
    finish_prompt_line(err=err)
    return CONFIRM_ABORT_MESSAGE


def prompt_confirm(
    message: str,
    *,
    default: bool = False,
    err: bool = False,
) -> bool:
    """Yes/no confirm. Decline and Ctrl+C/EOF both return ``False``.

    Prefer this over raw ``typer.confirm`` so interrupt is not an empty
    ``typer.Abort`` that becomes a red ``Operation failed.`` panel mid-line.
    Options and ``fabric-tools …`` invocations in *message* are highlighted.
    """
    from fabric_tools.colours import render_cli_prose

    text = render_cli_prose(message, stderr=err)
    try:
        return bool(typer.confirm(text, default=default, err=err))
    except typer.Abort:
        finish_prompt_line(err=err)
        return False


def _normalize_explicit_download_files(
    items: list[WorkItem],
    normalize: Callable[[Path], Path],
) -> list[WorkItem]:
    """Apply *normalize* to each explicit local download path."""
    return [
        WorkItem(
            item.target,
            normalize(item.file) if item.file is not None else None,
            origin=item.origin,
        )
        for item in items
    ]


def _normalize_report_download_path(path: Path) -> Path:
    """Keep ``.pbix``; otherwise ensure a ``*.Report`` folder path."""
    if is_pbix_path(path):
        return path
    return detect_report_path(path)


def confirm_or_abort(message: str, *, silent: bool) -> None:
    """Prompt unless ``silent``; abort on decline or interrupt."""
    if silent:
        return
    if not prompt_confirm(message, default=False):
        raise ConfirmationAborted(CONFIRM_ABORT_MESSAGE)


def resolve_workspace_name(client: FabricClient, workspace_id: str) -> str:
    try:
        data = client.get_workspace(workspace_id)
    except FabricApiError as exc:
        return f"{workspace_id} (unavailable: {exc})"
    name = data.get("displayName") or data.get("name") or workspace_id
    return f"{name} ({workspace_id})"


def resolve_item_name(client: FabricClient, target: Target) -> str:
    if target.item_id is None:
        return "(new notebook)"
    try:
        data = client.get_item(target.workspace_id, target.item_id)
    except FabricApiError as exc:
        return f"{target.item_id} (unavailable: {exc})"
    name = data.get("displayName") or data.get("name") or target.item_id
    item_type = data.get("type")
    suffix = f", type={item_type}" if item_type else ""
    return f"{name} ({target.item_id}{suffix})"


def item_display_name(client: FabricClient, target: Target) -> str:
    """Return Fabric item display name only (no id/type suffix)."""
    if target.item_id is None:
        return "-"
    try:
        data = client.get_item(target.workspace_id, target.item_id)
    except FabricApiError:
        return target.item_id
    name = data.get("displayName") or data.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return target.item_id


def status_item_label(
    client: FabricClient,
    target: Target | None,
    *,
    fallback: str | None = None,
) -> str | None:
    """Display name for ``status_detail`` brackets (never a raw GUID preference).

    Returns *fallback* when *target* has no item id (e.g. create). Falls back to
    the item id only when the remote lookup fails — ``status_detail`` then shortens
    it. Prefer passing a local/create display name as *fallback* when known.
    """
    if target is None or target.item_id is None:
        return fallback
    return item_display_name(client, target)


def status_item_label_for_id(
    client: FabricClient,
    workspace_id: str,
    item_id: str,
) -> str:
    """Display name for a workspace item id (joined model downloads, etc.)."""
    return item_display_name(client, Target(workspace_id, item_id))


def resolve_powerbi_group_name(client: PowerBiClient, group_id: str) -> str:
    try:
        data = client.get_group(group_id)
    except PowerBiApiError as exc:
        return f"{group_id} (unavailable: {exc})"
    name = data.get("name") or data.get("displayName") or group_id
    return f"{name} ({group_id})"


def resolve_powerbi_dataflow_name(client: PowerBiClient, target: Target) -> str:
    if target.item_id is None:
        return "(new dataflow-gen1)"
    try:
        data = client.get_dataflow(target.workspace_id, target.item_id)
    except PowerBiApiError as exc:
        return f"{target.item_id} (unavailable: {exc})"
    name = data.get("name") or target.item_id
    return f"{name} ({target.item_id})"


def notebook_display_name(client: FabricClient, target: Target) -> str:
    """Return Fabric item display name for a notebook target (fallback: id)."""
    if target.item_id is None:
        return "Notebook"
    return item_display_name(client, target)


def dataflow_gen1_display_name(client: PowerBiClient, target: Target) -> str:
    """Return Power BI dataflow name for a Gen1 target (fallback: id)."""
    if target.item_id is None:
        return "Dataflow"
    try:
        data = client.get_dataflow(target.workspace_id, target.item_id)
    except PowerBiApiError:
        return target.item_id
    name = data.get("name") or data.get("displayName")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return target.item_id


def resolve_powerbi_paginated_report_name(client: PowerBiClient, target: Target) -> str:
    if target.item_id is None:
        return "(new paginated-report)"
    try:
        data = client.get_report(target.workspace_id, target.item_id)
    except PowerBiApiError as exc:
        return f"{target.item_id} (unavailable: {exc})"
    name = data.get("name") or target.item_id
    return f"{name} ({target.item_id})"


def paginated_report_display_name(client: PowerBiClient, target: Target) -> str:
    """Return Power BI paginated report name for a target (fallback: id)."""
    if target.item_id is None:
        return "PaginatedReport"
    try:
        data = client.get_report(target.workspace_id, target.item_id)
    except PowerBiApiError:
        return target.item_id
    name = data.get("name") or data.get("displayName")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return target.item_id


def status_gen1_label(
    client: PowerBiClient,
    target: Target | None,
    *,
    fallback: str | None = None,
) -> str | None:
    """Display name for Gen1 spinner brackets (Power BI)."""
    if target is None or target.item_id is None:
        return fallback
    return dataflow_gen1_display_name(client, target)


def status_paginated_label(
    client: PowerBiClient,
    target: Target | None,
    *,
    fallback: str | None = None,
) -> str | None:
    """Display name for paginated-report spinner brackets (Power BI)."""
    if target is None or target.item_id is None:
        return fallback
    return paginated_report_display_name(client, target)


def dataflow_display_name(client: FabricClient, target: Target) -> str:
    """Return Fabric item display name for a Dataflow Gen2 target (fallback: id)."""
    if target.item_id is None:
        return "Dataflow"
    try:
        data = client.get_item(target.workspace_id, target.item_id)
    except FabricApiError:
        return target.item_id
    name = data.get("displayName") or data.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return target.item_id


def org_app_display_name(client: FabricClient, target: Target) -> str:
    """Return Fabric item display name for an Org App target (fallback: id)."""
    if target.item_id is None:
        return "OrgApp"
    return item_display_name(client, target)


def variable_library_display_name(client: FabricClient, target: Target) -> str:
    """Return Fabric item display name for a Variable Library target."""
    if target.item_id is None:
        return "VariableLibrary"
    return item_display_name(client, target)


def environment_display_name(client: FabricClient, target: Target) -> str:
    """Return Fabric item display name for an Environment target."""
    if target.item_id is None:
        return "Environment"
    return item_display_name(client, target)


def resolve_notebook_download_files(
    client: FabricClient,
    items: list[WorkItem],
) -> list[WorkItem]:
    """Fill missing download destinations from remote notebook display names (``.ipynb``)."""
    if not items:
        return items
    if all(item.file is not None for item in items):
        return _normalize_explicit_download_files(items, ensure_notebook_path)
    if any(item.file is not None for item in items):
        raise ValueError(
            "download work items must all omit --target path or all provide it"
        )

    with busy(status_detail("notebook", "resolving download paths")):
        names = [
            notebook_display_name(client, item.target)
            if item.target is not None
            else "Notebook"
            for item in items
        ]
        paths = default_download_paths(names, extension=".ipynb")
    return [
        WorkItem(item.target, path, origin=item.origin)
        for item, path in zip(items, paths, strict=True)
    ]


def resolve_dataflow_gen1_download_files(
    client: PowerBiClient,
    items: list[WorkItem],
) -> list[WorkItem]:
    """Fill missing download destinations from remote dataflow names (``.json``)."""
    if not items:
        return items
    if all(item.file is not None for item in items):
        return _normalize_explicit_download_files(items, ensure_model_path)
    if any(item.file is not None for item in items):
        raise ValueError(
            "download work items must all omit --target path or all provide it"
        )

    with busy(status_detail("dataflow-gen1", "resolving download paths")):
        names = [
            dataflow_gen1_display_name(client, item.target)
            if item.target is not None
            else "Dataflow"
            for item in items
        ]
        paths = default_download_paths(names, extension=".json")
    return [
        WorkItem(item.target, path, origin=item.origin)
        for item, path in zip(items, paths, strict=True)
    ]


def resolve_paginated_report_download_files(
    client: PowerBiClient,
    items: list[WorkItem],
) -> list[WorkItem]:
    """Fill missing download destinations from remote report names (``.rdl``)."""
    if not items:
        return items
    if all(item.file is not None for item in items):
        return _normalize_explicit_download_files(items, ensure_rdl_path)
    if any(item.file is not None for item in items):
        raise ValueError(
            "download work items must all omit --target path or all provide it"
        )

    with busy(status_detail("paginated-report", "resolving download paths")):
        names = [
            paginated_report_display_name(client, item.target)
            if item.target is not None
            else "PaginatedReport"
            for item in items
        ]
        paths = default_download_paths(names, extension=".rdl")
    return [
        WorkItem(item.target, path, origin=item.origin)
        for item, path in zip(items, paths, strict=True)
    ]


def resolve_dataflow_download_files(
    client: FabricClient,
    items: list[WorkItem],
) -> list[WorkItem]:
    """Fill missing download destinations from remote display names (``.Dataflow``)."""
    if not items:
        return items
    if all(item.file is not None for item in items):
        return _normalize_explicit_download_files(items, detect_dataflow_path)
    if any(item.file is not None for item in items):
        raise ValueError(
            "download work items must all omit --target path or all provide it"
        )

    with busy(status_detail("dataflow", "resolving download paths")):
        names = [
            dataflow_display_name(client, item.target)
            if item.target is not None
            else "Dataflow"
            for item in items
        ]
        paths = default_download_paths(names, extension=".Dataflow")
    return [
        WorkItem(item.target, path, origin=item.origin)
        for item, path in zip(items, paths, strict=True)
    ]


def resolve_org_app_download_files(
    client: FabricClient,
    items: list[WorkItem],
) -> list[WorkItem]:
    """Fill missing download destinations from remote names (``.OrgApp``)."""
    if not items:
        return items
    if all(item.file is not None for item in items):
        return _normalize_explicit_download_files(items, detect_org_app_path)
    if any(item.file is not None for item in items):
        raise ValueError(
            "download work items must all omit --target path or all provide it"
        )

    with busy(status_detail("org-app", "resolving download paths")):
        names = [
            org_app_display_name(client, item.target)
            if item.target is not None
            else "OrgApp"
            for item in items
        ]
        paths = default_download_paths(names, extension=".OrgApp")
    return [
        WorkItem(item.target, path, origin=item.origin)
        for item, path in zip(items, paths, strict=True)
    ]


def resolve_variable_library_download_files(
    client: FabricClient,
    items: list[WorkItem],
) -> list[WorkItem]:
    """Fill missing download destinations from remote names."""
    if not items:
        return items
    if all(item.file is not None for item in items):
        return _normalize_explicit_download_files(items, detect_variable_library_path)
    if any(item.file is not None for item in items):
        raise ValueError(
            "download work items must all omit --target path or all provide it"
        )
    with busy(status_detail("variable-library", "resolving download paths")):
        names = [
            variable_library_display_name(client, item.target)
            if item.target is not None
            else "VariableLibrary"
            for item in items
        ]
        paths = default_download_paths(names, extension=".VariableLibrary")
    return [
        WorkItem(item.target, path, origin=item.origin)
        for item, path in zip(items, paths, strict=True)
    ]


def resolve_environment_download_files(
    client: FabricClient,
    items: list[WorkItem],
) -> list[WorkItem]:
    """Fill missing download destinations from remote names (``.Environment``)."""
    if not items:
        return items
    if all(item.file is not None for item in items):
        return _normalize_explicit_download_files(items, detect_environment_path)
    if any(item.file is not None for item in items):
        raise ValueError(
            "download work items must all omit --target path or all provide it"
        )
    with busy(status_detail("environment", "resolving download paths")):
        names = [
            environment_display_name(client, item.target)
            if item.target is not None
            else "Environment"
            for item in items
        ]
        paths = default_download_paths(names, extension=".Environment")
    return [
        WorkItem(item.target, path, origin=item.origin)
        for item, path in zip(items, paths, strict=True)
    ]


def confirm_download_overwrites(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm before overwriting existing local paths (Fabric notebooks)."""
    if silent:
        return
    existing = [
        item
        for item in items
        if item.target is not None and item.file is not None and _path_exists(item.file)
    ]
    if not existing:
        return

    lines = ["About to overwrite local path(s):"]
    with busy(status_detail("notebook", "resolving targets")):
        for item in existing:
            assert item.target is not None and item.file is not None
            remote = resolve_item_name(client, item.target)
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            lines.append(f"  - local `{item.file}` <- remote {remote} in {workspace}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_download_overwrites_dataflow_gen1(
    client: PowerBiClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm before overwriting existing local model.json paths."""
    if silent:
        return
    existing = [
        item
        for item in items
        if item.target is not None and item.file is not None and _path_exists(item.file)
    ]
    if not existing:
        return

    lines = ["About to overwrite local path(s):"]
    with busy(status_detail("dataflow-gen1", "resolving targets")):
        for item in existing:
            assert item.target is not None and item.file is not None
            remote = resolve_powerbi_dataflow_name(client, item.target)
            workspace = resolve_powerbi_group_name(client, item.target.workspace_id)
            lines.append(f"  - local `{item.file}` <- remote {remote} in {workspace}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_download_overwrites_paginated_report(
    client: PowerBiClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm before overwriting existing local ``.rdl`` paths."""
    if silent:
        return
    existing = [
        item
        for item in items
        if item.target is not None and item.file is not None and _path_exists(item.file)
    ]
    if not existing:
        return

    lines = ["About to overwrite local path(s):"]
    with busy(status_detail("paginated-report", "resolving targets")):
        for item in existing:
            assert item.target is not None and item.file is not None
            remote = resolve_powerbi_paginated_report_name(client, item.target)
            workspace = resolve_powerbi_group_name(client, item.target.workspace_id)
            lines.append(f"  - local `{item.file}` <- remote {remote} in {workspace}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_download_overwrites_dataflow(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm before overwriting existing local Dataflow Gen2 folders."""
    if silent:
        return
    existing = [
        item
        for item in items
        if item.target is not None and item.file is not None and _path_exists(item.file)
    ]
    if not existing:
        return

    lines = ["About to overwrite local path(s):"]
    with busy(status_detail("dataflow", "resolving targets")):
        for item in existing:
            assert item.target is not None and item.file is not None
            remote = resolve_item_name(client, item.target)
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            lines.append(f"  - local `{item.file}` <- remote {remote} in {workspace}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_download_overwrites_org_app(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm before overwriting existing local Org App folders."""
    if silent:
        return
    existing = [
        item
        for item in items
        if item.target is not None and item.file is not None and _path_exists(item.file)
    ]
    if not existing:
        return

    lines = ["About to overwrite local path(s):"]
    with busy(status_detail("org-app", "resolving targets")):
        for item in existing:
            assert item.target is not None and item.file is not None
            remote = resolve_item_name(client, item.target)
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            lines.append(f"  - local `{item.file}` <- remote {remote} in {workspace}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_download_overwrites_variable_library(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm before overwriting existing local Variable Library folders."""
    if silent:
        return
    existing = [
        item
        for item in items
        if item.target is not None and item.file is not None and _path_exists(item.file)
    ]
    if not existing:
        return
    lines = ["About to overwrite local path(s):"]
    with busy(status_detail("variable-library", "resolving targets")):
        for item in existing:
            assert item.target is not None and item.file is not None
            remote = resolve_item_name(client, item.target)
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            lines.append(f"  - local `{item.file}` <- remote {remote} in {workspace}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_download_overwrites_environment(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm before overwriting existing local Environment folders."""
    if silent:
        return
    existing = [
        item
        for item in items
        if item.target is not None and item.file is not None and _path_exists(item.file)
    ]
    if not existing:
        return
    lines = ["About to overwrite local path(s):"]
    with busy(status_detail("environment", "resolving targets")):
        for item in existing:
            assert item.target is not None and item.file is not None
            remote = resolve_item_name(client, item.target)
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            lines.append(f"  - local `{item.file}` <- remote {remote} in {workspace}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_deploy_actions(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
    display_names: list[str] | None = None,
    cell_indices: list[int] | None = None,
    guid_map_line: str | None = None,
) -> None:
    """Confirm create or remote overwrite before notebook deploy."""
    if silent or not items:
        return

    first = items[0].target
    if first is None:
        return

    if first.is_create:
        lines = ["About to create notebook(s):"]
        with busy(status_detail("notebook", "resolving targets")):
            for index, item in enumerate(items):
                assert item.target is not None
                workspace = resolve_workspace_name(client, item.target.workspace_id)
                name: str | None = None
                if (
                    display_names
                    and index < len(display_names)
                    and display_names[index]
                ):
                    name = display_names[index]
                if not name:
                    if item.file is not None:
                        name = item.file.name
                    elif item.origin is not None:
                        name = resolve_item_name(client, item.origin)
                    else:
                        name = "(unnamed)"
                source = _source_phrase_fabric(client, item)
                lines.append(f"  - '{name}' in {workspace}{source}")
        if guid_map_line:
            lines.append(guid_map_line)
        lines.append("Are you sure?")
        confirm_or_abort("\n".join(lines), silent=False)
        return

    if cell_indices is not None:
        cells_label = ", ".join(str(index) for index in cell_indices)
        lines = [f"About to overwrite cell(s) [{cells_label}] in remote notebook:"]
    else:
        lines = ["About to overwrite remote notebook(s):"]
    with busy(status_detail("notebook", "resolving targets")):
        for item in items:
            assert item.target is not None
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            remote = resolve_item_name(client, item.target)
            source = _source_phrase_fabric(client, item, prefix=" with")
            lines.append(f"  - {remote} in {workspace}{source}")
    if guid_map_line:
        lines.append(guid_map_line)
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_deploy_create_dataflow_gen1(
    client: PowerBiClient,
    items: list[WorkItem],
    *,
    silent: bool,
    display_names: list[str] | None = None,
) -> None:
    """Confirm Gen1 dataflow create (no overwrite)."""
    if silent or not items:
        return

    lines = ["About to create dataflow-gen1 item(s):"]
    with busy(status_detail("dataflow-gen1", "resolving targets")):
        for index, item in enumerate(items):
            assert item.target is not None
            workspace = resolve_powerbi_group_name(client, item.target.workspace_id)
            name: str | None = None
            if display_names and index < len(display_names) and display_names[index]:
                name = display_names[index]
            if not name:
                if item.file is not None:
                    name = item.file.name
                elif item.origin is not None:
                    name = resolve_powerbi_dataflow_name(client, item.origin)
                else:
                    name = "(unnamed)"
            source = _source_phrase_powerbi(client, item)
            lines.append(f"  - '{name}' in {workspace}{source}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_deploy_actions_paginated_report(
    client: PowerBiClient,
    items: list[WorkItem],
    *,
    silent: bool,
    display_names: list[str] | None = None,
) -> None:
    """Confirm create or remote overwrite before paginated-report deploy."""
    from fabric_tools.paginated_report.definition import display_name_from_path

    if silent or not items:
        return

    first = items[0].target
    if first is None:
        return

    if first.is_create:
        lines = ["About to create paginated-report item(s):"]
        with busy(status_detail("paginated-report", "resolving targets")):
            for index, item in enumerate(items):
                assert item.target is not None
                workspace = resolve_powerbi_group_name(client, item.target.workspace_id)
                name: str | None = None
                if (
                    display_names
                    and index < len(display_names)
                    and display_names[index]
                ):
                    name = display_names[index]
                if not name:
                    if item.file is not None:
                        name = display_name_from_path(item.file)
                    elif item.origin is not None:
                        name = resolve_powerbi_paginated_report_name(
                            client, item.origin
                        )
                    else:
                        name = "(unnamed)"
                source = _source_phrase_paginated_report(client, item)
                lines.append(f"  - '{name}' in {workspace}{source}")
        lines.append("Are you sure?")
        confirm_or_abort("\n".join(lines), silent=False)
        return

    lines = ["About to overwrite remote paginated-report item(s):"]
    with busy(status_detail("paginated-report", "resolving targets")):
        for item in items:
            assert item.target is not None
            workspace = resolve_powerbi_group_name(client, item.target.workspace_id)
            remote = resolve_powerbi_paginated_report_name(client, item.target)
            source = _source_phrase_paginated_report(client, item, prefix=" with")
            lines.append(f"  - {remote} in {workspace}{source}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_deploy_actions_dataflow(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
    display_names: list[str] | None = None,
    guid_map_line: str | None = None,
    publish: bool = False,
) -> None:
    """Confirm create or remote overwrite before Dataflow Gen2 deploy."""
    if silent or not items:
        return

    first = items[0].target
    if first is None:
        return

    if first.is_create:
        lines = ["About to create dataflow(s):"]
        with busy(status_detail("dataflow", "resolving targets")):
            for index, item in enumerate(items):
                assert item.target is not None
                workspace = resolve_workspace_name(client, item.target.workspace_id)
                name: str | None = None
                if (
                    display_names
                    and index < len(display_names)
                    and display_names[index]
                ):
                    name = display_names[index]
                if not name:
                    if item.file is not None:
                        name = display_name_from_path(item.file)
                    elif item.origin is not None:
                        name = resolve_item_name(client, item.origin)
                    else:
                        name = "(unnamed)"
                source = _source_phrase_fabric(client, item)
                lines.append(f"  - '{name}' in {workspace}{source}")
        if guid_map_line:
            lines.append(guid_map_line)
        if publish:
            lines.append("Will publish (Apply Changes) after each successful deploy.")
        lines.append("Are you sure?")
        confirm_or_abort("\n".join(lines), silent=False)
        return

    lines = ["About to overwrite remote dataflow(s):"]
    with busy(status_detail("dataflow", "resolving targets")):
        for item in items:
            assert item.target is not None
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            remote = resolve_item_name(client, item.target)
            source = _source_phrase_fabric(client, item, prefix=" with")
            lines.append(f"  - {remote} in {workspace}{source}")
    if guid_map_line:
        lines.append(guid_map_line)
    if publish:
        lines.append("Will publish (Apply Changes) after each successful deploy.")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_deploy_actions_org_app(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
    display_names: list[str] | None = None,
) -> None:
    """Confirm create or remote overwrite before Org App deploy."""
    if silent or not items:
        return

    first = items[0].target
    if first is None:
        return

    if first.is_create:
        lines = ["About to create Org App(s):"]
        with busy(status_detail("org-app", "resolving targets")):
            for index, item in enumerate(items):
                assert item.target is not None
                workspace = resolve_workspace_name(client, item.target.workspace_id)
                name: str | None = None
                if (
                    display_names
                    and index < len(display_names)
                    and display_names[index]
                ):
                    name = display_names[index]
                if not name:
                    if item.file is not None:
                        name = org_app_name_from_path(item.file)
                    elif item.origin is not None:
                        name = resolve_item_name(client, item.origin)
                    else:
                        name = "(unnamed)"
                source = _source_phrase_fabric(client, item)
                lines.append(f"  - '{name}' in {workspace}{source}")
        lines.append("Are you sure?")
        confirm_or_abort("\n".join(lines), silent=False)
        return

    lines = ["About to overwrite remote Org App(s):"]
    with busy(status_detail("org-app", "resolving targets")):
        for item in items:
            assert item.target is not None
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            remote = resolve_item_name(client, item.target)
            source = _source_phrase_fabric(client, item, prefix=" with")
            lines.append(f"  - {remote} in {workspace}{source}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_deploy_actions_variable_library(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
    display_names: list[str] | None = None,
) -> None:
    """Confirm create or remote overwrite before Variable Library deploy."""
    if silent or not items:
        return
    first = items[0].target
    if first is None:
        return
    if first.is_create:
        lines = ["About to create Variable Library item(s):"]
        with busy(status_detail("variable-library", "resolving targets")):
            for index, item in enumerate(items):
                assert item.target is not None
                workspace = resolve_workspace_name(client, item.target.workspace_id)
                name: str | None = None
                if display_names and index < len(display_names):
                    name = display_names[index]
                if not name:
                    if item.file is not None:
                        name = variable_library_name_from_path(item.file)
                    elif item.origin is not None:
                        name = resolve_item_name(client, item.origin)
                    else:
                        name = "(unnamed)"
                source = _source_phrase_fabric(client, item)
                lines.append(f"  - '{name}' in {workspace}{source}")
        lines.append("Are you sure?")
        confirm_or_abort("\n".join(lines), silent=False)
        return
    lines = ["About to overwrite remote Variable Library item(s):"]
    with busy(status_detail("variable-library", "resolving targets")):
        for item in items:
            assert item.target is not None
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            remote = resolve_item_name(client, item.target)
            source = _source_phrase_fabric(client, item, prefix=" with")
            lines.append(f"  - {remote} in {workspace}{source}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_deploy_actions_environment(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
    display_names: list[str] | None = None,
) -> None:
    """Confirm create or remote overwrite before Environment deploy."""
    if silent or not items:
        return
    first = items[0].target
    if first is None:
        return
    if first.is_create:
        lines = ["About to create Environment(s):"]
        with busy(status_detail("environment", "resolving targets")):
            for index, item in enumerate(items):
                assert item.target is not None
                workspace = resolve_workspace_name(client, item.target.workspace_id)
                name: str | None = None
                if display_names and index < len(display_names):
                    name = display_names[index]
                if not name:
                    if item.file is not None:
                        name = environment_name_from_path(item.file)
                    elif item.origin is not None:
                        name = resolve_item_name(client, item.origin)
                    else:
                        name = "(unnamed)"
                source = _source_phrase_fabric(client, item)
                lines.append(f"  - '{name}' in {workspace}{source}")
        lines.append("Are you sure?")
        confirm_or_abort("\n".join(lines), silent=False)
        return
    lines = ["About to overwrite remote Environment(s):"]
    with busy(status_detail("environment", "resolving targets")):
        for item in items:
            assert item.target is not None
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            remote = resolve_item_name(client, item.target)
            source = _source_phrase_fabric(client, item, prefix=" with")
            lines.append(f"  - {remote} in {workspace}{source}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_delete_actions(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm soft-delete of remote Fabric notebooks."""
    if silent or not items:
        return

    lines = ["About to delete remote notebook(s):"]
    with busy(status_detail("notebook", "resolving targets")):
        for item in items:
            assert item.target is not None
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            remote = resolve_item_name(client, item.target)
            lines.append(f"  - {remote} in {workspace}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_delete_dataflow_gen1(
    client: PowerBiClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm delete of remote Dataflow Gen1 items."""
    if silent or not items:
        return

    lines = ["About to delete remote dataflow-gen1 item(s):"]
    with busy(status_detail("dataflow-gen1", "resolving targets")):
        for item in items:
            assert item.target is not None
            workspace = resolve_powerbi_group_name(client, item.target.workspace_id)
            remote = resolve_powerbi_dataflow_name(client, item.target)
            lines.append(f"  - {remote} in {workspace}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_delete_paginated_report(
    client: PowerBiClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm delete of remote paginated-report items."""
    if silent or not items:
        return

    lines = ["About to delete remote paginated-report item(s):"]
    with busy(status_detail("paginated-report", "resolving targets")):
        for item in items:
            assert item.target is not None
            workspace = resolve_powerbi_group_name(client, item.target.workspace_id)
            remote = resolve_powerbi_paginated_report_name(client, item.target)
            lines.append(f"  - {remote} in {workspace}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_delete_dataflow(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm soft-delete of remote Dataflow Gen2 items."""
    if silent or not items:
        return

    lines = ["About to delete remote dataflow(s):"]
    with busy(status_detail("dataflow", "resolving targets")):
        for item in items:
            assert item.target is not None
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            remote = resolve_item_name(client, item.target)
            lines.append(f"  - {remote} in {workspace}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_delete_org_app(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm soft-delete of remote Org App items."""
    if silent or not items:
        return

    lines = ["About to delete remote Org App(s):"]
    with busy(status_detail("org-app", "resolving targets")):
        for item in items:
            assert item.target is not None
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            remote = resolve_item_name(client, item.target)
            lines.append(f"  - {remote} in {workspace}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_delete_variable_library(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm soft-delete of remote Variable Library items."""
    if silent or not items:
        return
    lines = ["About to delete remote Variable Library item(s):"]
    with busy(status_detail("variable-library", "resolving targets")):
        for item in items:
            assert item.target is not None
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            remote = resolve_item_name(client, item.target)
            lines.append(f"  - {remote} in {workspace}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_delete_environment(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm soft-delete of remote Environment items."""
    if silent or not items:
        return
    lines = ["About to delete remote Environment(s):"]
    with busy(status_detail("environment", "resolving targets")):
        for item in items:
            assert item.target is not None
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            remote = resolve_item_name(client, item.target)
            lines.append(f"  - {remote} in {workspace}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def semantic_model_display_name(client: FabricClient, target: Target) -> str:
    """Return Fabric item display name for a semantic model target (fallback: id)."""
    if target.item_id is None:
        return "SemanticModel"
    try:
        data = client.get_item(target.workspace_id, target.item_id)
    except FabricApiError:
        return target.item_id
    name = data.get("displayName") or data.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return target.item_id


def resolve_semantic_model_download_files(
    client: FabricClient,
    items: list[WorkItem],
) -> list[WorkItem]:
    """Fill missing download destinations from remote names (``.SemanticModel``)."""
    if not items:
        return items
    if all(item.file is not None for item in items):
        return _normalize_explicit_download_files(items, detect_semantic_model_path)
    if any(item.file is not None for item in items):
        raise ValueError(
            "download work items must all omit --target path or all provide it"
        )

    with busy(status_detail("semantic-model", "resolving download paths")):
        names = [
            semantic_model_display_name(client, item.target)
            if item.target is not None
            else "SemanticModel"
            for item in items
        ]
        paths = default_download_paths(names, extension=".SemanticModel")
    return [
        WorkItem(item.target, path, origin=item.origin)
        for item, path in zip(items, paths, strict=True)
    ]


def confirm_download_overwrites_semantic_model(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm before overwriting existing local semantic model folders."""
    if silent or not items:
        return
    existing = [item for item in items if item.file is not None and item.file.exists()]
    if not existing:
        return

    lines = ["About to overwrite local path(s):"]
    with busy(status_detail("semantic-model", "resolving targets")):
        for item in existing:
            assert item.target is not None and item.file is not None
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            remote = resolve_item_name(client, item.target)
            lines.append(f"  - {item.file}  (from {remote} in {workspace})")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def _bound_report_lines(
    workspace_id: str,
    semantic_model_id: str,
) -> tuple[list[str], str | None]:
    """Best-effort list of report lines bound to a semantic model in a workspace.

    Returns ``(lines, error_note)``. *error_note* is set when the Power BI list
    could not be loaded.
    """
    from fabric_tools.powerbi_client import PowerBiApiError, PowerBiClient

    try:
        with PowerBiClient() as pbi:
            pbi.ensure_authenticated()
            reports = pbi.reports_bound_to_dataset(workspace_id, semantic_model_id)
    except PowerBiApiError as exc:
        return [], f"(could not list dependent reports: {exc})"
    except Exception as exc:  # noqa: BLE001 - confirm should not crash auth noise
        return [], f"(could not list dependent reports: {exc})"

    lines: list[str] = []
    for report in reports:
        rid = str(report.get("id") or "")
        rname = str(report.get("name") or report.get("displayName") or rid)
        lines.append(f'report "{rname}" ({rid})')
    return lines, None


def confirm_deploy_actions_semantic_model(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
    display_names: list[str] | None = None,
) -> None:
    """Confirm create or overwrite of remote semantic models (with impact list)."""
    from fabric_tools.semantic_model.definition import display_name_from_path

    if silent or not items:
        return

    creates = [
        item for item in items if item.target is not None and item.target.is_create
    ]
    overwrites = [
        item
        for item in items
        if item.target is not None and item.target.item_id is not None
    ]

    if creates:
        lines = ["About to create semantic model(s):"]
        with busy(status_detail("semantic-model", "resolving targets")):
            for index, item in enumerate(items):
                if item.target is None or not item.target.is_create:
                    continue
                workspace = resolve_workspace_name(client, item.target.workspace_id)
                if (
                    display_names
                    and index < len(display_names)
                    and display_names[index]
                ):
                    name = display_names[index]
                elif item.file is not None:
                    name = display_name_from_path(item.file)
                else:
                    name = "SemanticModel"
                source = (
                    str(item.file)
                    if item.file is not None
                    else (
                        f"origin {item.origin.label()}"
                        if item.origin is not None
                        else "?"
                    )
                )
                lines.append(f"  - '{name}' in {workspace} from {source}")
        lines.append("Are you sure?")
        confirm_or_abort("\n".join(lines), silent=False)

    if overwrites:
        lines = [
            "About to overwrite remote semantic model(s).",
            "Other reports bound to these models may be affected:",
        ]
        with busy(status_detail("semantic-model", "resolving targets and impact")):
            for item in overwrites:
                assert item.target is not None and item.target.item_id is not None
                workspace = resolve_workspace_name(client, item.target.workspace_id)
                name = semantic_model_display_name(client, item.target)
                sm_id = item.target.item_id
                lines.append(
                    f'Deploy/overwrite: semantic model "{name}" ({sm_id}) in {workspace}'
                )
                report_lines, err = _bound_report_lines(item.target.workspace_id, sm_id)
                if err:
                    lines.append(f"  {err}")
                elif not report_lines:
                    lines.append("  (no other reports found in this workspace)")
                else:
                    for report_line in report_lines:
                        lines.append(f"  affects: {report_line}")
        lines.append("Are you sure?")
        confirm_or_abort("\n".join(lines), silent=False)


def confirm_delete_semantic_model(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm semantic model delete; list downstream reports the service will remove."""
    if silent or not items:
        return

    lines = [
        "About to delete semantic model(s).",
        "Fabric deletes upstream models and destroys dependent reports:",
    ]
    with busy(status_detail("semantic-model", "resolving targets and dependents")):
        for item in items:
            assert item.target is not None and item.target.item_id is not None
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            name = semantic_model_display_name(client, item.target)
            sm_id = item.target.item_id
            lines.append(f'Delete: semantic model "{name}" ({sm_id}) in {workspace}')
            report_lines, err = _bound_report_lines(item.target.workspace_id, sm_id)
            if err:
                lines.append(f"  {err}")
            elif not report_lines:
                lines.append("  (no dependent reports found in this workspace)")
            else:
                for report_line in report_lines:
                    lines.append(f"  also deletes: {report_line}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_semantic_model_role_member_changes(
    rows: list[tuple[str, str, str, str, str]],
    *,
    action: str,
    silent: bool,
) -> None:
    """Confirm RLS role member add/remove for each affected model.

    *rows* are ``(workspace_label, model_name, model_id, role_name, member_name)``.
    *action* is ``add`` or ``remove``.
    """
    if silent or not rows:
        return
    verb = "Add" if action == "add" else "Remove"
    prep = "to" if action == "add" else "from"
    lines = [
        f"About to {action} semantic-model role member(s) via XMLA:",
    ]
    for workspace, model_name, model_id, role_name, member_name in rows:
        lines.append(
            f'{verb}: member "{member_name}" {prep} role "{role_name}" '
            f'on semantic model "{model_name}" ({model_id}) in {workspace}'
        )
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def report_display_name(client: FabricClient, target: Target) -> str:
    """Return Fabric item display name for a report target (fallback: id)."""
    if target.item_id is None:
        return "Report"
    try:
        data = client.get_item(target.workspace_id, target.item_id)
    except FabricApiError:
        return target.item_id
    name = data.get("displayName") or data.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return target.item_id


def resolve_report_download_files(
    client: FabricClient,
    items: list[WorkItem],
) -> list[WorkItem]:
    """Fill missing download destinations from remote names (``.Report``)."""
    if not items:
        return items
    if all(item.file is not None for item in items):
        return _normalize_explicit_download_files(
            items, _normalize_report_download_path
        )
    if any(item.file is not None for item in items):
        raise ValueError(
            "download work items must all omit --target path or all provide it"
        )

    with busy(status_detail("report", "resolving download paths")):
        names = [
            report_display_name(client, item.target)
            if item.target is not None
            else "Report"
            for item in items
        ]
        paths = default_download_paths(names, extension=".Report")
    return [
        WorkItem(item.target, path, origin=item.origin)
        for item, path in zip(items, paths, strict=True)
    ]


def confirm_download_overwrites_report(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm before overwriting existing local report folders or ``.pbix`` files."""
    if silent or not items:
        return
    existing = [item for item in items if item.file is not None and item.file.exists()]
    if not existing:
        return

    lines = ["About to overwrite local path(s):"]
    with busy(status_detail("report", "resolving targets")):
        for item in existing:
            assert item.target is not None and item.file is not None
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            remote = resolve_item_name(client, item.target)
            lines.append(f"  - {item.file}  (from {remote} in {workspace})")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_deploy_actions_report(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
    display_names: list[str] | None = None,
    independent: bool = False,
    join_model_paths: list[Path | None] | None = None,
) -> None:
    """Confirm create/overwrite of reports; name joined models and shared consumers."""
    from fabric_tools.report.definition import display_name_from_path, is_pbix_path

    if silent or not items:
        return

    creates = [
        item for item in items if item.target is not None and item.target.is_create
    ]
    overwrites = [
        item
        for item in items
        if item.target is not None and item.target.item_id is not None
    ]

    if creates:
        lines = ["About to create report(s):"]
        with busy(status_detail("report", "resolving targets")):
            for index, item in enumerate(items):
                if item.target is None or not item.target.is_create:
                    continue
                workspace = resolve_workspace_name(client, item.target.workspace_id)
                if (
                    display_names
                    and index < len(display_names)
                    and display_names[index]
                ):
                    name = display_names[index]
                elif item.file is not None:
                    name = display_name_from_path(item.file)
                else:
                    name = "Report"
                source = (
                    str(item.file)
                    if item.file is not None
                    else (
                        f"origin {item.origin.label()}"
                        if item.origin is not None
                        else "?"
                    )
                )
                lines.append(f"  - report '{name}' in {workspace} from {source}")
                model_path = None
                if join_model_paths and index < len(join_model_paths):
                    model_path = join_model_paths[index]
                if (
                    not independent
                    and item.file is not None
                    and not is_pbix_path(item.file)
                    and model_path is not None
                ):
                    lines.append(
                        f"    + joined semantic model '{model_path.name}' "
                        f"({model_path})"
                    )
                elif (
                    not independent
                    and item.file is not None
                    and is_pbix_path(item.file)
                ):
                    lines.append("    + embedded semantic model from .pbix")
        lines.append("Are you sure?")
        confirm_or_abort("\n".join(lines), silent=False)

    if overwrites:
        lines = ["About to overwrite remote report(s):"]
        with busy(status_detail("report", "resolving targets and impact")):
            for index, item in enumerate(items):
                if item.target is None or item.target.item_id is None:
                    continue
                workspace = resolve_workspace_name(client, item.target.workspace_id)
                name = report_display_name(client, item.target)
                rid = item.target.item_id
                lines.append(
                    f'Deploy/overwrite: report "{name}" ({rid}) in {workspace}'
                )
                model_path = None
                if join_model_paths and index < len(join_model_paths):
                    model_path = join_model_paths[index]
                dataset_id = _report_dataset_id(item.target.workspace_id, rid)
                if not independent and (
                    model_path is not None
                    or (item.file is not None and is_pbix_path(item.file))
                    or dataset_id
                ):
                    if dataset_id:
                        lines.append(f'  also updates semantic model id "{dataset_id}"')
                        report_lines, err = _bound_report_lines(
                            item.target.workspace_id, dataset_id
                        )
                        if err:
                            lines.append(f"  {err}")
                        elif report_lines:
                            for report_line in report_lines:
                                if rid not in report_line:
                                    lines.append(f"  affects: {report_line}")
                    elif model_path is not None:
                        lines.append(f"  also updates joined model {model_path}")
                    else:
                        lines.append(
                            "  also updates embedded semantic model from .pbix"
                        )
        lines.append("Are you sure?")
        confirm_or_abort("\n".join(lines), silent=False)


def confirm_delete_report(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm report delete; note orphan upstream semantic model when known."""
    if silent or not items:
        return

    lines = [
        "About to delete report(s).",
        "Deleting a report leaves its semantic model intact:",
    ]
    with busy(status_detail("report", "resolving targets")):
        for item in items:
            assert item.target is not None and item.target.item_id is not None
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            name = report_display_name(client, item.target)
            rid = item.target.item_id
            lines.append(f'Delete: report "{name}" ({rid}) in {workspace}')
            dataset_id = _report_dataset_id(item.target.workspace_id, rid)
            if dataset_id:
                model_label = dataset_id
                try:
                    meta = client.get_item(item.target.workspace_id, dataset_id)
                    model_name = meta.get("displayName") or meta.get("name")
                    if isinstance(model_name, str) and model_name.strip():
                        model_label = f"{model_name.strip()}"
                except FabricApiError:
                    pass
                lines.append(f'  leaves semantic model "{model_label}" ({dataset_id})')
            else:
                lines.append("  (bound semantic model unknown / unbound)")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def _report_dataset_id(workspace_id: str, report_id: str) -> str | None:
    """Best-effort datasetId for a report via Power BI."""
    from fabric_tools.powerbi_client import PowerBiApiError, PowerBiClient

    try:
        with PowerBiClient() as pbi:
            pbi.ensure_authenticated()
            report = pbi.get_report(workspace_id, report_id)
    except PowerBiApiError:
        return None
    except Exception:  # noqa: BLE001
        return None
    dataset_id = report.get("datasetId")
    return str(dataset_id) if dataset_id else None


def pipeline_display_name(client: FabricClient, target: Target) -> str:
    """Return Fabric item display name for a DataPipeline target (fallback: id)."""
    if target.item_id is None:
        return "DataPipeline"
    try:
        data = client.get_item(target.workspace_id, target.item_id)
    except FabricApiError:
        return target.item_id
    name = data.get("displayName") or data.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return target.item_id


def resolve_pipeline_download_files(
    client: FabricClient,
    items: list[WorkItem],
) -> list[WorkItem]:
    """Fill missing download destinations from remote names (``.DataPipeline``)."""
    if not items:
        return items
    if all(item.file is not None for item in items):
        return _normalize_explicit_download_files(items, detect_pipeline_path)
    if any(item.file is not None for item in items):
        raise ValueError(
            "download work items must all omit --target path or all provide it"
        )

    with busy(status_detail("pipeline", "resolving download paths")):
        names = [
            pipeline_display_name(client, item.target)
            if item.target is not None
            else "DataPipeline"
            for item in items
        ]
        paths = default_download_paths(names, extension=".DataPipeline")
    return [
        WorkItem(item.target, path, origin=item.origin)
        for item, path in zip(items, paths, strict=True)
    ]


def confirm_download_overwrites_pipeline(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm before overwriting existing local DataPipeline folders."""
    if silent:
        return
    existing = [
        item
        for item in items
        if item.target is not None and item.file is not None and _path_exists(item.file)
    ]
    if not existing:
        return

    lines = ["About to overwrite local path(s):"]
    with busy(status_detail("pipeline", "resolving targets")):
        for item in existing:
            assert item.target is not None and item.file is not None
            remote = resolve_item_name(client, item.target)
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            lines.append(f"  - local `{item.file}` <- remote {remote} in {workspace}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_deploy_actions_pipeline(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
    display_names: list[str] | None = None,
    include_schedules: bool = False,
    guid_map_line: str | None = None,
) -> None:
    """Confirm create or remote overwrite before DataPipeline deploy."""
    from fabric_tools.pipeline.definition import (
        display_name_from_path as pipeline_name_from_path,
    )

    if silent or not items:
        return

    first = items[0].target
    if first is None:
        return

    if first.is_create:
        lines = ["About to create pipeline(s):"]
        with busy(status_detail("pipeline", "resolving targets")):
            for index, item in enumerate(items):
                assert item.target is not None
                workspace = resolve_workspace_name(client, item.target.workspace_id)
                name: str | None = None
                if (
                    display_names
                    and index < len(display_names)
                    and display_names[index]
                ):
                    name = display_names[index]
                if not name:
                    if item.file is not None:
                        name = pipeline_name_from_path(item.file)
                    elif item.origin is not None:
                        name = resolve_item_name(client, item.origin)
                    else:
                        name = "(unnamed)"
                source = _source_phrase_fabric(client, item)
                lines.append(f"  - '{name}' in {workspace}{source}")
        if include_schedules:
            lines.append(
                "Source .schedules will be included when present "
                "(create has no existing schedule to preserve)."
            )
        else:
            lines.append(
                "Pipeline-only: .schedules will not be sent "
                "(use --include-schedules / -i to sync schedules)."
            )
        if guid_map_line:
            lines.append(guid_map_line)
        lines.append("Are you sure?")
        confirm_or_abort("\n".join(lines), silent=False)
        return

    lines = ["About to overwrite remote pipeline(s):"]
    with busy(status_detail("pipeline", "resolving targets")):
        for item in items:
            assert item.target is not None
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            remote = resolve_item_name(client, item.target)
            source = _source_phrase_fabric(client, item, prefix=" with")
            lines.append(f"  - {remote} in {workspace}{source}")
    if include_schedules:
        lines.append(
            "Source .schedules will replace remote schedules "
            "(or clear them if the source has none)."
        )
    else:
        lines.append(
            "Pipeline-only: each target's existing .schedules will be reattached "
            "so remote schedules stay untouched "
            "(use --include-schedules / -i to sync schedules from the source)."
        )
    if guid_map_line:
        lines.append(guid_map_line)
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_delete_pipeline(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm soft-delete of remote DataPipeline items."""
    if silent or not items:
        return

    lines = ["About to delete remote pipeline(s):"]
    with busy(status_detail("pipeline", "resolving targets")):
        for item in items:
            assert item.target is not None
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            remote = resolve_item_name(client, item.target)
            lines.append(f"  - {remote} in {workspace}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def udf_display_name(client: FabricClient, target: Target) -> str:
    """Return Fabric item display name for a UDF target (fallback: id)."""
    if target.item_id is None:
        return "UserDataFunction"
    try:
        data = client.get_item(target.workspace_id, target.item_id)
    except FabricApiError:
        return target.item_id
    name = data.get("displayName") or data.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return target.item_id


def resolve_udf_download_files(
    client: FabricClient,
    items: list[WorkItem],
) -> list[WorkItem]:
    """Fill missing download destinations from remote names (``*.UserDataFunction``)."""
    if not items:
        return items
    if all(item.file is not None for item in items):
        return _normalize_explicit_download_files(items, detect_udf_folder)
    if any(item.file is not None for item in items):
        raise ValueError(
            "download work items must all omit --target path or all provide it"
        )

    with busy(status_detail("udf", "resolving download paths")):
        names = [
            udf_display_name(client, item.target)
            if item.target is not None
            else "UserDataFunction"
            for item in items
        ]
        paths = default_download_paths(names, extension=".UserDataFunction")
    return [
        WorkItem(item.target, path, origin=item.origin)
        for item, path in zip(items, paths, strict=True)
    ]


def confirm_download_overwrites_udf(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm before overwriting existing local User Data Function folders."""
    if silent:
        return
    existing = [
        item
        for item in items
        if item.target is not None and item.file is not None and _path_exists(item.file)
    ]
    if not existing:
        return

    lines = ["About to overwrite local path(s):"]
    with busy(status_detail("udf", "resolving targets")):
        for item in existing:
            assert item.target is not None and item.file is not None
            remote = resolve_item_name(client, item.target)
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            lines.append(f"  - local `{item.file}` <- remote {remote} in {workspace}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_deploy_actions_udf(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
    display_names: list[str] | None = None,
    guid_map_line: str | None = None,
) -> None:
    """Confirm create or remote overwrite before User Data Function deploy."""
    from fabric_tools.udf.definition import display_name_from_path as udf_name_from_path

    if silent or not items:
        return

    first = items[0].target
    if first is None:
        return

    if first.is_create:
        lines = ["About to create User Data Function(s):"]
        with busy(status_detail("udf", "resolving targets")):
            for index, item in enumerate(items):
                assert item.target is not None
                workspace = resolve_workspace_name(client, item.target.workspace_id)
                name: str | None = None
                if (
                    display_names
                    and index < len(display_names)
                    and display_names[index]
                ):
                    name = display_names[index]
                if not name:
                    if item.file is not None:
                        name = udf_name_from_path(item.file)
                    elif item.origin is not None:
                        name = resolve_item_name(client, item.origin)
                    else:
                        name = "(unnamed)"
                source = _source_phrase_fabric(client, item)
                lines.append(f"  - '{name}' in {workspace}{source}")
        if guid_map_line:
            lines.append(guid_map_line)
        lines.append("Are you sure?")
        confirm_or_abort("\n".join(lines), silent=False)
        return

    lines = ["About to overwrite remote User Data Function(s):"]
    with busy(status_detail("udf", "resolving targets")):
        for item in items:
            assert item.target is not None
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            remote = resolve_item_name(client, item.target)
            source = _source_phrase_fabric(client, item, prefix=" with")
            lines.append(f"  - {remote} in {workspace}{source}")
    if guid_map_line:
        lines.append(guid_map_line)
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def confirm_delete_udf(
    client: FabricClient,
    items: list[WorkItem],
    *,
    silent: bool,
) -> None:
    """Confirm soft-delete of remote User Data Function items."""
    if silent or not items:
        return

    lines = ["About to delete remote User Data Function(s):"]
    with busy(status_detail("udf", "resolving targets")):
        for item in items:
            assert item.target is not None
            workspace = resolve_workspace_name(client, item.target.workspace_id)
            remote = resolve_item_name(client, item.target)
            lines.append(f"  - {remote} in {workspace}")
    lines.append("Are you sure?")
    confirm_or_abort("\n".join(lines), silent=False)


def _source_phrase_fabric(
    client: FabricClient,
    item: WorkItem,
    *,
    prefix: str = " from",
) -> str:
    if item.file is not None:
        return f"{prefix} `{item.file}`"
    if item.origin is not None:
        origin_name = resolve_item_name(client, item.origin)
        origin_ws = resolve_workspace_name(client, item.origin.workspace_id)
        return f"{prefix} origin {origin_name} in {origin_ws}"
    return ""


def _source_phrase_powerbi(
    client: PowerBiClient,
    item: WorkItem,
    *,
    prefix: str = " from",
) -> str:
    if item.file is not None:
        return f"{prefix} `{item.file}`"
    if item.origin is not None:
        origin_name = resolve_powerbi_dataflow_name(client, item.origin)
        origin_ws = resolve_powerbi_group_name(client, item.origin.workspace_id)
        return f"{prefix} origin {origin_name} in {origin_ws}"
    return ""


def _source_phrase_paginated_report(
    client: PowerBiClient,
    item: WorkItem,
    *,
    prefix: str = " from",
) -> str:
    if item.file is not None:
        return f"{prefix} `{item.file}`"
    if item.origin is not None:
        origin_name = resolve_powerbi_paginated_report_name(client, item.origin)
        origin_ws = resolve_powerbi_group_name(client, item.origin.workspace_id)
        return f"{prefix} origin {origin_name} in {origin_ws}"
    return ""


def _path_exists(path: Path) -> bool:
    return path.exists()

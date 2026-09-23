"""Shared sync orchestration helpers (auth, readonly, inputs, manifests, exits)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import typer

from fabric_tools.auth import AuthError
from fabric_tools.colours import FG_OK, print_error_panel, print_warn_panel
from fabric_tools.confirm import (
    CONFIRM_ABORT_MESSAGE,
    ConfirmationAborted,
    abort_interrupt_message,
)
from fabric_tools.display import format_local_path
from fabric_tools.exit_codes import EXIT_API, EXIT_OK, EXIT_USER
from fabric_tools.manifest import (
    KIND_DATAFLOW,
    KIND_DATAFLOW_GEN1,
    KIND_ENVIRONMENT,
    KIND_NOTEBOOK,
    KIND_ORG_APP,
    KIND_PAGINATED_REPORT,
    KIND_PIPELINE,
    KIND_REPORT,
    KIND_SEMANTIC_MODEL,
    KIND_UDF,
    KIND_VARIABLE_LIBRARY,
    ManifestError,
    delete_targets_from_manifest,
    item_id_overrides_from_results,
    load_manifest,
    manifest_from_work_items,
    resolve_manifest_path,
    save_manifest,
    semantic_model_id_overrides_from_results,
    semantic_model_ids_from_manifest,
    work_items_from_manifest,
)
from fabric_tools.parsing import (
    CommandMode,
    ParseError,
    WorkItem,
    build_work_items,
    build_work_items_from_cli,
)
from fabric_tools.readonly import (
    ReadOnlyError,
    ensure_command_allowed,
    ensure_mutation_allowed,
    ensure_setup_mutation_allowed,
)

if TYPE_CHECKING:
    from fabric_tools.notebook.compare import CompareResult
    from fabric_tools.notebook.ops import OpResult


def _exit_error(message: str, *, code: int = EXIT_USER) -> NoReturn:
    """Print a shared Error panel and exit (never returns)."""
    text = (message or "").strip() or "Operation failed."
    print_error_panel(text)
    raise typer.Exit(code=code)


def _exit_warn(message: str, *, code: int = EXIT_USER) -> NoReturn:
    """Print a shared Warning panel and exit (never returns)."""
    text = (message or "").strip() or CONFIRM_ABORT_MESSAGE
    print_warn_panel(text)
    raise typer.Exit(code=code)


def _exit_user_abort(exc: BaseException | None = None) -> NoReturn:
    """Exit for ``ConfirmationAborted`` or mid-prompt ``typer.Abort``."""
    if isinstance(exc, ConfirmationAborted):
        _exit_warn(str(exc))
    if isinstance(exc, typer.Abort):
        _exit_warn(abort_interrupt_message())
    _exit_warn(CONFIRM_ABORT_MESSAGE)


def _resolve_deploy_guid_maps(
    remap_values: list[str] | None,
    *,
    n_targets: int,
    has_targets: bool,
    manifest: str | None = None,
    expected_kind: str | None = None,
) -> list:
    """Load GUID maps for deploy / deploy dry-run.

    Precedence: CLI ``--remap`` / ``-r`` wins when set; otherwise pack/entry
    ``remap`` path refs from *manifest* (when *expected_kind* is set).
    """
    from fabric_tools.guid_map import GuidMapError, load_guid_map, resolve_guid_maps
    from fabric_tools.manifest import entry_guid_maps_from_manifest

    if remap_values:
        try:
            if has_targets and n_targets > 0:
                return resolve_guid_maps(remap_values, n_targets)
            # Validate maps load even when dry-run has no targets yet.
            for raw in remap_values:
                for piece in raw.split(","):
                    piece = piece.strip()
                    if piece:
                        load_guid_map(piece)
            return []
        except GuidMapError as exc:
            _exit_error(str(exc))

    if manifest and expected_kind and has_targets and n_targets > 0:
        try:
            path = resolve_manifest_path(manifest)
            if not path.is_file():
                return []
            loaded = load_manifest(path)
            return entry_guid_maps_from_manifest(loaded, expected_kind=expected_kind)
        except ManifestError as exc:
            _exit_error(str(exc))
    return []


def _enforce_readonly_command(mode: CommandMode, *, dry_run: bool) -> None:
    """Exit if ``FABRIC_TOOLS_READONLY`` blocks this mode (unless dry-run)."""
    try:
        ensure_command_allowed(mode, dry_run=dry_run)
    except ReadOnlyError as exc:
        _exit_error(str(exc))


def _enforce_readonly_setup(action: str) -> None:
    """Exit if ``FABRIC_TOOLS_READONLY`` blocks a mutating setup action."""
    try:
        ensure_setup_mutation_allowed(action)
    except ReadOnlyError as exc:
        _exit_error(str(exc))


def _enforce_readonly_mutation(action: str, *, dry_run: bool) -> None:
    """Exit if ``FABRIC_TOOLS_READONLY`` blocks a named mutation (unless dry-run)."""
    try:
        ensure_mutation_allowed(action, dry_run=dry_run)
    except ReadOnlyError as exc:
        _exit_error(str(exc))


def _fail_auth(exc: AuthError) -> NoReturn:
    """Print a short auth failure and exit (never returns)."""
    if exc.canceled:
        _exit_warn(str(exc))
    _exit_error(str(exc))


def _authenticate_client(client: object) -> None:
    """Run ``ensure_authenticated`` with a clean CLI exit on ``AuthError``."""
    try:
        client.ensure_authenticated()  # type: ignore[attr-defined]
    except AuthError as exc:
        _fail_auth(exc)


def _resolve_sync_inputs(
    mode: CommandMode,
    *,
    expected_kind: str,
    target_values: list[str] | None,
    origin_values: list[str] | None,
    dry_run: bool,
    names: list[str | None] | list[str] | None,
    manifest: str | None,
    deploy_create_only: bool = False,
    name_filter: str | None = None,
    list_items_fn: Callable[[str], list] | None = None,
    kind_label: str | None = None,
) -> tuple[list[WorkItem], list[str | None] | list[str] | None, bool, bool, bool]:
    """Resolve polymorphic --origin/--target from CLI and/or a deployment manifest.

    When CLI remotes include ``workspaceId:*``, *list_items_fn* must list items for
    one workspace (already authenticated). *name_filter* applies to every wildcard
    side in the invocation.
    """
    from fabric_tools.parsing import (
        build_work_items_from_classified,
        classify_cli_endpoints,
    )
    from fabric_tools.remote_expand import (
        ExpandError,
        classified_has_wildcard,
        expand_classified,
        validate_filter_usage,
    )

    has_cli = bool(target_values or origin_values)
    manifest_names: list[str | None] | None = None

    if mode is CommandMode.DELETE:
        if origin_values:
            raise ParseError("delete only accepts remote --target selector(s)")
        if target_values:
            classified = classify_cli_endpoints(
                origin_values=None,
                target_values=target_values,
                mode=mode,
            )
            validate_filter_usage(
                name_filter, has_wildcard=classified_has_wildcard(classified)
            )
            if classified_has_wildcard(classified):
                if list_items_fn is None or not kind_label:
                    raise ParseError(
                        "workspace:* requires an authenticated client before expand"
                    )
                try:
                    classified = expand_classified(
                        classified,
                        list_items=list_items_fn,
                        name_filter=name_filter,
                        kind_label=kind_label,
                    )
                except ExpandError as exc:
                    raise ParseError(str(exc)) from exc
            items = build_work_items_from_classified(
                mode,
                classified,
                dry_run=dry_run,
                deploy_create_only=deploy_create_only,
            )
            return items, None, True, False, False
        if name_filter:
            validate_filter_usage(name_filter, has_wildcard=False)
        if manifest:
            path = resolve_manifest_path(manifest)
            loaded = load_manifest(path)
            items = delete_targets_from_manifest(loaded, expected_kind=expected_kind)
            return items, None, True, False, False
        items = build_work_items(mode, [], [], dry_run=dry_run)
        return items, None, False, False, False

    if has_cli:
        classified = classify_cli_endpoints(
            origin_values=origin_values,
            target_values=target_values,
            mode=mode,
        )
        validate_filter_usage(
            name_filter, has_wildcard=classified_has_wildcard(classified)
        )
        if classified_has_wildcard(classified):
            if deploy_create_only:
                raise ParseError(
                    "dataflow-gen1 deploy does not support workspace:* "
                    "(create-only; use concrete workspace targets)"
                )
            if list_items_fn is None or not kind_label:
                raise ParseError(
                    "workspace:* requires an authenticated client before expand"
                )
            try:
                classified = expand_classified(
                    classified,
                    list_items=list_items_fn,
                    name_filter=name_filter,
                    kind_label=kind_label,
                )
            except ExpandError as exc:
                raise ParseError(str(exc)) from exc
        elif name_filter:
            validate_filter_usage(name_filter, has_wildcard=False)
        items = build_work_items_from_classified(
            mode,
            classified,
            dry_run=dry_run,
            deploy_create_only=deploy_create_only,
        )
        has_targets = any(item.target is not None for item in items)
        has_files = any(item.file is not None for item in items)
        has_origins = any(item.origin is not None for item in items)
        return items, names, has_targets, has_files, has_origins

    if name_filter:
        validate_filter_usage(name_filter, has_wildcard=False)

    if manifest:
        path = resolve_manifest_path(manifest)
        loaded = load_manifest(path)
        loaded_items, manifest_names = work_items_from_manifest(
            loaded, expected_kind=expected_kind
        )
        targets = [item.target for item in loaded_items if item.target is not None]
        files = [item.file for item in loaded_items if item.file is not None]
        origins = [item.origin for item in loaded_items if item.origin is not None]
        if len(targets) != len(loaded_items):
            raise ManifestError(
                f"manifest {path} has incomplete entries (need workspace on each)"
            )
        if files and origins:
            raise ManifestError(
                f"manifest {path} mixes file and origin entries in one load"
            )
        if not files and not origins:
            raise ManifestError(
                f"manifest {path} has incomplete entries (need file or origin on each)"
            )
        if files and len(files) != len(loaded_items):
            raise ManifestError(
                f"manifest {path} has incomplete entries (need file on each)"
            )
        if origins and len(origins) != len(loaded_items):
            raise ManifestError(
                f"manifest {path} has incomplete entries (need origin on each)"
            )
        items = build_work_items(
            mode,
            targets,
            files,
            origins=origins,
            dry_run=dry_run,
            deploy_create_only=deploy_create_only,
        )
        effective_names: list[str | None] | list[str] | None = (
            names if names else manifest_names
        )
        return items, effective_names, bool(targets), bool(files), bool(origins)

    items = build_work_items_from_cli(
        mode,
        origin_values=None,
        target_values=None,
        dry_run=dry_run,
        deploy_create_only=deploy_create_only,
    )
    return items, names, False, False, False


def _cli_needs_wildcard_expand(
    *,
    origin_values: list[str] | None,
    target_values: list[str] | None,
    mode: CommandMode,
    name_filter: str | None,
) -> bool:
    """Validate ``--filter`` and report whether ``workspaceId:*`` needs API expand."""
    from fabric_tools.parsing import classify_cli_endpoints
    from fabric_tools.remote_expand import (
        classified_has_wildcard,
        validate_filter_usage,
    )

    if not (origin_values or target_values):
        validate_filter_usage(name_filter, has_wildcard=False)
        return False
    classified = classify_cli_endpoints(
        origin_values=origin_values,
        target_values=target_values,
        mode=mode,
    )
    has_wildcard = classified_has_wildcard(classified)
    validate_filter_usage(name_filter, has_wildcard=has_wildcard)
    return has_wildcard


def _list_items_fn_for_kind(kind: str, client: object) -> Callable[[str], list]:
    """Return a workspace→item-list callback for wildcard expansion."""
    fabric_types = {
        KIND_NOTEBOOK: "Notebook",
        KIND_DATAFLOW: "Dataflow",
        KIND_PIPELINE: "DataPipeline",
        KIND_UDF: "UserDataFunction",
        KIND_REPORT: "Report",
        KIND_ORG_APP: "OrgApp",
        KIND_VARIABLE_LIBRARY: "VariableLibrary",
        KIND_ENVIRONMENT: "Environment",
        KIND_SEMANTIC_MODEL: "SemanticModel",
    }
    if kind == KIND_DATAFLOW_GEN1:

        def list_gen1(workspace_id: str) -> list:
            return list(client.list_dataflows(workspace_id))  # type: ignore[attr-defined]

        return list_gen1
    if kind == KIND_PAGINATED_REPORT:

        def list_paginated(workspace_id: str) -> list:
            return [
                row
                for row in client.list_reports(workspace_id)  # type: ignore[attr-defined]
                if row.get("reportType") == "PaginatedReport"
            ]

        return list_paginated
    item_type = fabric_types.get(kind)
    if item_type is None:
        raise ParseError(f"workspace:* is not supported for kind {kind}")

    def list_fabric(workspace_id: str) -> list:
        return list(client.list_items(workspace_id, type=item_type))  # type: ignore[attr-defined]

    return list_fabric


_KIND_EXPAND_LABELS = {
    KIND_NOTEBOOK: "Notebook",
    KIND_DATAFLOW: "Dataflow",
    KIND_DATAFLOW_GEN1: "dataflow-gen1",
    KIND_PIPELINE: "DataPipeline",
    KIND_UDF: "UserDataFunction",
    KIND_REPORT: "Report",
    KIND_ORG_APP: "OrgApp",
    KIND_VARIABLE_LIBRARY: "VariableLibrary",
    KIND_ENVIRONMENT: "Environment",
    KIND_SEMANTIC_MODEL: "SemanticModel",
    KIND_PAGINATED_REPORT: "PaginatedReport",
}


def _resolve_dataflow_inputs(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    origin_values: list[str] | None,
    dry_run: bool,
    names: list[str | None] | list[str] | None,
    manifest: str | None,
    name_filter: str | None = None,
    list_items_fn: Callable[[str], list] | None = None,
    kind_label: str | None = None,
) -> tuple[list[WorkItem], list[str | None] | list[str] | None, bool, bool, bool]:
    """Resolve KIND_DATAFLOW endpoints from CLI and/or a deployment manifest."""
    return _resolve_sync_inputs(
        mode,
        expected_kind=KIND_DATAFLOW,
        target_values=target_values,
        origin_values=origin_values,
        dry_run=dry_run,
        names=names,
        manifest=manifest,
        deploy_create_only=False,
        name_filter=name_filter,
        list_items_fn=list_items_fn,
        kind_label=kind_label,
    )


def _resolve_dataflow_deploy_names(
    items: list[WorkItem],
    names: list[str | None] | list[str] | None,
) -> list[str]:
    from fabric_tools.dataflow.definition import display_name_from_path

    if names and len(names) not in {1, len(items)}:
        raise ParseError(
            f"--name count must be 1 or match target count ({len(items)}); "
            f"got {len(names)}"
        )
    resolved: list[str] = []
    for index, item in enumerate(items):
        chosen: str | None = None
        if names:
            chosen = names[0] if len(names) == 1 else names[index]
        if chosen:
            resolved.append(chosen)
        elif item.file is not None:
            resolved.append(display_name_from_path(item.file))
        else:
            resolved.append("")
    return resolved


def _resolve_org_app_inputs(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    origin_values: list[str] | None,
    dry_run: bool,
    names: list[str | None] | list[str] | None,
    manifest: str | None,
    name_filter: str | None = None,
    list_items_fn: Callable[[str], list] | None = None,
    kind_label: str | None = None,
) -> tuple[list[WorkItem], list[str | None] | list[str] | None, bool, bool, bool]:
    """Resolve KIND_ORG_APP endpoints from CLI and/or a deployment manifest."""
    return _resolve_sync_inputs(
        mode,
        expected_kind=KIND_ORG_APP,
        target_values=target_values,
        origin_values=origin_values,
        dry_run=dry_run,
        names=names,
        manifest=manifest,
        deploy_create_only=False,
        name_filter=name_filter,
        list_items_fn=list_items_fn,
        kind_label=kind_label,
    )


def _resolve_org_app_deploy_names(
    items: list[WorkItem],
    names: list[str | None] | list[str] | None,
) -> list[str]:
    from fabric_tools.org_app.definition import display_name_from_path

    if names and len(names) not in {1, len(items)}:
        raise ParseError(
            f"--name count must be 1 or match target count ({len(items)}); "
            f"got {len(names)}"
        )
    resolved: list[str] = []
    for index, item in enumerate(items):
        chosen: str | None = None
        if names:
            chosen = names[0] if len(names) == 1 else names[index]
        if chosen:
            resolved.append(chosen)
        elif item.file is not None:
            resolved.append(display_name_from_path(item.file))
        else:
            resolved.append("")
    return resolved


def _resolve_variable_library_inputs(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    origin_values: list[str] | None,
    dry_run: bool,
    names: list[str | None] | list[str] | None,
    manifest: str | None,
    name_filter: str | None = None,
    list_items_fn: Callable[[str], list] | None = None,
    kind_label: str | None = None,
) -> tuple[list[WorkItem], list[str | None] | list[str] | None, bool, bool, bool]:
    """Resolve KIND_VARIABLE_LIBRARY endpoints from CLI and/or a deployment manifest."""
    return _resolve_sync_inputs(
        mode,
        expected_kind=KIND_VARIABLE_LIBRARY,
        target_values=target_values,
        origin_values=origin_values,
        dry_run=dry_run,
        names=names,
        manifest=manifest,
        deploy_create_only=False,
        name_filter=name_filter,
        list_items_fn=list_items_fn,
        kind_label=kind_label,
    )


def _resolve_variable_library_deploy_names(
    items: list[WorkItem],
    names: list[str | None] | list[str] | None,
) -> list[str]:
    from fabric_tools.variable_library.definition import display_name_from_path

    if names and len(names) not in {1, len(items)}:
        raise ParseError(
            f"--name count must be 1 or match target count ({len(items)}); "
            f"got {len(names)}"
        )
    resolved: list[str] = []
    for index, item in enumerate(items):
        chosen: str | None = None
        if names:
            chosen = names[0] if len(names) == 1 else names[index]
        if chosen:
            resolved.append(chosen)
        elif item.file is not None:
            resolved.append(display_name_from_path(item.file))
        else:
            resolved.append("")
    return resolved


def _resolve_environment_inputs(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    origin_values: list[str] | None,
    dry_run: bool,
    names: list[str | None] | list[str] | None,
    manifest: str | None,
    name_filter: str | None = None,
    list_items_fn: Callable[[str], list] | None = None,
    kind_label: str | None = None,
) -> tuple[list[WorkItem], list[str | None] | list[str] | None, bool, bool, bool]:
    """Resolve KIND_ENVIRONMENT endpoints from CLI and/or a deployment manifest."""
    return _resolve_sync_inputs(
        mode,
        expected_kind=KIND_ENVIRONMENT,
        target_values=target_values,
        origin_values=origin_values,
        dry_run=dry_run,
        names=names,
        manifest=manifest,
        deploy_create_only=False,
        name_filter=name_filter,
        list_items_fn=list_items_fn,
        kind_label=kind_label,
    )


def _resolve_environment_deploy_names(
    items: list[WorkItem],
    names: list[str | None] | list[str] | None,
) -> list[str]:
    from fabric_tools.environment.definition import display_name_from_path

    if names and len(names) not in {1, len(items)}:
        raise ParseError(
            f"--name count must be 1 or match target count ({len(items)}); "
            f"got {len(names)}"
        )
    resolved: list[str] = []
    for index, item in enumerate(items):
        chosen: str | None = None
        if names:
            chosen = names[0] if len(names) == 1 else names[index]
        if chosen:
            resolved.append(chosen)
        elif item.file is not None:
            resolved.append(display_name_from_path(item.file))
        else:
            resolved.append("")
    return resolved


def _resolve_semantic_model_inputs(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    origin_values: list[str] | None,
    dry_run: bool,
    names: list[str | None] | list[str] | None,
    manifest: str | None,
    name_filter: str | None = None,
    list_items_fn: Callable[[str], list] | None = None,
    kind_label: str | None = None,
) -> tuple[list[WorkItem], list[str | None] | list[str] | None, bool, bool, bool]:
    """Resolve KIND_SEMANTIC_MODEL endpoints from CLI and/or a deployment manifest."""
    return _resolve_sync_inputs(
        mode,
        expected_kind=KIND_SEMANTIC_MODEL,
        target_values=target_values,
        origin_values=origin_values,
        dry_run=dry_run,
        names=names,
        manifest=manifest,
        deploy_create_only=False,
        name_filter=name_filter,
        list_items_fn=list_items_fn,
        kind_label=kind_label,
    )


def _resolve_semantic_model_deploy_names(
    items: list[WorkItem],
    names: list[str | None] | list[str] | None,
) -> list[str]:
    from fabric_tools.semantic_model.definition import display_name_from_path

    if names and len(names) not in {1, len(items)}:
        raise ParseError(
            f"--name count must be 1 or match target count ({len(items)}); "
            f"got {len(names)}"
        )
    resolved: list[str] = []
    for index, item in enumerate(items):
        chosen: str | None = None
        if names:
            chosen = names[0] if len(names) == 1 else names[index]
        if chosen:
            resolved.append(chosen)
        elif item.file is not None:
            resolved.append(display_name_from_path(item.file))
        else:
            resolved.append("")
    return resolved


def _resolve_report_inputs(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    origin_values: list[str] | None,
    dry_run: bool,
    names: list[str | None] | list[str] | None,
    manifest: str | None,
    name_filter: str | None = None,
    list_items_fn: Callable[[str], list] | None = None,
    kind_label: str | None = None,
) -> tuple[
    list[WorkItem],
    list[str | None] | list[str] | None,
    bool,
    bool,
    bool,
    list[str | None] | None,
]:
    """Resolve KIND_REPORT endpoints from CLI and/or a deployment manifest."""
    sm_ids: list[str | None] | None = None
    if manifest and not (target_values or origin_values):
        path = resolve_manifest_path(manifest)
        loaded = load_manifest(path)
        sm_ids = semantic_model_ids_from_manifest(loaded)
    items, resolved_names, has_targets, has_files, has_origins = _resolve_sync_inputs(
        mode,
        expected_kind=KIND_REPORT,
        target_values=target_values,
        origin_values=origin_values,
        dry_run=dry_run,
        names=names,
        manifest=manifest,
        deploy_create_only=False,
        name_filter=name_filter,
        list_items_fn=list_items_fn,
        kind_label=kind_label,
    )
    return items, resolved_names, has_targets, has_files, has_origins, sm_ids


def _resolve_report_deploy_names(
    items: list[WorkItem],
    names: list[str | None] | list[str] | None,
) -> list[str]:
    from fabric_tools.report.definition import display_name_from_path

    if names and len(names) not in {1, len(items)}:
        raise ParseError(
            f"--name count must be 1 or match target count ({len(items)}); "
            f"got {len(names)}"
        )
    resolved: list[str] = []
    for index, item in enumerate(items):
        chosen: str | None = None
        if names:
            chosen = names[0] if len(names) == 1 else names[index]
        if chosen:
            resolved.append(chosen)
        elif item.file is not None:
            resolved.append(display_name_from_path(item.file))
        else:
            resolved.append("")
    return resolved


def _resolve_dataflow_gen1_inputs(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    origin_values: list[str] | None,
    dry_run: bool,
    names: list[str | None] | list[str] | None,
    manifest: str | None,
    name_filter: str | None = None,
    list_items_fn: Callable[[str], list] | None = None,
    kind_label: str | None = None,
) -> tuple[list[WorkItem], list[str | None] | list[str] | None, bool, bool, bool]:
    """Resolve KIND_DATAFLOW_GEN1 endpoints from CLI and/or a deployment manifest."""
    return _resolve_sync_inputs(
        mode,
        expected_kind=KIND_DATAFLOW_GEN1,
        target_values=target_values,
        origin_values=origin_values,
        dry_run=dry_run,
        names=names,
        manifest=manifest,
        deploy_create_only=True,
        name_filter=name_filter,
        list_items_fn=list_items_fn,
        kind_label=kind_label,
    )


def _resolve_dataflow_gen1_deploy_names(
    items: list[WorkItem],
    names: list[str | None] | list[str] | None,
) -> list[str]:
    from fabric_tools.dataflow_gen1.definition import (
        display_name_from_model,
        load_model,
    )

    if names and len(names) not in {1, len(items)}:
        raise ParseError(
            f"--name count must be 1 or match target count ({len(items)}); "
            f"got {len(names)}"
        )
    resolved: list[str] = []
    for index, item in enumerate(items):
        chosen: str | None = None
        if names:
            chosen = names[0] if len(names) == 1 else names[index]
        if chosen:
            resolved.append(chosen)
        elif item.file is not None:
            resolved.append(display_name_from_model(load_model(item.file)))
        else:
            resolved.append("")
    return resolved


def _resolve_paginated_report_inputs(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    origin_values: list[str] | None,
    dry_run: bool,
    names: list[str | None] | list[str] | None,
    manifest: str | None,
    name_filter: str | None = None,
    list_items_fn: Callable[[str], list] | None = None,
    kind_label: str | None = None,
) -> tuple[list[WorkItem], list[str | None] | list[str] | None, bool, bool, bool]:
    """Resolve KIND_PAGINATED_REPORT endpoints from CLI and/or a deployment manifest."""
    return _resolve_sync_inputs(
        mode,
        expected_kind=KIND_PAGINATED_REPORT,
        target_values=target_values,
        origin_values=origin_values,
        dry_run=dry_run,
        names=names,
        manifest=manifest,
        deploy_create_only=False,
        name_filter=name_filter,
        list_items_fn=list_items_fn,
        kind_label=kind_label,
    )


def _resolve_paginated_report_deploy_names(
    items: list[WorkItem],
    names: list[str | None] | list[str] | None,
) -> list[str]:
    from fabric_tools.paginated_report.definition import display_name_from_path

    if names and len(names) not in {1, len(items)}:
        raise ParseError(
            f"--name count must be 1 or match target count ({len(items)}); "
            f"got {len(names)}"
        )
    resolved: list[str] = []
    for index, item in enumerate(items):
        chosen: str | None = None
        if names:
            chosen = names[0] if len(names) == 1 else names[index]
        if chosen:
            resolved.append(chosen)
        elif item.file is not None:
            resolved.append(display_name_from_path(item.file))
        else:
            resolved.append("")
    return resolved


def _resolve_pipeline_inputs(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    origin_values: list[str] | None,
    dry_run: bool,
    names: list[str | None] | list[str] | None,
    manifest: str | None,
    name_filter: str | None = None,
    list_items_fn: Callable[[str], list] | None = None,
    kind_label: str | None = None,
) -> tuple[list[WorkItem], list[str | None] | list[str] | None, bool, bool, bool]:
    """Resolve KIND_PIPELINE endpoints from CLI and/or a deployment manifest."""
    return _resolve_sync_inputs(
        mode,
        expected_kind=KIND_PIPELINE,
        target_values=target_values,
        origin_values=origin_values,
        dry_run=dry_run,
        names=names,
        manifest=manifest,
        deploy_create_only=False,
        name_filter=name_filter,
        list_items_fn=list_items_fn,
        kind_label=kind_label,
    )


def _resolve_pipeline_deploy_names(
    items: list[WorkItem],
    names: list[str | None] | list[str] | None,
) -> list[str]:
    from fabric_tools.pipeline.definition import display_name_from_path

    if names and len(names) not in {1, len(items)}:
        raise ParseError(
            f"--name count must be 1 or match target count ({len(items)}); "
            f"got {len(names)}"
        )
    resolved: list[str] = []
    for index, item in enumerate(items):
        chosen: str | None = None
        if names:
            chosen = names[0] if len(names) == 1 else names[index]
        if chosen:
            resolved.append(chosen)
        elif item.file is not None:
            resolved.append(display_name_from_path(item.file))
        else:
            resolved.append("")
    return resolved


def _resolve_udf_inputs(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    origin_values: list[str] | None,
    dry_run: bool,
    names: list[str | None] | list[str] | None,
    manifest: str | None,
    name_filter: str | None = None,
    list_items_fn: Callable[[str], list] | None = None,
    kind_label: str | None = None,
) -> tuple[list[WorkItem], list[str | None] | list[str] | None, bool, bool, bool]:
    """Resolve KIND_UDF endpoints from CLI and/or a deployment manifest."""
    return _resolve_sync_inputs(
        mode,
        expected_kind=KIND_UDF,
        target_values=target_values,
        origin_values=origin_values,
        dry_run=dry_run,
        names=names,
        manifest=manifest,
        deploy_create_only=False,
        name_filter=name_filter,
        list_items_fn=list_items_fn,
        kind_label=kind_label,
    )


def _resolve_udf_deploy_names(
    items: list[WorkItem],
    names: list[str | None] | list[str] | None,
) -> list[str]:
    from fabric_tools.udf.definition import display_name_from_path

    if names and len(names) not in {1, len(items)}:
        raise ParseError(
            f"--name count must be 1 or match target count ({len(items)}); "
            f"got {len(names)}"
        )
    resolved: list[str] = []
    for index, item in enumerate(items):
        chosen: str | None = None
        if names:
            chosen = names[0] if len(names) == 1 else names[index]
        if chosen:
            resolved.append(chosen)
        elif item.file is not None:
            resolved.append(display_name_from_path(item.file))
        else:
            resolved.append("")
    return resolved


def _notify_success(
    on_success: Callable[..., None] | None,
    items: list[WorkItem],
    *,
    display_names: list[str] | None,
    op_results: list[OpResult] | None = None,
    compare_results: list[CompareResult] | None = None,
) -> None:
    if on_success is None:
        return
    if op_results is not None and not all(result.ok for result in op_results):
        return
    if compare_results is not None and not all(result.ok for result in compare_results):
        return
    on_success(
        items,
        display_names=display_names,
        op_results=op_results,
        compare_results=compare_results,
    )


def _resolve_notebook_inputs(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    origin_values: list[str] | None,
    dry_run: bool,
    names: list[str | None] | list[str] | None,
    manifest: str | None,
    name_filter: str | None = None,
    list_items_fn: Callable[[str], list] | None = None,
    kind_label: str | None = None,
) -> tuple[list[WorkItem], list[str | None] | list[str] | None, bool, bool, bool]:
    """Resolve KIND_NOTEBOOK endpoints from CLI and/or a deployment manifest."""
    return _resolve_sync_inputs(
        mode,
        expected_kind=KIND_NOTEBOOK,
        target_values=target_values,
        origin_values=origin_values,
        dry_run=dry_run,
        names=names,
        manifest=manifest,
        deploy_create_only=False,
        name_filter=name_filter,
        list_items_fn=list_items_fn,
        kind_label=kind_label,
    )


def _remap_paths_from_existing_manifest(
    manifest: str,
    *,
    n_entries: int,
) -> tuple[Path | None, list[Path | None] | None]:
    """Load pack/entry remap paths from an existing ``.ftdep`` for rewrite.

    Returns ``(pack_remap, entry_remaps)``. Entry remaps are returned only when
    the loaded entry count matches *n_entries* so they stay aligned with items.
    """
    path = resolve_manifest_path(manifest)
    if not path.is_file():
        return None, None
    try:
        loaded = load_manifest(path)
    except ManifestError:
        return None, None
    pack_remap = loaded.remap
    if len(loaded.entries) != n_entries:
        return pack_remap, None
    return pack_remap, [entry.remap for entry in loaded.entries]


def _write_manifest_after_success(
    manifest: str | None,
    items: list[WorkItem],
    *,
    display_names: list[str] | None,
    op_results: list[OpResult] | None = None,
    compare_results: list[CompareResult] | None = None,
    kind: str = KIND_NOTEBOOK,
    semantic_model_ids: list[str | None] | None = None,
) -> None:
    """Rewrite ``.ftdep`` when ``-m`` is set and the operation or dry-run succeeded.

    Skips the write (and the “Wrote manifest” line) when content is unchanged.
    Preserves pack-level and per-entry ``remap`` path refs from the existing file.
    """
    if not manifest:
        return
    if op_results is not None and not all(result.ok for result in op_results):
        return
    if compare_results is not None and not all(result.ok for result in compare_results):
        return

    overrides = (
        item_id_overrides_from_results(op_results) if op_results is not None else None
    )
    sm_overrides = semantic_model_ids
    if op_results is not None and kind == KIND_REPORT:
        from_results = semantic_model_id_overrides_from_results(op_results)
        if any(from_results):
            sm_overrides = from_results
    pack_remap, entry_remaps = _remap_paths_from_existing_manifest(
        manifest, n_entries=len(items)
    )
    try:
        built = manifest_from_work_items(
            items,
            kind=kind,
            display_names=display_names,
            item_id_overrides=overrides,
            semantic_model_id_overrides=sm_overrides,
            remap=pack_remap,
            entry_remaps=entry_remaps,
        )
        path, written = save_manifest(manifest, built)
    except ManifestError as exc:
        print_warn_panel(f"manifest not written: {exc}")
        return
    if written:
        typer.secho(f"Wrote manifest: {format_local_path(path)}", fg=FG_OK)


def _print_op_results(results: list[OpResult]) -> None:
    for result in results:
        if result.ok:
            typer.secho(result.message, fg=FG_OK)
        else:
            print_error_panel(result.message)


def _exit_from_op_results(results: list[OpResult]) -> None:
    if all(result.ok for result in results):
        raise typer.Exit(code=EXIT_OK)
    raise typer.Exit(code=EXIT_API)


def _print_compare_results(results: list[CompareResult]) -> None:
    from fabric_tools.compare_print import print_compare_results

    print_compare_results(results)


def _exit_from_compare_results(results: list[CompareResult]) -> None:
    if any(not result.ok for result in results):
        raise typer.Exit(code=EXIT_API)
    if any(not result.identical for result in results):
        raise typer.Exit(code=EXIT_USER)
    raise typer.Exit(code=EXIT_OK)


def _resolve_deploy_names(
    items: list,
    names: list[str | None] | list[str] | None,
) -> list[str]:
    from fabric_tools.notebook.definition import display_name_from_path

    if names and len(names) not in {1, len(items)}:
        raise ParseError(
            f"--name count must be 1 or match target count ({len(items)}); got {len(names)}"
        )
    resolved: list[str] = []
    for index, item in enumerate(items):
        chosen: str | None = None
        if names:
            chosen = names[0] if len(names) == 1 else names[index]
        if chosen:
            resolved.append(chosen)
        elif item.file is not None:
            resolved.append(display_name_from_path(item.file))
        else:
            # Origin create resolves display name at deploy time via get_item.
            resolved.append("")
    return resolved

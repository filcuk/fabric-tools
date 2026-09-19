"""Orchestration for notebook sync commands."""

from __future__ import annotations

from collections.abc import Callable

import typer

from fabric_tools.auth import AuthError
from fabric_tools.colours import FG_ID, FG_OK, print_error_panel
from fabric_tools.exit_codes import EXIT_API, EXIT_OK, EXIT_USER
from fabric_tools.manifest import (
    KIND_NOTEBOOK,
    ManifestError,
)
from fabric_tools.parsing import CommandMode, ParseError
from fabric_tools.sync.common import (
    _KIND_EXPAND_LABELS,
    _authenticate_client,
    _cli_needs_wildcard_expand,
    _enforce_readonly_command,
    _exit_error,
    _exit_from_compare_results,
    _exit_from_op_results,
    _exit_warn,
    _fail_auth,
    _list_items_fn_for_kind,
    _notify_success,
    _print_compare_results,
    _print_op_results,
    _resolve_deploy_guid_maps,
    _resolve_deploy_names,
    _resolve_notebook_inputs,
    _write_manifest_after_success,
)


def run_notebook_command(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    silent: bool,
    dry_run: bool,
    name_filter: str | None = None,
    origin_values: list[str] | None = None,
    names: list[str | None] | list[str] | None = None,
    cells: list[str] | None = None,
    ignore_outputs: bool = False,
    manifest: str | None = None,
    remap_values: list[str] | None = None,
    guid_maps_override: list[dict[str, str] | None] | None = None,
    on_success: Callable[..., None] | None = None,
) -> None:
    """Shared entry used by CLI commands and the interactive wizard.

    *on_success* is called after a completed successful operation or dry-run (all
    checks/ops/compare results ok), before the process exit code is raised — used
    by interactive mode to offer saving a deployment manifest.
    """
    _enforce_readonly_command(mode, dry_run=dry_run)
    from fabric_tools.client import FabricClient
    from fabric_tools.confirm import (
        ConfirmationAborted,
        confirm_delete_actions,
        confirm_deploy_actions,
        confirm_download_overwrites,
        resolve_notebook_download_files,
    )
    from fabric_tools.guid_map import guid_map_confirm_line
    from fabric_tools.notebook.cells import (
        CellSelectionError,
        parse_cell_indices,
        validate_cells_usage,
    )
    from fabric_tools.notebook.compare import run_compare_batch
    from fabric_tools.notebook.ops import (
        run_delete_batch,
        run_deploy_batch,
        run_download_batch,
    )
    from fabric_tools.status import busy, status_detail
    from fabric_tools.validate import run_dry_run

    if remap_values and mode is not CommandMode.DEPLOY:
        _exit_error("--remap / -r is only valid with deploy")

    expand_client = None
    try:
        cell_indices = parse_cell_indices(cells)
        needs_expand = _cli_needs_wildcard_expand(
            origin_values=origin_values,
            target_values=target_values,
            mode=mode,
            name_filter=name_filter,
        )
        if needs_expand:
            with busy(status_detail("auth", "authenticating")):
                expand_client = FabricClient()
                _authenticate_client(expand_client)
            list_fn = _list_items_fn_for_kind(KIND_NOTEBOOK, expand_client)
            with busy(status_detail("notebook", "expanding selectors")):
                items, resolved_names, has_targets, has_files, has_origins = (
                    _resolve_notebook_inputs(
                        mode,
                        target_values=target_values,
                        origin_values=origin_values,
                        dry_run=dry_run,
                        names=names,
                        manifest=manifest,
                        name_filter=name_filter,
                        list_items_fn=list_fn,
                        kind_label=_KIND_EXPAND_LABELS[KIND_NOTEBOOK],
                    )
                )
        else:
            items, resolved_names, has_targets, has_files, has_origins = (
                _resolve_notebook_inputs(
                    mode,
                    target_values=target_values,
                    origin_values=origin_values,
                    dry_run=dry_run,
                    names=names,
                    manifest=manifest,
                    name_filter=name_filter,
                )
            )
        validate_cells_usage(mode, items, cell_indices, dry_run=dry_run)
    except (ParseError, ManifestError, CellSelectionError) as exc:
        _exit_error(str(exc))

    guid_map_specs = (
        []
        if guid_maps_override is not None
        else (
            _resolve_deploy_guid_maps(
                remap_values,
                n_targets=len(items),
                has_targets=has_targets,
                manifest=manifest,
                expected_kind=KIND_NOTEBOOK,
            )
            if mode is CommandMode.DEPLOY
            else []
        )
    )
    guid_maps = (
        list(guid_maps_override)
        if guid_maps_override is not None
        else [spec.mapping if spec is not None else None for spec in guid_map_specs]
    )
    map_line = (
        None
        if guid_maps_override is not None
        else (guid_map_confirm_line(guid_map_specs) if guid_map_specs else None)
    )
    if guid_maps_override is not None and any(guid_maps_override):
        map_line = "Will apply GUID remap map(s) from pack orchestration."

    if dry_run:
        client: FabricClient | None = expand_client
        try:
            if (has_targets or has_origins) and client is None:
                with busy(status_detail("auth", "authenticating")):
                    client = FabricClient()
                    _authenticate_client(client)
            with busy(status_detail("notebook", "checking")):
                results = run_dry_run(
                    mode,
                    items,
                    client=client,
                    has_targets=has_targets,
                    has_files=has_files,
                    has_origins=has_origins,
                    cell_indices=cell_indices,
                )
        except AuthError as exc:
            _fail_auth(exc)
        except Exception as exc:  # noqa: BLE001 - surface auth/client failures cleanly
            _exit_error(f"dry-run failed: {exc}", code=EXIT_API)
        finally:
            if client is not None:
                client.close()

        failed = False
        for result in results:
            if result.ok:
                typer.secho(result.message, fg=FG_OK)
            else:
                print_error_panel(result.message)
                failed = True
        if (remap_values or map_line) and not failed:
            if map_line:
                typer.secho(f"remap ok: {map_line}", fg=FG_OK)
            else:
                typer.secho("remap ok: GUID remap file(s) valid", fg=FG_OK)
        if not failed and has_targets and (has_files or has_origins):
            try:
                display_names = (
                    _resolve_deploy_names(items, resolved_names)
                    if mode is CommandMode.DEPLOY
                    else None
                )
            except ParseError as exc:
                _exit_error(str(exc))
            _write_manifest_after_success(
                manifest,
                items,
                display_names=display_names,
                kind=KIND_NOTEBOOK,
            )
            _notify_success(
                on_success,
                items,
                display_names=display_names,
            )
        raise typer.Exit(code=EXIT_USER if failed else EXIT_OK)

    try:
        display_names = (
            _resolve_deploy_names(items, resolved_names)
            if mode is CommandMode.DEPLOY
            else None
        )
    except ParseError as exc:
        _exit_error(str(exc))

    client = expand_client
    if client is None:
        with busy(status_detail("auth", "authenticating")):
            client = FabricClient()
            _authenticate_client(client)
    try:
        if mode is CommandMode.DOWNLOAD:
            items = resolve_notebook_download_files(client, items)
            confirm_download_overwrites(client, items, silent=silent)
            with busy(status_detail("notebook", "downloading")):
                op_results = run_download_batch(client, items)
            _print_op_results(op_results)
            _write_manifest_after_success(
                manifest,
                items,
                display_names=None,
                op_results=op_results,
                kind=KIND_NOTEBOOK,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                op_results=op_results,
            )
            _exit_from_op_results(op_results)
        elif mode is CommandMode.DEPLOY:
            confirm_deploy_actions(
                client,
                items,
                silent=silent,
                display_names=display_names,
                cell_indices=cell_indices,
                guid_map_line=map_line,
            )
            with busy(status_detail("notebook", "deploying")):
                op_results = run_deploy_batch(
                    client,
                    items,
                    display_names=display_names,
                    cell_indices=cell_indices,
                    guid_maps=guid_maps or None,
                )
            _print_op_results(op_results)
            for result in op_results:
                if (
                    result.ok
                    and result.workspace_id
                    and result.item_id
                    and "created" in result.message
                ):
                    typer.secho(
                        f"GUID: {result.workspace_id}:{result.item_id}",
                        fg=FG_ID,
                    )
            _write_manifest_after_success(
                manifest,
                items,
                display_names=display_names,
                op_results=op_results,
                kind=KIND_NOTEBOOK,
            )
            _notify_success(
                on_success,
                items,
                display_names=display_names,
                op_results=op_results,
            )
            _exit_from_op_results(op_results)
        elif mode is CommandMode.COMPARE:
            with busy(status_detail("notebook", "comparing")):
                compare_results = run_compare_batch(
                    client,
                    items,
                    ignore_outputs=ignore_outputs,
                )
            _print_compare_results(compare_results)
            _write_manifest_after_success(
                manifest,
                items,
                display_names=None,
                compare_results=compare_results,
                kind=KIND_NOTEBOOK,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                compare_results=compare_results,
            )
            _exit_from_compare_results(compare_results)
        elif mode is CommandMode.DELETE:
            confirm_delete_actions(client, items, silent=silent)
            with busy(status_detail("notebook", "deleting")):
                op_results = run_delete_batch(client, items)
            _print_op_results(op_results)
            _notify_success(
                on_success,
                items,
                display_names=None,
                op_results=op_results,
            )
            _exit_from_op_results(op_results)
        else:
            _exit_error(f"Unknown mode: {mode}")
    except ConfirmationAborted as exc:
        _exit_warn(str(exc))
    except typer.Exit:
        raise
    except AuthError as exc:
        _fail_auth(exc)
    except Exception as exc:  # noqa: BLE001
        _exit_error(str(exc), code=EXIT_API)
    finally:
        client.close()

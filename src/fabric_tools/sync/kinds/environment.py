"""Orchestration for Environment sync commands."""

from __future__ import annotations

from collections.abc import Callable

import typer

from fabric_tools.auth import AuthError
from fabric_tools.colours import FG_ID, FG_OK, print_error_panel
from fabric_tools.exit_codes import EXIT_API, EXIT_OK, EXIT_USER
from fabric_tools.manifest import (
    KIND_ENVIRONMENT,
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
    _resolve_environment_deploy_names,
    _resolve_environment_inputs,
    _write_manifest_after_success,
)


def run_environment_command(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    silent: bool,
    dry_run: bool,
    name_filter: str | None = None,
    origin_values: list[str] | None = None,
    names: list[str | None] | list[str] | None = None,
    manifest: str | None = None,
    on_success: Callable[..., None] | None = None,
) -> None:
    """Shared entry for Environment CLI commands and the interactive wizard."""
    _enforce_readonly_command(mode, dry_run=dry_run)
    from fabric_tools.client import FabricClient
    from fabric_tools.confirm import (
        ConfirmationAborted,
        confirm_delete_environment,
        confirm_deploy_actions_environment,
        confirm_download_overwrites_environment,
        resolve_environment_download_files,
    )
    from fabric_tools.environment.compare import (
        run_compare_batch as run_environment_compare,
    )
    from fabric_tools.environment.ops import run_delete_batch as run_environment_delete
    from fabric_tools.environment.ops import run_deploy_batch as run_environment_deploy
    from fabric_tools.environment.ops import (
        run_download_batch as run_environment_download,
    )
    from fabric_tools.status import busy, status_detail
    from fabric_tools.validate import run_dry_run_environment

    expand_client = None
    try:
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
            list_fn = _list_items_fn_for_kind(KIND_ENVIRONMENT, expand_client)
            with busy(status_detail("environment", "expanding selectors")):
                items, resolved_names, has_targets, has_files, has_origins = (
                    _resolve_environment_inputs(
                        mode,
                        target_values=target_values,
                        origin_values=origin_values,
                        dry_run=dry_run,
                        names=names,
                        manifest=manifest,
                        name_filter=name_filter,
                        list_items_fn=list_fn,
                        kind_label=_KIND_EXPAND_LABELS[KIND_ENVIRONMENT],
                    )
                )
        else:
            items, resolved_names, has_targets, has_files, has_origins = (
                _resolve_environment_inputs(
                    mode,
                    target_values=target_values,
                    origin_values=origin_values,
                    dry_run=dry_run,
                    names=names,
                    manifest=manifest,
                    name_filter=name_filter,
                )
            )
    except (ParseError, ManifestError) as exc:
        _exit_error(str(exc))

    if dry_run:
        client: FabricClient | None = expand_client
        try:
            if (has_targets or has_origins) and client is None:
                with busy(status_detail("auth", "authenticating")):
                    client = FabricClient()
                    _authenticate_client(client)
            with busy(status_detail("environment", "checking")):
                results = run_dry_run_environment(
                    mode,
                    items,
                    client=client,
                    has_targets=has_targets,
                    has_files=has_files,
                    has_origins=has_origins,
                )
        except AuthError as exc:
            _fail_auth(exc)
        except Exception as exc:  # noqa: BLE001
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
        if not failed and has_targets and (has_files or has_origins):
            try:
                display_names = (
                    _resolve_environment_deploy_names(items, resolved_names)
                    if mode is CommandMode.DEPLOY
                    else None
                )
            except ParseError as exc:
                _exit_error(str(exc))
            _write_manifest_after_success(
                manifest,
                items,
                display_names=display_names,
                kind=KIND_ENVIRONMENT,
            )
            _notify_success(on_success, items, display_names=display_names)
        raise typer.Exit(code=EXIT_USER if failed else EXIT_OK)

    try:
        display_names = (
            _resolve_environment_deploy_names(items, resolved_names)
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
            items = resolve_environment_download_files(client, items)
            confirm_download_overwrites_environment(client, items, silent=silent)
            with busy(status_detail("environment", "downloading")):
                op_results = run_environment_download(client, items)
            _print_op_results(op_results)  # type: ignore[arg-type]
            _write_manifest_after_success(
                manifest,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
                kind=KIND_ENVIRONMENT,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
            )
            _exit_from_op_results(op_results)  # type: ignore[arg-type]
        elif mode is CommandMode.DEPLOY:
            confirm_deploy_actions_environment(
                client, items, silent=silent, display_names=display_names
            )
            with busy(status_detail("environment", "deploying")):
                op_results = run_environment_deploy(
                    client, items, display_names=display_names
                )
            _print_op_results(op_results)  # type: ignore[arg-type]
            for result in op_results:
                if (
                    result.ok
                    and result.workspace_id
                    and result.item_id
                    and "created" in result.message
                ):
                    typer.secho(
                        f"GUID: {result.workspace_id}:{result.item_id}", fg=FG_ID
                    )
            _write_manifest_after_success(
                manifest,
                items,
                display_names=display_names,
                op_results=op_results,  # type: ignore[arg-type]
                kind=KIND_ENVIRONMENT,
            )
            _notify_success(
                on_success,
                items,
                display_names=display_names,
                op_results=op_results,  # type: ignore[arg-type]
            )
            _exit_from_op_results(op_results)  # type: ignore[arg-type]
        elif mode is CommandMode.COMPARE:
            with busy(status_detail("environment", "comparing")):
                compare_results = run_environment_compare(client, items)
            _print_compare_results(compare_results)  # type: ignore[arg-type]
            _write_manifest_after_success(
                manifest,
                items,
                display_names=None,
                compare_results=compare_results,  # type: ignore[arg-type]
                kind=KIND_ENVIRONMENT,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                compare_results=compare_results,  # type: ignore[arg-type]
            )
            _exit_from_compare_results(compare_results)  # type: ignore[arg-type]
        elif mode is CommandMode.DELETE:
            confirm_delete_environment(client, items, silent=silent)
            with busy(status_detail("environment", "deleting")):
                op_results = run_environment_delete(client, items)
            _print_op_results(op_results)  # type: ignore[arg-type]
            _notify_success(
                on_success,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
            )
            _exit_from_op_results(op_results)  # type: ignore[arg-type]
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

"""Orchestration for report sync commands."""

from __future__ import annotations

from collections.abc import Callable

import typer

from fabric_tools.auth import AuthError
from fabric_tools.colours import FG_ID, FG_OK, print_error_panel
from fabric_tools.exit_codes import EXIT_API, EXIT_OK, EXIT_USER
from fabric_tools.manifest import (
    KIND_REPORT,
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
    _resolve_report_deploy_names,
    _resolve_report_inputs,
    _write_manifest_after_success,
)


def run_report_command(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    silent: bool,
    dry_run: bool,
    name_filter: str | None = None,
    origin_values: list[str] | None = None,
    names: list[str | None] | list[str] | None = None,
    manifest: str | None = None,
    independent: bool = False,
    on_success: Callable[..., None] | None = None,
) -> None:
    """Shared entry for report CLI commands and the interactive wizard."""
    _enforce_readonly_command(mode, dry_run=dry_run)
    from fabric_tools.client import FabricClient
    from fabric_tools.confirm import (
        ConfirmationAborted,
        confirm_delete_report,
        confirm_deploy_actions_report,
        confirm_download_overwrites_report,
        resolve_report_download_files,
    )
    from fabric_tools.report.compare import (
        run_compare_batch as run_report_compare,
    )
    from fabric_tools.report.definition import (
        DefinitionError as ReportDefinitionError,
    )
    from fabric_tools.report.definition import (
        is_pbix_path,
        packable_local_model,
    )
    from fabric_tools.report.ops import (
        run_delete_batch as run_report_delete,
    )
    from fabric_tools.report.ops import (
        run_deploy_batch as run_report_deploy,
    )
    from fabric_tools.report.ops import (
        run_download_batch as run_report_download,
    )
    from fabric_tools.status import busy, status_detail
    from fabric_tools.validate import run_dry_run_report

    if independent and mode is CommandMode.DELETE:
        _exit_error(
            "--independent / -i is not used on report delete "
            "(delete always removes the report only)."
        )

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
            list_fn = _list_items_fn_for_kind(KIND_REPORT, expand_client)
            with busy(status_detail("report", "expanding selectors")):
                items, resolved_names, has_targets, has_files, has_origins, sm_ids = (
                    _resolve_report_inputs(
                        mode,
                        target_values=target_values,
                        origin_values=origin_values,
                        dry_run=dry_run,
                        names=names,
                        manifest=manifest,
                        name_filter=name_filter,
                        list_items_fn=list_fn,
                        kind_label=_KIND_EXPAND_LABELS[KIND_REPORT],
                    )
                )
        else:
            items, resolved_names, has_targets, has_files, has_origins, sm_ids = (
                _resolve_report_inputs(
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
            with busy(status_detail("report", "checking")):
                results = run_dry_run_report(
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
                    _resolve_report_deploy_names(items, resolved_names)
                    if mode is CommandMode.DEPLOY
                    else None
                )
            except ParseError as exc:
                _exit_error(str(exc))
            _write_manifest_after_success(
                manifest,
                items,
                display_names=display_names,
                kind=KIND_REPORT,
                semantic_model_ids=sm_ids,
            )
            _notify_success(
                on_success,
                items,
                display_names=display_names,
            )
        raise typer.Exit(code=EXIT_USER if failed else EXIT_OK)

    try:
        display_names = (
            _resolve_report_deploy_names(items, resolved_names)
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
            items = resolve_report_download_files(client, items)
            confirm_download_overwrites_report(client, items, silent=silent)
            with busy(status_detail("report", "downloading")):
                op_results = run_report_download(client, items, independent=independent)
            _print_op_results(op_results)  # type: ignore[arg-type]
            _write_manifest_after_success(
                manifest,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
                kind=KIND_REPORT,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                op_results=op_results,  # type: ignore[arg-type]
            )
            _exit_from_op_results(op_results)  # type: ignore[arg-type]
        elif mode is CommandMode.DEPLOY:
            join_model_paths: list[object | None] = []
            for item in items:
                if independent or item.file is None or is_pbix_path(item.file):
                    join_model_paths.append(None)
                    continue
                try:
                    join_model_paths.append(packable_local_model(item.file))
                except ReportDefinitionError:
                    join_model_paths.append(None)
            confirm_deploy_actions_report(
                client,
                items,
                silent=silent,
                display_names=display_names,
                independent=independent,
                join_model_paths=join_model_paths,  # type: ignore[arg-type]
            )
            with busy(status_detail("report", "deploying")):
                op_results = run_report_deploy(
                    client,
                    items,
                    display_names=display_names,
                    independent=independent,
                    semantic_model_ids=sm_ids,
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
                        f"GUID: {result.workspace_id}:{result.item_id}",
                        fg=FG_ID,
                    )
                    sm = getattr(result, "semantic_model_id", None)
                    if sm:
                        typer.secho(
                            f"semanticModelId: {sm}",
                            fg=FG_ID,
                        )
            _write_manifest_after_success(
                manifest,
                items,
                display_names=display_names,
                op_results=op_results,  # type: ignore[arg-type]
                kind=KIND_REPORT,
            )
            _notify_success(
                on_success,
                items,
                display_names=display_names,
                op_results=op_results,  # type: ignore[arg-type]
            )
            _exit_from_op_results(op_results)  # type: ignore[arg-type]
        elif mode is CommandMode.COMPARE:
            with busy(status_detail("report", "comparing")):
                compare_results = run_report_compare(
                    client, items, independent=independent
                )
            _print_compare_results(compare_results)  # type: ignore[arg-type]
            _write_manifest_after_success(
                manifest,
                items,
                display_names=None,
                compare_results=compare_results,  # type: ignore[arg-type]
                kind=KIND_REPORT,
            )
            _notify_success(
                on_success,
                items,
                display_names=None,
                compare_results=compare_results,  # type: ignore[arg-type]
            )
            _exit_from_compare_results(compare_results)  # type: ignore[arg-type]
        elif mode is CommandMode.DELETE:
            confirm_delete_report(client, items, silent=silent)
            with busy(status_detail("report", "deleting")):
                op_results = run_report_delete(client, items)
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

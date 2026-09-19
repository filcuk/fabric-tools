"""Orchestration for report sync commands."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import typer

from fabric_tools.colours import FG_ID
from fabric_tools.manifest import KIND_REPORT
from fabric_tools.parsing import CommandMode
from fabric_tools.sync.common import (
    _exit_error,
    _resolve_report_deploy_names,
    _resolve_report_inputs,
)
from fabric_tools.sync.orchestrator import (
    KindSpec,
    ResolvedBundle,
    SyncRequest,
    run_sync_command,
)


def _resolve_report_bundle(*args: Any, **kwargs: Any) -> ResolvedBundle:
    items, names, has_targets, has_files, has_origins, sm_ids = _resolve_report_inputs(
        *args, **kwargs
    )
    return ResolvedBundle(
        items=items,
        resolved_names=names,
        has_targets=has_targets,
        has_files=has_files,
        has_origins=has_origins,
        extras={"sm_ids": sm_ids},
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
    from fabric_tools.client import FabricClient
    from fabric_tools.confirm import (
        confirm_delete_report,
        confirm_deploy_actions_report,
        confirm_download_overwrites_report,
        resolve_report_download_files,
    )
    from fabric_tools.report.compare import run_compare_batch as run_report_compare
    from fabric_tools.report.definition import (
        DefinitionError as ReportDefinitionError,
    )
    from fabric_tools.report.definition import is_pbix_path, packable_local_model
    from fabric_tools.report.ops import run_delete_batch as run_report_delete
    from fabric_tools.report.ops import run_deploy_batch as run_report_deploy
    from fabric_tools.report.ops import run_download_batch as run_report_download
    from fabric_tools.validate import run_dry_run_report

    def validate_flags(req: SyncRequest) -> None:
        if independent and req.mode is CommandMode.DELETE:
            _exit_error(
                "--independent / -i is not used on report delete "
                "(delete always removes the report only)."
            )

    def prepare_deploy(req: SyncRequest, _client: object) -> None:
        join_model_paths: list[object | None] = []
        for item in req.items:
            if independent or item.file is None or is_pbix_path(item.file):
                join_model_paths.append(None)
                continue
            try:
                join_model_paths.append(packable_local_model(item.file))
            except ReportDefinitionError:
                join_model_paths.append(None)
        req.extras["join_model_paths"] = join_model_paths

    def download_kwargs(_req: SyncRequest) -> dict:
        return {"independent": independent}

    def deploy_confirm_kwargs(req: SyncRequest) -> dict:
        return {
            "independent": independent,
            "join_model_paths": req.extras.get("join_model_paths"),
        }

    def deploy_kwargs(req: SyncRequest) -> dict:
        return {
            "independent": independent,
            "semantic_model_ids": req.extras.get("sm_ids"),
        }

    def compare_kwargs(_req: SyncRequest) -> dict:
        return {"independent": independent}

    def manifest_kwargs(req: SyncRequest) -> dict:
        # Dry-run uses resolved sm_ids; execute deploy picks SM ids from op results.
        if req.dry_run:
            return {"semantic_model_ids": req.extras.get("sm_ids")}
        return {}

    def echo_created(result: object) -> None:
        if not (
            getattr(result, "ok", False)
            and getattr(result, "workspace_id", None)
            and getattr(result, "item_id", None)
            and "created" in getattr(result, "message", "")
        ):
            return
        typer.secho(
            f"GUID: {result.workspace_id}:{result.item_id}",
            fg=FG_ID,
        )
        sm = getattr(result, "semantic_model_id", None)
        if sm:
            typer.secho(f"semanticModelId: {sm}", fg=FG_ID)

    spec = KindSpec(
        kind=KIND_REPORT,
        status_label="report",
        make_client=FabricClient,
        resolve_inputs=_resolve_report_bundle,
        resolve_deploy_names=_resolve_report_deploy_names,
        run_dry_run=run_dry_run_report,
        resolve_download_files=resolve_report_download_files,
        confirm_download=confirm_download_overwrites_report,
        confirm_deploy=confirm_deploy_actions_report,
        confirm_delete=confirm_delete_report,
        run_download=run_report_download,
        run_deploy=run_report_deploy,
        run_compare=run_report_compare,
        run_delete=run_report_delete,
        validate_flags=validate_flags,
        prepare_deploy=prepare_deploy,
        download_kwargs=download_kwargs,
        deploy_confirm_kwargs=deploy_confirm_kwargs,
        deploy_kwargs=deploy_kwargs,
        compare_kwargs=compare_kwargs,
        manifest_kwargs=manifest_kwargs,
        echo_created=echo_created,
    )
    run_sync_command(
        spec,
        SyncRequest(
            mode=mode,
            target_values=target_values,
            silent=silent,
            dry_run=dry_run,
            name_filter=name_filter,
            origin_values=origin_values,
            names=names,
            manifest=manifest,
            on_success=on_success,
        ),
    )

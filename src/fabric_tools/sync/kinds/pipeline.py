"""Orchestration for DataPipeline sync commands."""

from __future__ import annotations

from collections.abc import Callable

from fabric_tools.manifest import KIND_PIPELINE
from fabric_tools.parsing import CommandMode
from fabric_tools.sync.common import (
    _resolve_pipeline_deploy_names,
    _resolve_pipeline_inputs,
)
from fabric_tools.sync.orchestrator import (
    KindSpec,
    SyncRequest,
    remap_dry_run_notes,
    require_remap_deploy_only,
    run_sync_command,
    wrap_five_tuple_resolve,
)


def run_pipeline_command(
    mode: CommandMode,
    *,
    target_values: list[str] | None,
    silent: bool,
    dry_run: bool,
    name_filter: str | None = None,
    origin_values: list[str] | None = None,
    names: list[str | None] | list[str] | None = None,
    manifest: str | None = None,
    remap_values: list[str] | None = None,
    include_schedules: bool = False,
    guid_maps_override: list[dict[str, str] | None] | None = None,
    on_success: Callable[..., None] | None = None,
) -> None:
    """Shared entry for pipeline CLI commands and the interactive wizard."""
    from fabric_tools.client import FabricClient
    from fabric_tools.confirm import (
        confirm_delete_pipeline,
        confirm_deploy_actions_pipeline,
        confirm_download_overwrites_pipeline,
        resolve_pipeline_download_files,
    )
    from fabric_tools.pipeline.compare import run_compare_batch as run_pl_compare
    from fabric_tools.pipeline.ops import run_delete_batch as run_pl_delete
    from fabric_tools.pipeline.ops import run_deploy_batch as run_pl_deploy
    from fabric_tools.pipeline.ops import run_download_batch as run_pl_download
    from fabric_tools.validate import run_dry_run_pipeline

    def deploy_confirm_kwargs(req: SyncRequest) -> dict:
        return {
            "include_schedules": include_schedules,
            "guid_map_line": req.map_line,
        }

    def deploy_kwargs(req: SyncRequest) -> dict:
        return {
            "include_schedules": include_schedules,
            "guid_maps": req.guid_maps or None,
        }

    def download_kwargs(_req: SyncRequest) -> dict:
        return {"include_schedules": include_schedules}

    def compare_kwargs(_req: SyncRequest) -> dict:
        return {"include_schedules": include_schedules}

    spec = KindSpec(
        kind=KIND_PIPELINE,
        status_label="pipeline",
        make_client=FabricClient,
        resolve_inputs=wrap_five_tuple_resolve(_resolve_pipeline_inputs),
        resolve_deploy_names=_resolve_pipeline_deploy_names,
        run_dry_run=run_dry_run_pipeline,
        resolve_download_files=resolve_pipeline_download_files,
        confirm_download=confirm_download_overwrites_pipeline,
        confirm_deploy=confirm_deploy_actions_pipeline,
        confirm_delete=confirm_delete_pipeline,
        run_download=run_pl_download,
        run_deploy=run_pl_deploy,
        run_compare=run_pl_compare,
        run_delete=run_pl_delete,
        supports_remap=True,
        validate_flags=require_remap_deploy_only,
        dry_run_notes=remap_dry_run_notes,
        download_kwargs=download_kwargs,
        deploy_confirm_kwargs=deploy_confirm_kwargs,
        deploy_kwargs=deploy_kwargs,
        compare_kwargs=compare_kwargs,
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
            remap_values=remap_values,
            guid_maps_override=guid_maps_override,
        ),
    )

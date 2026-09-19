"""Orchestration for Dataflow Gen2 sync commands."""

from __future__ import annotations

from collections.abc import Callable

import typer

from fabric_tools.colours import FG_OK
from fabric_tools.manifest import KIND_DATAFLOW
from fabric_tools.parsing import CommandMode
from fabric_tools.sync.common import (
    _exit_error,
    _resolve_dataflow_deploy_names,
    _resolve_dataflow_inputs,
)
from fabric_tools.sync.orchestrator import (
    KindSpec,
    SyncRequest,
    remap_dry_run_notes,
    require_remap_deploy_only,
    run_sync_command,
    wrap_five_tuple_resolve,
)


def run_dataflow_command(
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
    publish: bool = False,
    guid_maps_override: list[dict[str, str] | None] | None = None,
    on_success: Callable[..., None] | None = None,
) -> None:
    """Shared entry for dataflow (Gen2) CLI commands and the interactive wizard."""
    from fabric_tools.client import FabricClient
    from fabric_tools.confirm import (
        confirm_delete_dataflow,
        confirm_deploy_actions_dataflow,
        confirm_download_overwrites_dataflow,
        resolve_dataflow_download_files,
    )
    from fabric_tools.dataflow.compare import run_compare_batch as run_df_compare
    from fabric_tools.dataflow.ops import run_delete_batch as run_df_delete
    from fabric_tools.dataflow.ops import run_deploy_batch as run_df_deploy
    from fabric_tools.dataflow.ops import run_download_batch as run_df_download
    from fabric_tools.validate import run_dry_run_dataflow

    def validate_flags(req: SyncRequest) -> None:
        require_remap_deploy_only(req)
        if publish and req.mode is not CommandMode.DEPLOY:
            _exit_error("--publish / -p is only valid with deploy")

    def dry_run_notes(req: SyncRequest) -> None:
        remap_dry_run_notes(req)
        if publish:
            typer.secho(
                "publish: would run Apply Changes after each successful deploy",
                fg=FG_OK,
            )

    def deploy_confirm_kwargs(req: SyncRequest) -> dict:
        return {"guid_map_line": req.map_line, "publish": publish}

    def deploy_kwargs(req: SyncRequest) -> dict:
        return {"guid_maps": req.guid_maps or None, "publish": publish}

    spec = KindSpec(
        kind=KIND_DATAFLOW,
        status_label="dataflow",
        make_client=FabricClient,
        resolve_inputs=wrap_five_tuple_resolve(_resolve_dataflow_inputs),
        resolve_deploy_names=_resolve_dataflow_deploy_names,
        run_dry_run=run_dry_run_dataflow,
        resolve_download_files=resolve_dataflow_download_files,
        confirm_download=confirm_download_overwrites_dataflow,
        confirm_deploy=confirm_deploy_actions_dataflow,
        confirm_delete=confirm_delete_dataflow,
        run_download=run_df_download,
        run_deploy=run_df_deploy,
        run_compare=run_df_compare,
        run_delete=run_df_delete,
        supports_remap=True,
        validate_flags=validate_flags,
        dry_run_notes=dry_run_notes,
        deploy_confirm_kwargs=deploy_confirm_kwargs,
        deploy_kwargs=deploy_kwargs,
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

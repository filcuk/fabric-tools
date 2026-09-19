"""Orchestration for User Data Function sync commands."""

from __future__ import annotations

from collections.abc import Callable

from fabric_tools.manifest import KIND_UDF
from fabric_tools.parsing import CommandMode
from fabric_tools.sync.common import (
    _resolve_udf_deploy_names,
    _resolve_udf_inputs,
)
from fabric_tools.sync.orchestrator import (
    KindSpec,
    SyncRequest,
    remap_dry_run_notes,
    require_remap_deploy_only,
    run_sync_command,
    wrap_five_tuple_resolve,
)


def run_udf_command(
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
    guid_maps_override: list[dict[str, str] | None] | None = None,
    on_success: Callable[..., None] | None = None,
) -> None:
    """Shared entry for UDF CLI commands and the interactive wizard."""
    from fabric_tools.client import FabricClient
    from fabric_tools.confirm import (
        confirm_delete_udf,
        confirm_deploy_actions_udf,
        confirm_download_overwrites_udf,
        resolve_udf_download_files,
    )
    from fabric_tools.sync.common import _exit_error
    from fabric_tools.udf.compare import run_compare_batch as run_udf_compare
    from fabric_tools.udf.ops import UdfAuthError, check_udf_user_auth
    from fabric_tools.udf.ops import run_delete_batch as run_udf_delete
    from fabric_tools.udf.ops import run_deploy_batch as run_udf_deploy
    from fabric_tools.udf.ops import run_download_batch as run_udf_download
    from fabric_tools.validate import run_dry_run_udf

    try:
        check_udf_user_auth()
    except UdfAuthError as exc:
        _exit_error(str(exc))

    def deploy_confirm_kwargs(req: SyncRequest) -> dict:
        return {"guid_map_line": req.map_line}

    def deploy_kwargs(req: SyncRequest) -> dict:
        return {"guid_maps": req.guid_maps or None}

    spec = KindSpec(
        kind=KIND_UDF,
        status_label="udf",
        make_client=FabricClient,
        resolve_inputs=wrap_five_tuple_resolve(_resolve_udf_inputs),
        resolve_deploy_names=_resolve_udf_deploy_names,
        run_dry_run=run_dry_run_udf,
        resolve_download_files=resolve_udf_download_files,
        confirm_download=confirm_download_overwrites_udf,
        confirm_deploy=confirm_deploy_actions_udf,
        confirm_delete=confirm_delete_udf,
        run_download=run_udf_download,
        run_deploy=run_udf_deploy,
        run_compare=run_udf_compare,
        run_delete=run_udf_delete,
        supports_remap=True,
        validate_flags=require_remap_deploy_only,
        dry_run_notes=remap_dry_run_notes,
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
